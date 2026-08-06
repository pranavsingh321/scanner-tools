"""Tools exposed to the remediation agent (via langchain tool bindings)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool

from . import findings as F
from .config import RunConfig
from .containers import run_tool


def _git(repo_dir: str, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", repo_dir, *args], capture_output=True, text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout


def make_agent_tools(cfg: RunConfig, repo_dir: str, name: str, image: str, script_for: callable):
    """Build the tool closures for one repo's remediation agent."""

    verify_dir = cfg.work_dir / ".verify" / name
    verify_dir.mkdir(parents=True, exist_ok=True)

    @tool
    def read_file(path: str) -> str:
        """Read a file from the working tree (relative path)."""
        full = (Path(repo_dir) / path).resolve()
        if str(full).startswith(str(Path(repo_dir).resolve())) and full.is_file():
            return full.read_text(errors="replace")[:8000]
        return f"error: cannot read {path}"

    @tool
    def list_files() -> str:
        """List tracked files (relative paths)."""
        return _git(repo_dir, "ls-files")

    @tool
    def apply_patch(patch: str) -> str:
        """Apply a unified diff to the working tree.

        The diff must be in `git diff` format, one or more hunks, with the
        file paths relative to the repo root. Use `--- a/<path>` / `+++ b/<path>`.
        """
        proc = subprocess.run(
            ["git", "-C", repo_dir, "apply", "--recount", "-"],
            input=patch, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return f"patch failed: {proc.stderr.strip() or proc.stdout.strip()}"
        return "patch applied"

    @tool
    def repo_status() -> str:
        """Show the current working-tree diff stat."""
        return _git(repo_dir, "diff", "--stat")

    @tool
    def verify_tool(tool_name: str) -> str:
        """Re-run one analysis tool on the fixed working tree and report remaining findings.

        tool_name is one of: ruff, bandit, gosec, staticcheck, shellcheck, hadolint,
        gitleaks, semgrep-java, semgrep-rust, semgrep-js, semgrep-kotlin, semgrep-ruby,
        semgrep-php, semgrep-c, semgrep-terraform, trivy, opengrep.
        """
        try:
            script = script_for(tool_name)
        except (KeyError, ValueError):
            return f"error: unknown tool {tool_name}"
        out_dir = verify_dir / tool_name
        out_dir.mkdir(parents=True, exist_ok=True)
        run_tool(cfg.runtime, image, script, repo_dir, out_dir)
        n = F.count_findings(out_dir, tool_name)
        fl = F.parse_dir(out_dir, tool_name)
        top = "\n".join(
            f"- {f.title} @ {f.file}:{f.line}" for f in fl[:6]
        ) or "(clean)"
        return f"{n} findings remaining for {tool_name}:\n{top}"

    return [read_file, list_files, apply_patch, repo_status, verify_tool]
