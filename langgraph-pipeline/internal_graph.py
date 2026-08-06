#!/usr/bin/env python3
"""Phase 2: internal graph — security analysis pipeline as a LangGraph state machine.

Stages (nodes): ensure_images → ingest → security_scan → (target_scan for
network targets) → llm_summarize → remediate ⇄ verify_scan (loop, gated)
→ merge_pr | leave_open → finalize.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from pipeline import findings as F
from pipeline import remediate as RM
from pipeline import refactor as R
from pipeline.config import DEFAULT_REPOS, INTERNAL_IMAGE, SCRIPT_DIR, RunConfig
from pipeline.containers import ensure_images, run_tool
from pipeline.debug import diagnose_and_retry
from pipeline.repos import cleanup_work_dir, prepare_work_dir, resolve_repo
from pipeline.state import PipelineState, RepoEntry, RepoResult, ToolResult
from pipeline.summarize import generate_summary
from pipeline.tools import (
    INTERNAL_TARGET_TOOLS,
    INTERNAL_TOOLS,
    internal_security_script,
    internal_target_script,
)

INTERNAL_DIR = SCRIPT_DIR.parent / "internal-repo"


def build_config(args) -> RunConfig:
    return RunConfig.from_cli(args, image=INTERNAL_IMAGE)


def detect_language(repo_dir: str) -> str:
    p = Path(repo_dir)
    if (p / "go.mod").is_file():
        return "go"
    if any((p / f).is_file() for f in ("pom.xml", "build.gradle", "build.gradle.kts")):
        return "java"
    if (p / "package.json").is_file():
        return "javascript"
    if any((p / f).is_file() for f in ("requirements.txt", "setup.py", "pyproject.toml")):
        return "python"
    if (p / "Gemfile").is_file():
        return "ruby"
    if (p / "Cargo.toml").is_file():
        return "rust"
    if (p / "CMakeLists.txt").is_file() or (p / "Makefile").is_file():
        return "cpp"
    return "javascript"


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def node_ensure_images(state: PipelineState) -> dict:
    ensure_images(
        state["cfg"].runtime,
        [(INTERNAL_IMAGE, INTERNAL_DIR, None)],
        rebuild=state["cfg"].rebuild,
    )
    return {}


def node_ingest(state: PipelineState) -> dict:
    cfg = state["cfg"]
    prepare_work_dir(cfg)
    results: dict[str, RepoResult] = state.get("results", {})
    for entry in state["entries"]:
        if entry.is_target:
            results.setdefault(entry.name, RepoResult(name=entry.name))
            continue
        result = results.get(entry.name, RepoResult(name=entry.name))
        try:
            result.repo_dir = resolve_repo(cfg, entry)
        except Exception as exc:  # noqa: BLE001
            result.error = f"ingest failed: {exc}"
            state["errors"].append(f"[{entry.name}] {result.error}")
        results[entry.name] = result
    return {"results": results}


def node_security_scan(state: PipelineState) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    for entry in state["entries"]:
        result = results.get(entry.name)
        if result is None or entry.is_target or not result.repo_dir:
            continue
        for tool in INTERNAL_TOOLS:
            out_dir = cfg.out_dir / entry.name / tool
            out_dir.mkdir(parents=True, exist_ok=True)
            print(f"==> [{entry.name}] {tool}")
            script = internal_security_script(tool, lang=detect_language(result.repo_dir))
            rc, _ = run_tool(cfg.runtime, cfg.image, script, result.repo_dir, out_dir)
            status = "ok"
            bad, reason = F.looks_failed(tool, out_dir)
            if bad:
                print(f"       [debug] {tool}: {reason}")
                debug_status = diagnose_and_retry(cfg, cfg.image, tool, result.repo_dir, out_dir, script)
                if debug_status == "skip":
                    print(f"       [debug] {tool}: transient upstream failure -> skipped")
                    result.tools[tool] = ToolResult(tool=tool, status="skipped", out_dir=str(out_dir), exit_code=str(rc))
                    continue
                if debug_status != "ok":
                    status = "failed"
                    result.error = f"{tool} failed after debug retries"
            result.tools[tool] = ToolResult(
                tool=tool, status=status, out_dir=str(out_dir), exit_code=str(rc),
            )
            print(f"       -> {out_dir}/")
    return {"results": results}


def node_target_scan(state: PipelineState) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    for entry in state["entries"]:
        if not entry.is_target:
            continue
        result = results[entry.name]
        for tool in INTERNAL_TARGET_TOOLS:
            out_dir = cfg.out_dir / entry.name / tool
            out_dir.mkdir(parents=True, exist_ok=True)
            print(f"==> [target:{entry.name}] {tool} ({entry.target})")
            rc, _ = run_tool(cfg.runtime, cfg.image, internal_target_script(tool, entry.target), "/tmp", out_dir)
            result.tools[tool] = ToolResult(
                tool=tool, status="ok" if rc == 0 else "failed", out_dir=str(out_dir), exit_code=str(rc)
            )
            print(f"       -> {out_dir}/")
    return {"results": results}


def node_llm_summarize(state: PipelineState) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    summaries: dict[str, str] = {}
    for entry in state["entries"]:
        result = results.get(entry.name)
        if result is None:
            continue
        tools = [t for t in result.tools if result.tools[t].status not in ("skipped", "failed")]
        source = entry.url or entry.localdir or entry.target
        try:
            path = generate_summary(cfg, entry.name, cfg.out_dir, tools, source)
            result.summary_path = path
            summaries[entry.name] = path
            print(f"==> [{entry.name}] summary -> {path}")
        except Exception as exc:  # noqa: BLE001
            state["errors"].append(f"[{entry.name}] summary failed: {exc}")
    return {"results": results, "summaries": summaries}


def node_remediate(state: PipelineState) -> dict:
    cfg = state["cfg"]
    if not cfg.remediate:
        return {}
    results = state["results"]
    for entry in state["entries"]:
        result = results.get(entry.name)
        if result is None or entry.is_target or not result.repo_dir:
            continue
        if result.round >= RM.MAX_ROUNDS or result.remaining_total == 0:
            continue
        fixable = [t for t in INTERNAL_TOOLS if t in result.tools]
        if not fixable:
            continue
        result.round += 1
        print(f"==> [{entry.name}] remediation round {result.round}")
        try:
            message = RM.run_agent(
                cfg, result, cfg.out_dir, fixable, internal_security_script,
                cfg.image, round_number=result.round,
            )
            result.remediation["agent"] = message
        except Exception as exc:  # noqa: BLE001
            result.remediation["agent"] = f"agent error: {exc}"
            state["errors"].append(f"[{entry.name}] remediation agent failed: {exc}")
    return {"results": results}


def node_verify_scan(state: PipelineState) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    for entry in state["entries"]:
        result = results.get(entry.name)
        if result is None or entry.is_target or not result.repo_dir or result.round == 0:
            continue
        fixable = [t for t in INTERNAL_TOOLS if t in result.tools]
        if not fixable:
            continue
        remaining = RM.verify_remaining(cfg, result, fixable, internal_security_script, cfg.image)
        result.remaining_total = sum(remaining.values())
        result.remediation["remaining"] = remaining
        result.can_merge = result.remaining_total == 0
        print(f"==> [{entry.name}] verify: {result.remaining_total} remaining "
              f"({'GATE PASS' if result.can_merge else 'gate NOT passed'})")
    return {"results": results}


def after_verify(state: PipelineState) -> str:
    for entry in state["entries"]:
        if entry.is_target:
            continue
        result = state["results"].get(entry.name)
        if result is None or not result.repo_dir:
            continue
        if result.remaining_total and result.round < RM.MAX_ROUNDS:
            return "loop"
    if state["cfg"].remediate and _llm_available():
        return "refactor"
    return _route_after_automation(state)


def _llm_available() -> bool:
    from pipeline.llm import llm_configured
    return llm_configured()


def _fixable(result: RepoResult) -> list[str]:
    return [t for t in INTERNAL_TOOLS if t in result.tools]


def node_refactor(state: PipelineState) -> dict:
    cfg = state["cfg"]
    if not cfg.remediate or not _llm_available():
        return {}
    results = state["results"]
    for entry in state["entries"]:
        if entry.is_target:
            continue
        result = results.get(entry.name)
        if result is None or not result.repo_dir:
            continue
        if result.remaining_total or result.refactor_round >= R.MAX_REFACTOR_ROUNDS:
            continue
        fixable = _fixable(result)
        if not fixable:
            continue
        result.refactor_round += 1
        print(f"==> [{entry.name}] refactor round {result.refactor_round} (single responsibility)")
        before = RM.diff_hash(result.repo_dir)
        try:
            message = R.refactor_repo(cfg, result, fixable, internal_security_script, cfg.image)
            result.remediation["refactor_agent"] = message
            result.refactor_changed = RM.diff_hash(result.repo_dir) != before
            if not result.refactor_changed:
                print(f"==> [{entry.name}] refactor made no changes")
        except Exception as exc:  # noqa: BLE001
            result.remediation["refactor_agent"] = f"refactor error: {exc}"
            state["errors"].append(f"[{entry.name}] refactor agent failed: {exc}")
    return {"results": results}


def node_verify_refactor(state: PipelineState) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    for entry in state["entries"]:
        if entry.is_target:
            continue
        result = results.get(entry.name)
        if result is None or not result.repo_dir or result.refactor_round == 0:
            continue
        fixable = _fixable(result)
        if not fixable:
            continue
        remaining = RM.verify_remaining(cfg, result, fixable, internal_security_script, cfg.image)
        total = sum(remaining.values())
        result.remaining_total = total
        result.refactor_remaining = total
        result.remediation["refactor_remaining"] = remaining
        result.can_merge = total == 0
        print(f"==> [{entry.name}] refactor verify: {total} remaining "
              f"({'GATE PASS' if result.can_merge else 'gate NOT passed'})")
    return {"results": results}


def _route_after_automation(state: PipelineState) -> str:
    if any(
        (r := state["results"].get(e.name)) is not None
        and r.can_merge and RM.has_edits(r.repo_dir)
        for e in state["entries"] if not e.is_target
    ):
        return "merge"
    if any(
        (r := state["results"].get(e.name)) is not None
        and RM.has_edits(r.repo_dir)
        for e in state["entries"] if not e.is_target
    ):
        return "leave"
    return "none"


def after_refactor_verify(state: PipelineState) -> str:
    for entry in state["entries"]:
        if entry.is_target:
            continue
        result = state["results"].get(entry.name)
        if result is None or not result.repo_dir:
            continue
        if (result.refactor_remaining and result.refactor_changed
                and result.refactor_round < R.MAX_REFACTOR_ROUNDS):
            return "loop"
    return _route_after_automation(state)


def _pr_for(state: PipelineState, merge_only: bool) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    for entry in state["entries"]:
        if entry.is_target:
            continue
        result = results.get(entry.name)
        if result is None or not result.repo_dir or not RM.has_edits(result.repo_dir):
            continue
        if merge_only and not result.can_merge:
            continue
        if not merge_only and result.can_merge:
            continue
        print(f"==> [{entry.name}] pushing PR "
              f"({'auto-merge' if result.can_merge else 'leave open'})")
        try:
            result.remediation.update(RM.push_and_pr(cfg, entry, result, force_no_merge=not result.can_merge))
        except Exception as exc:  # noqa: BLE001
            result.remediation["status"] = f"error: {exc}"
            state["errors"].append(f"[{entry.name}] PR failed: {exc}")
    return {"results": results}


def node_merge_pr(state: PipelineState) -> dict:
    return _pr_for(state, merge_only=True)


def node_leave_open(state: PipelineState) -> dict:
    return _pr_for(state, merge_only=False)


def node_finalize(state: PipelineState) -> dict:
    cfg = state["cfg"]
    cleanup_work_dir(cfg)
    print("\n==> Summary table")
    for entry in state["entries"]:
        result = state["results"].get(entry.name)
        if result is None:
            continue
        status = result.error or "ok"
        rem = result.remediation.get("status", "")
        if rem:
            status += f" | remediation: {rem}"
        print(f"  {entry.name:<20} {status}")
    if state["errors"]:
        print("\n==> Errors:")
        for err in state["errors"]:
            print(f"  !! {err}")
    print("\n==> Done.")
    return {"done": True}


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("ensure_images", node_ensure_images)
    g.add_node("ingest", node_ingest)
    g.add_node("security_scan", node_security_scan)
    g.add_node("target_scan", node_target_scan)
    g.add_node("llm_summarize", node_llm_summarize)
    g.add_node("remediate", node_remediate)
    g.add_node("verify_scan", node_verify_scan)
    g.add_node("refactor", node_refactor)
    g.add_node("verify_refactor", node_verify_refactor)
    g.add_node("merge_pr", node_merge_pr)
    g.add_node("leave_open", node_leave_open)
    g.add_node("finalize", node_finalize)

    g.add_edge(START, "ensure_images")
    g.add_edge("ensure_images", "ingest")
    g.add_edge("ingest", "security_scan")
    g.add_conditional_edges(
        "security_scan",
        lambda s: "target_scan" if any(e.is_target for e in s["entries"]) else "llm_summarize",
        {"target_scan": "target_scan", "llm_summarize": "llm_summarize"},
    )
    g.add_edge("target_scan", "llm_summarize")
    g.add_edge("llm_summarize", "remediate")
    g.add_conditional_edges(
        "remediate",
        lambda s: "verify" if s["cfg"].remediate else "finalize",
        {"verify": "verify_scan", "finalize": "finalize"},
    )
    g.add_conditional_edges(
        "verify_scan",
        after_verify,
        {
            "loop": "remediate",
            "refactor": "refactor",
            "merge": "merge_pr",
            "leave": "leave_open",
            "none": "finalize",
        },
    )
    g.add_conditional_edges(
        "refactor",
        lambda s: "verify" if _llm_available() and s["cfg"].remediate else _route_after_automation(s),
        {"verify": "verify_refactor", "merge": "merge_pr", "leave": "leave_open", "none": "finalize"},
    )
    g.add_conditional_edges(
        "verify_refactor",
        after_refactor_verify,
        {"loop": "refactor", "merge": "merge_pr", "leave": "leave_open", "none": "finalize"},
    )
    g.add_edge("merge_pr", "finalize")
    g.add_edge("leave_open", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def main() -> None:
    parser = argparse.ArgumentParser(prog="internal_graph", description="LangGraph security analysis pipeline")
    parser.add_argument("repos", nargs="*", help="name, URL, name:URL, local dir, or target:HOST")
    parser.add_argument("-o", "--out", default=str(SCRIPT_DIR / "artifacts"))
    parser.add_argument("-r", "--rebuild", action="store_true")
    parser.add_argument("-R", "--runtime")
    parser.add_argument("-k", "--keep", action="store_true")
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("--no-remediate", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    args = parser.parse_args()

    cfg = build_config(args)
    from pipeline.config import parse_entries
    entries = [RepoEntry(name=n, url=u) for n, u in DEFAULT_REPOS] if not args.repos else parse_entries(args.repos)

    graph = build_graph()
    initial: PipelineState = {
        "cfg": cfg,
        "entries": entries,
        "results": {},
        "errors": [],
        "summaries": {},
        "merge_status": {},
        "done": False,
    }
    graph.invoke(initial)
    if cfg.keep:
        print(f"(keeping work dir {cfg.work_dir})")


if __name__ == "__main__":
    main()
