"""Remediation agent + git/gh automation (fork, PR, auto-merge)."""
from __future__ import annotations

import datetime
import shutil
import subprocess
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from . import findings as F
from .agent_tools import make_agent_tools
from .config import RunConfig, gh_account
from .llm import get_llm, remediate_system_prompt
from .state import RepoEntry, RepoResult

MAX_ROUNDS = 2


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _git(repo_dir: str, *args: str, check: bool = True) -> str:
    proc = _run(["git", "-C", repo_dir, *args])
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def findings_text(repo: RepoResult, out_dir: Path, tools: list[str], limit: int = 12) -> str:
    """Structured findings for the agent, capped per tool."""
    lines = []
    for tool in tools:
        td = out_dir / repo.name / tool
        if not td.is_dir():
            continue
        fl = F.parse_dir(td, tool)
        if not fl:
            continue
        lines.append(f"## {tool} ({len(fl)} findings, category={F.FIX_CATEGORY.get(tool,'auto')})")
        for f in fl[:limit]:
            loc = f"{f.file}:{f.line}" if f.line else f.file
            lines.append(f"- [{f.severity}] {f.title} @ {loc} — {f.detail}")
        if len(fl) > limit:
            lines.append(f"  ... and {len(fl) - limit} more")
    return "\n".join(lines) or "(no findings)"


def verify_logs(cfg: RunConfig, repo: RepoResult, tools: list[str], limit_lines: int = 25) -> str:
    """Log tail of the last verify re-run, for the agent to diagnose failures."""
    lines = []
    base = cfg.work_dir / ".verify" / repo.name
    for tool in tools:
        td = base / tool
        if not td.is_dir():
            continue
        logs = sorted(p for p in td.glob("*.log"))
        tail = ""
        for log in logs[-1:]:
            tail = log.read_text(errors="replace").splitlines()[-limit_lines:]
        lines.append(f"## {tool} verify log")
        lines.append("\n".join(tail) if tail else "(no log)")
    return "\n".join(lines)


def run_agent(
    cfg: RunConfig,
    repo: RepoResult,
    out_dir: Path,
    tools: list[str],
    script_for,
    image: str,
    round_number: int = 1,
) -> str:
    """Invoke the remediation agent on the repo; returns its closing message.

    On later rounds the agent is shown the remaining findings (re-parsed from the
    last verify run) plus the verify logs, so it can diagnose why a fix did not work.
    """
    if round_number > 1:
        verify_dir = cfg.work_dir / ".verify" / repo.name
        prompt_findings = findings_text(repo, verify_dir, tools)
        prompt_extra = f"\n\nPrevious verify logs:\n{verify_logs(cfg, repo, tools)}"
    else:
        prompt_findings = findings_text(repo, out_dir, tools)
        prompt_extra = ""
    prompt = (
        f"Findings for {repo.name}:\n\n{prompt_findings}{prompt_extra}\n\n"
        "Read the relevant files, fix what is safe, and run verify_tool for each tool "
        "that had findings. Work in the working tree only; do not commit or push."
    )
    agent = create_react_agent(
        model=get_llm(),
        tools=make_agent_tools(cfg, repo.repo_dir, repo.name, image, script_for),
        prompt=remediate_system_prompt(repo.name, repo.repo_dir),
    )
    result = agent.invoke({"messages": [HumanMessage(prompt)]})
    reply = result.get("messages", [])
    return str(reply[-1].content) if reply else "(no response)"


def verify_remaining(cfg: RunConfig, repo: RepoResult, tools: list[str], script_for, image: str) -> dict[str, int]:
    """Re-run each tool on the fixed working tree; returns tool -> remaining findings."""
    remaining: dict[str, int] = {}
    for tool in tools:
        out_dir = cfg.work_dir / ".verify" / repo.name / tool
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            script = script_for(tool)
        except (KeyError, ValueError):
            continue
        from .containers import run_tool
        run_tool(cfg.runtime, image, script, repo.repo_dir, out_dir)
        remaining[tool] = F.count_findings(out_dir, tool)
    return remaining


