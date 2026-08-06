#!/usr/bin/env python3
"""Phase 1: transit graph — inventory + quality pipeline as a LangGraph state machine.

Stages (nodes): ensure_images → ingest → inventory_scan → detect_languages
→ quality_scan → llm_summarize → remediate ⇄ verify_scan (loop, gated)
→ merge_pr | leave_open → finalize.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from pipeline import findings as F
from pipeline import remediate as RM
from pipeline import refactor as R
from pipeline.config import DEFAULT_REPOS, QUALITY_IMAGE, SCRIPT_DIR, TRANSIT_IMAGE, RunConfig
from pipeline.containers import ensure_images, run_tool
from pipeline.debug import diagnose_and_retry
from pipeline.detect_languages import detect_languages, select_tools
from pipeline.repos import cleanup_work_dir, prepare_work_dir, resolve_repo
from pipeline.state import PipelineState, RepoEntry, RepoResult, ToolResult
from pipeline.summarize import generate_summary
from pipeline.tools import (
    TRANSIT_INVENTORY_TOOLS,
    transit_inventory_script,
    transit_quality_script,
)

REPO_ROOT = SCRIPT_DIR.parent
TRANSIT_DIR = REPO_ROOT / "transit-repo"
QUALITY_DIR = SCRIPT_DIR / "quality"

INVENTORY_OUT = {  # tool -> primary output file
    "tokei": "tokei.json",
    "repomix": "repomix.txt",
}


def build_config(args) -> RunConfig:
    return RunConfig.from_cli(args, image=TRANSIT_IMAGE, quality_dir=QUALITY_DIR)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def node_ensure_images(state: PipelineState) -> dict:
    ensure_images(
        state["cfg"].runtime,
        [
            (TRANSIT_IMAGE, TRANSIT_DIR, None),
            (QUALITY_IMAGE, TRANSIT_DIR, TRANSIT_DIR / "quality.Dockerfile"),
        ],
        rebuild=state["cfg"].rebuild,
    )
    return {}


def node_ingest(state: PipelineState) -> dict:
    cfg = state["cfg"]
    prepare_work_dir(cfg)
    results: dict[str, RepoResult] = state.get("results", {})
    for entry in state["entries"]:
        if entry.is_target:
            continue
        result = results.get(entry.name, RepoResult(name=entry.name))
        try:
            result.repo_dir = resolve_repo(cfg, entry)
        except Exception as exc:  # noqa: BLE001
            result.error = f"ingest failed: {exc}"
            state["errors"].append(f"[{entry.name}] {result.error}")
        results[entry.name] = result
    return {"results": results}


def _run_inventory(cfg: RunConfig, entry: RepoEntry, result: RepoResult) -> None:
    for tool in TRANSIT_INVENTORY_TOOLS:
        out_dir = cfg.out_dir / entry.name / tool
        out_dir.mkdir(parents=True, exist_ok=True)
        primary = INVENTORY_OUT[tool]
        if cfg.force is False and (out_dir / primary).is_file():
            print(f"==> [{entry.name}] {tool} already has output, skipping (-f to force)")
            result.tools[tool] = ToolResult(tool=tool, status="skipped", out_dir=str(out_dir))
            continue
        print(f"==> [{entry.name}] {tool}")
        cmd = transit_inventory_script(tool)
        rc, _ = run_tool(cfg.runtime, cfg.image, cmd, result.repo_dir, out_dir)
        status = "ok"
        bad, reason = F.looks_failed(tool, out_dir)
        if bad:
            print(f"       [debug] {tool}: {reason}")
            debug_status = diagnose_and_retry(cfg, cfg.image, tool, result.repo_dir, out_dir, cmd)
            if debug_status != "ok":
                status = "failed"
                result.error = f"{tool} failed after debug retries"
        result.tools[tool] = ToolResult(
            tool=tool, status=status, out_dir=str(out_dir), exit_code=str(rc),
        )
        print(f"       -> {out_dir}/")



def node_inventory_scan(state: PipelineState) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    for entry in state["entries"]:
        result = results.get(entry.name)
        if result is None or not result.repo_dir:
            continue
        _run_inventory(cfg, entry, result)
    return {"results": results}


def node_detect_languages(state: PipelineState) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    for entry in state["entries"]:
        result = results.get(entry.name)
        if result is None:
            continue
        languages = detect_languages(cfg.out_dir, entry.name, cfg.min_code)
        if languages is None:
            result.error = "no inventory artifacts (no tokei.json)"
            state["errors"].append(f"[{entry.name}] {result.error}")
            continue
        tools, unmapped = select_tools(languages)
        result.languages = languages
        result.quality_tools = tools
        print(f"==> [{entry.name}] languages: {' '.join(languages)}")
        print(f"==> [{entry.name}] quality tools: {' '.join(tools)}")
        if unmapped:
            print(f"==> [{entry.name}] no tool mapped for: {' '.join(unmapped)}")
    return {"results": results}


def node_quality_scan(state: PipelineState) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    for entry in state["entries"]:
        result = results.get(entry.name)
        if result is None or getattr(result, "quality_tools", None) is None:
            continue
        for tool in result.quality_tools:
            out_dir = cfg.quality_dir / entry.name / tool
            out_dir.mkdir(parents=True, exist_ok=True)
            if cfg.force is False and (out_dir / ".exit").is_file():
                print(f"==> [{entry.name}] {tool} already has output, skipping (-f to force)")
                result.tools[tool] = ToolResult(tool=tool, status="skipped", out_dir=str(out_dir))
                continue
            print(f"==> [{entry.name}] {tool}")
            cmd = transit_quality_script(tool)
            rc, _ = run_tool(cfg.runtime, QUALITY_IMAGE, cmd, result.repo_dir, out_dir)
            status = "ok"
            bad, reason = F.looks_failed(tool, out_dir)
            if bad:
                print(f"       [debug] {tool}: {reason}")
                debug_status = diagnose_and_retry(cfg, QUALITY_IMAGE, tool, result.repo_dir, out_dir, cmd)
                if debug_status == "skip":
                    print(f"       -> {out_dir}/ (skipped: transient upstream failure)")
                    result.tools[tool] = ToolResult(tool=tool, status="skipped", out_dir=str(out_dir))
                    continue
                if debug_status != "ok":
                    status = "failed"
                    result.error = f"{tool} failed after debug retries"
            exit_file = out_dir / ".exit"
            if exit_file.is_file():
                rc_tool = exit_file.read_text().strip().removeprefix("rc=")
                status = status if status == "failed" else ("ok" if rc_tool == "0" else "findings")
                result.tools[tool] = ToolResult(tool=tool, status=status, out_dir=str(out_dir), exit_code=rc_tool)
            else:
                result.tools[tool] = ToolResult(tool=tool, status=status, out_dir=str(out_dir))
            print(f"       -> {out_dir}/ ({status})")
    return {"results": results}


def node_llm_summarize(state: PipelineState) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    summaries: dict[str, str] = {}
    for entry in state["entries"]:
        result = results.get(entry.name)
        if result is None or result.error:
            if result is not None:
                summaries[entry.name] = f"# {entry.name}\n\n(no summary: {result.error})"
            continue
        tools = [t for t in result.tools if result.tools[t].status not in ("skipped", "failed")]
        source = entry.url or entry.localdir or entry.target
        try:
            path = generate_summary(cfg, entry.name, cfg.out_dir, tools, source, quality_dir=cfg.quality_dir)
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
        if result is None or not result.repo_dir or entry.is_target:
            continue
        if not getattr(result, "quality_tools", None):
            continue
        if result.round >= RM.MAX_ROUNDS:
            continue
        if result.remaining_total == 0:
            continue
        result.round += 1
        print(f"==> [{entry.name}] remediation round {result.round}")
        try:
            message = RM.run_agent(
                cfg, result, cfg.quality_dir, result.quality_tools,
                transit_quality_script, QUALITY_IMAGE, round_number=result.round,
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
        if result is None or not result.repo_dir or entry.is_target:
            continue
        if not getattr(result, "quality_tools", None):
            continue
        if result.round == 0:
            continue
        remaining = RM.verify_remaining(
            cfg, result, result.quality_tools, transit_quality_script, QUALITY_IMAGE
        )
        result.remaining_total = sum(remaining.values())
        result.remediation["remaining"] = remaining
        result.can_merge = result.remaining_total == 0
        print(f"==> [{entry.name}] verify: {result.remaining_total} remaining "
              f"({'GATE PASS' if result.can_merge else 'gate NOT passed'})")
    return {"results": results}


def after_verify(state: PipelineState) -> str:
    """Route from verify_scan: loop fixes, or move to refactor/merge/leave."""
    for entry in state["entries"]:
        result = state["results"].get(entry.name)
        if result is None or not result.repo_dir:
            continue
        if result.remaining_total and result.round < RM.MAX_ROUNDS:
            return "loop"
    # Remediation settled; refactor next if automation is on and it could do work.
    if state["cfg"].remediate and _llm_available():
        return "refactor"
    return _route_after_automation(state)


def _llm_available() -> bool:
    from pipeline.llm import llm_configured
    return llm_configured()


def node_refactor(state: PipelineState) -> dict:
    cfg = state["cfg"]
    if not cfg.remediate or not _llm_available():
        return {}
    results = state["results"]
    for entry in state["entries"]:
        result = results.get(entry.name)
        if result is None or not result.repo_dir or entry.is_target:
            continue
        if not getattr(result, "quality_tools", None):
            continue
        if result.remaining_total:
            continue  # only refactor code whose remediation gate passed
        if result.refactor_round >= R.MAX_REFACTOR_ROUNDS:
            continue
        result.refactor_round += 1
        print(f"==> [{entry.name}] refactor round {result.refactor_round} (single responsibility)")
        before = RM.diff_hash(result.repo_dir)
        try:
            message = R.refactor_repo(cfg, result, result.quality_tools, transit_quality_script, QUALITY_IMAGE)
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
        result = results.get(entry.name)
        if result is None or not result.repo_dir or entry.is_target:
            continue
        if not getattr(result, "quality_tools", None) or result.refactor_round == 0:
            continue
        remaining = RM.verify_remaining(
            cfg, result, result.quality_tools, transit_quality_script, QUALITY_IMAGE
        )
        total = sum(remaining.values())
        result.remaining_total = total
        result.refactor_remaining = total
        result.remediation["refactor_remaining"] = remaining
        result.can_merge = total == 0
        print(f"==> [{entry.name}] refactor verify: {total} remaining "
              f"({'GATE PASS' if result.can_merge else 'gate NOT passed'})")
    return {"results": results}


def _route_after_automation(state: PipelineState) -> str:
    """Final routing: merge (gate passed) | leave open | none."""
    if any(
        (r := state["results"].get(e.name)) is not None
        and r.can_merge and RM.has_edits(r.repo_dir)
        for e in state["entries"]
    ):
        return "merge"
    if any(
        (r := state["results"].get(e.name)) is not None
        and RM.has_edits(r.repo_dir)
        for e in state["entries"]
    ):
        return "leave"
    return "none"


def after_refactor_verify(state: PipelineState) -> str:
    """Route from verify_refactor: loop refactor, or final merge/leave routing."""
    for entry in state["entries"]:
        result = state["results"].get(entry.name)
        if result is None or not result.repo_dir:
            continue
        if (result.refactor_remaining and result.refactor_changed
                and result.refactor_round < R.MAX_REFACTOR_ROUNDS):
            return "loop"
    return _route_after_automation(state)


def node_merge_pr(state: PipelineState) -> dict:
    return _pr_for(state, merge_only=True)


def node_leave_open(state: PipelineState) -> dict:
    return _pr_for(state, merge_only=False)


def _pr_for(state: PipelineState, merge_only: bool) -> dict:
    cfg = state["cfg"]
    results = state["results"]
    for entry in state["entries"]:
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
    g.add_node("inventory_scan", node_inventory_scan)
    g.add_node("detect_languages", node_detect_languages)
    g.add_node("quality_scan", node_quality_scan)
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
    g.add_edge("ingest", "inventory_scan")
    g.add_edge("inventory_scan", "detect_languages")
    g.add_edge("detect_languages", "quality_scan")
    g.add_edge("quality_scan", "llm_summarize")
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
    parser = argparse.ArgumentParser(prog="transit_graph", description="LangGraph inventory+quality pipeline")
    parser.add_argument("repos", nargs="*", help="name, URL, name:URL, or local directory")
    parser.add_argument("-o", "--out", default=str(SCRIPT_DIR / "artifacts"))
    parser.add_argument("-r", "--rebuild", action="store_true")
    parser.add_argument("-R", "--runtime")
    parser.add_argument("-k", "--keep", action="store_true")
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("--no-remediate", action="store_true", help="scan + summarize only")
    parser.add_argument("--no-merge", action="store_true", help="open PR but never merge")
    args = parser.parse_args()

    cfg = build_config(args)
    entries = [RepoEntry(name=n, url=u) for n, u in DEFAULT_REPOS] if not args.repos else _parse(args.repos)

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


def _parse(entries: list[str]) -> list[RepoEntry]:
    from pipeline.config import parse_entries
    return parse_entries(entries)


if __name__ == "__main__":
    main()
