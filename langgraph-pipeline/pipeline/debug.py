"""AI-assisted tool-failure debugging: read logs, fix, re-run, verify.

Mirrors the human (or opencode) loop: a tool produced bad output -> we inspect
the log -> an LLM proposes a corrected container command -> we re-run -> we
validate the output -> stop when it is good or we exhaust retries.
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage

from . import findings as F
from .config import RunConfig
from .containers import run_tool
from .llm import get_llm, llm_configured

MAX_DEBUG_ATTEMPTS = 2


def _gather_context(tool: str, out_dir: Path, original_cmd: str) -> str:
    lines = [f"tool: {tool}", f"command: {original_cmd}", "", "logs:"]
    for log in sorted(out_dir.glob("*")):
        if log.is_file() and log.stat().st_size > 0:
            lines.append(f"--- {log.name} ---")
            lines.append(log.read_text(errors="replace")[-4000:])
    return "\n".join(lines)


def _propose_command(tool: str, out_dir: Path, original_cmd: str) -> str:
    """LLM proposes a corrected sh -c command, or returns SKIP."""
    ctx = _gather_context(tool, out_dir, original_cmd)
    llm = get_llm()
    reply = llm.invoke([
        HumanMessage(content=(
            "A containerized analysis tool produced invalid/missing output. Below is the "
            "tool, the command that ran, and its logs. Diagnose the root cause and propose "
            "a corrected `sh -c` shell command that fixes it (e.g. add a fallback, retry "
            "with different flags, point to the right source). Constraints: the repo is "
            "mounted at /repo (read-only) and output goes to /out. If retrying is pointless, "
            "reply with exactly SKIP.\n\n" + ctx
        )),
    ])
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    text = text.strip().strip("`").strip()
    return text if text.upper() != "SKIP" else "SKIP"


def _mechanical_retry(tool: str) -> str:
    """Fallback without an LLM: known corrections + one plain retry."""
    if tool == "trivy":
        return ("trivy fs --scanners vuln,secret,misconfig --format json --exit-code 0 "
                "--no-progress --skip-dirs 'vendor' -o /out/trivy.json /repo > /out/trivy.log 2>&1; true")
    return "RETRY"


# Errors that are upstream/transient: retrying immediately is pointless and the
# failure is not the repo's fault. Such runs are recorded as "skip", not "failed".
_TRANSIENT_MARKERS = (
    "429", "too many requests", "rate limit", "retry-after", "connection reset",
    "503", "502", "504", "service unavailable", "bad gateway", "temporarily",
    "timed out", "timeout while fetching", "network is unreachable",
)


def _transient_reason(out_dir: Path) -> str:
    """Return the first transient marker found in the tool's logs, or ''."""
    for log in sorted(out_dir.glob("*.log")):
        content = log.read_text(errors="replace")
        for marker in _TRANSIENT_MARKERS:
            if marker in content.lower():
                return f"{log.name} shows '{marker}'"
    return ""


def diagnose_and_retry(
    cfg: RunConfig,
    image: str,
    tool: str,
    repo_dir: str,
    out_dir: Path,
    original_cmd: str,
) -> str:
    """Fix a failed tool run. Returns a status string: 'ok' | 'failed' | 'skip'."""
    reason = _transient_reason(out_dir)
    if reason:
        print(f"       [debug] {tool}: {reason} -> transient, skipping retries")
        return "skip"
    for attempt in range(MAX_DEBUG_ATTEMPTS):
        reason = F.looks_failed(tool, out_dir)
        if not reason[0]:
            return "ok"
        if attempt > 0:
            print(f"       [debug] attempt {attempt}: {reason[1]}")

        if llm_configured():
            try:
                proposed = _propose_command(tool, out_dir, original_cmd)
            except Exception as exc:  # noqa: BLE001
                print(f"       [debug] LLM propose failed: {exc}; using mechanical retry")
                proposed = _mechanical_retry(tool)
        else:
            proposed = _mechanical_retry(tool)
            print(f"       [debug] no LLM endpoint; mechanical retry for {tool}")

        if proposed == "SKIP":
            print(f"       [debug] LLM decided retry is pointless for {tool}")
            return "failed"
        if proposed == "RETRY":
            proposed = original_cmd

        print(f"       [debug] re-running {tool} with corrected command")
        out_dir.mkdir(parents=True, exist_ok=True)
        for stale in out_dir.glob("*"):
            if stale.is_file():
                stale.unlink()
        run_tool(cfg.runtime, image, proposed, repo_dir, out_dir)
    reason = F.looks_failed(tool, out_dir)
    print(f"       [debug] final state for {tool}: {'ok' if not reason[0] else reason[1]}")
    return "ok" if not reason[0] else "failed"