def has_edits(repo_dir: str) -> bool:
    return bool(_git(repo_dir, "status", "--porcelain"))


def diff_hash(repo_dir: str) -> str:
    """Hash of the current uncommitted diff (to detect whether an agent changed anything)."""
    return _git(repo_dir, "diff", check=False)


# ---------------------------------------------------------------------------
# GitHub automation
# ---------------------------------------------------------------------------
def ensure_fork(upstream: str, account: str) -> str:
    """Fork owner/repo under `account`; returns the fork's owner/repo."""
    proc = _run(["gh", "repo", "view", f"{account}/{upstream.split('/')[1]}", "--json", "name"])
    if proc.returncode != 0:
        print(f"==> Forking {upstream} under {account}")
        proc = _run(["gh", "repo", "fork", upstream])
        if proc.returncode != 0:
            raise RuntimeError(f"fork failed: {proc.stderr.strip()}")
    return f"{account}/{upstream.split('/')[1]}"


def default_branch(fork: str) -> str:
    proc = _run(["gh", "repo", "view", fork, "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"])
    return proc.stdout.strip() or "main"


def push_and_pr(cfg: RunConfig, entry: RepoEntry, repo: RepoResult, force_no_merge: bool = False) -> dict:
    """Branch, commit, push to fork, open PR; merge when the gate passed."""
    repo_dir = repo.repo_dir
    account = gh_account()
    upstream = entry.upstream
    if not upstream or not shutil.which("gh"):
        return {"status": "skipped", "detail": "no upstream remote or gh CLI missing"}

    fork = ensure_fork(upstream, account)
    base = default_branch(fork)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = f"llm-fix/{repo.name}-{stamp}"

    if not _remote_exists(repo_dir, "fork"):
        _git(repo_dir, "remote", "add", "fork", f"https://github.com/{fork}.git")
    _git(repo_dir, "checkout", "-b", branch)
    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "-m", f"llm-fix: automated remediation for {repo.name}", check=False)
    _git(repo_dir, "push", "-u", "fork", branch)

    title = f"llm-fix: automated remediation for {repo.name}"
    body = (
        f"Automated fixes applied by the langgraph remediation agent "
        f"(round {repo.round}). Verification: "
        f"{'passed' if repo.can_merge else 'FAILED - see comments'}."
    )
    pr = _run([
        "gh", "pr", "create", "--repo", fork, "--base", base, "--head", branch,
        "--title", title, "--body", body,
    ])
    if pr.returncode != 0:
        return {"status": "error", "detail": pr.stderr.strip()}
    url = pr.stdout.strip()

    if cfg.no_merge or force_no_merge or not repo.can_merge:
        _run(["gh", "pr", "comment", url, "--repo", fork, "--body",
              "Verification did not pass; fix is NOT auto-merged. Inspect and re-run."])
        return {"status": "open", "branch": branch, "pr_url": url, "merged": False}

    _run(["gh", "repo", "edit", fork, "--enable-auto-merge", "--default-branch-only", "--delete-branch-on-merge"])
    merge_method = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}.get(
        _merge_method(), "--squash")
    merged = _run(["gh", "pr", "merge", url, "--repo", fork, "--auto", merge_method, "--delete-branch"])
    if merged.returncode != 0:
        return {"status": "merge-failed", "branch": branch, "pr_url": url,
                "detail": merged.stderr.strip(), "merged": False}
    return {"status": "merged", "branch": branch, "pr_url": url, "merged": True}


def _remote_exists(repo_dir: str, name: str) -> bool:
    proc = _run(["git", "-C", repo_dir, "remote"])
    return name in proc.stdout.split()


def _merge_method() -> str:
    import os
    return os.environ.get("MERGE_METHOD", "squash")
