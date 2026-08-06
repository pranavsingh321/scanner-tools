"""Graph state: the TypedDict carried between stages, plus supporting models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict


@dataclass
class RepoEntry:
    """One analyzed repo or network target."""

    name: str
    url: str = ""
    localdir: str = ""
    target: str = ""

    @property
    def is_target(self) -> bool:
        return bool(self.target)

    @property
    def upstream(self) -> str:
        """Owner/repo form, or '' for local dirs / bare hosts."""
        if not self.url:
            return ""
        return self.url.rstrip("/").replace("https://", "").replace("http://", "")


@dataclass
class ToolResult:
    """Outcome of one tool run for one repo."""

    tool: str
    status: str = "skipped"          # pending | ok | skipped | failed
    out_dir: str = ""
    findings: int = 0
    exit_code: str = ""              # tool's own exit code (from .exit)
    detail: str = ""


@dataclass
class RepoResult:
    """Per-repo accumulation of tool results, languages, remediation state."""

    name: str
    repo_dir: str = ""
    languages: list[str] = field(default_factory=list)
    tools: dict[str, ToolResult] = field(default_factory=dict)
    quality_tools: list[str] = field(default_factory=list)
    error: str = ""
    summary_path: str = ""
    remediation: dict[str, Any] = field(default_factory=dict)   # branch/pr/merged...
    round: int = 0
    remaining_total: int = 0
    can_merge: bool = False
    refactor_round: int = 0
    refactor_remaining: int = -1
    refactor_changed: bool = False


class PipelineState(TypedDict, total=False):
    """Shared state flowing through the graph.

    Most fields are keyed per stage. `repos` holds the entries; `results` holds
    per-repo results; stage nodes update them in place (annotations use replace
    for these so later stages see the full picture).
    """

    cfg: Any  # RunConfig, imported lazily to avoid a cycle
    entries: list[RepoEntry]
    results: dict[str, RepoResult]
    errors: list[str]
    summaries: dict[str, str]
    merge_status: dict[str, str]
    done: bool
