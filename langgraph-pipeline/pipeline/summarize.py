"""Per-repo summary generation (LLM when configured, mechanical fallback)."""
from __future__ import annotations

from pathlib import Path

from . import findings as F
from .config import RunConfig
from .llm import get_llm, llm_configured, summarize_messages


def build_metrics(out_dir: Path, name: str, tools: list[str], quality_dir: Path | None = None) -> str:
    """A metrics table built from parsed artifacts, one row per tool."""
    rows = []
    for tool in tools:
        td = out_dir / name / tool
        if not td.is_dir():
            continue
        n = F.count_findings(td, tool)
        label = tool
        if tool in ("tokei",):
            label = f"code lines ({tool})"
        elif tool in ("repomix",):
            label = f"pack size KB ({tool})"
        rows.append(f"| {label} | {n} |")
    if quality_dir:
        for tool in tools:
            td = quality_dir / name / tool
            if not td.is_dir():
                continue
            n = F.count_findings(td, tool)
            rows.append(f"| {tool} findings | {n} |")
    return "| Metric | Value |\n|---|---|\n" + "\n".join(rows) if rows else "(no metrics)"


def build_findings_text(
    out_dir: Path,
    name: str,
    tools: list[str],
    quality_dir: Path | None = None,
    limit_per_tool: int = 8,
) -> str:
    """Top findings per tool, capped, formatted for the LLM."""
    lines = []
    for base_dir in (out_dir, quality_dir):
        if base_dir is None:
            continue
        for tool in tools:
            td = base_dir / name / tool
            if not td.is_dir():
                continue
            fl = F.parse_dir(td, tool)
            if not fl:
                continue
            source_tag = "quality" if base_dir == quality_dir else "inventory"
            lines.append(f"### {tool} ({source_tag}, {len(fl)} findings)")
            for f in fl[:limit_per_tool]:
                loc = f"{f.file}:{f.line}" if f.line else f.file
                lines.append(f"- [{f.severity}] {f.title} @ {loc} — {f.detail}")
    return "\n".join(lines) or "(no findings)"


def generate_summary(
    cfg: RunConfig,
    name: str,
    out_dir: Path,
    tools: list[str],
    source: str,
    quality_dir: Path | None = None,
) -> str:
    """Write summary/<name>.md and return its path.

    Uses the LLM when an endpoint is configured; otherwise writes a mechanical
    metrics + findings report so the graph still completes without a key.
    """
    metrics = build_metrics(out_dir, name, tools, quality_dir)
    findings = build_findings_text(out_dir, name, tools, quality_dir)
    if llm_configured():
        llm = get_llm()
        reply = llm.invoke(summarize_messages(name, source, metrics, findings))
        md = reply.content if isinstance(reply.content, str) else str(reply.content)
    else:
        print(f"==> [{name}] no LLM endpoint configured; writing mechanical summary")
        md = mechanical_summary(name, source, metrics, findings)
    cfg.summary_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.summary_dir / f"{name}.md"
    path.write_text(md + "\n")
    return str(path)


def mechanical_summary(name: str, source: str, metrics: str, findings: str) -> str:
    lines = [
        f"# {name} — analysis summary",
        "",
        f"**Source:** {source}",
        "",
        metrics,
        "",
        "## Findings",
        "",
        findings,
        "",
        "## Notes",
        "",
        "Generated mechanically (no LLM endpoint configured). Re-run with "
        "OPENAI_API_KEY/OPENAI_BASE_URL set for an LLM-written report.",
    ]
    return "\n".join(lines)
