"""Parse tool artifacts into structured findings for summarization + remediation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# How a fix should be treated. "auto" = the agent edits code and can merge;
# "suggest" = the agent writes a suggestion report but may still attempt a patch.
FIX_CATEGORY = {
    "gitleaks": "auto",          # remove/redact leaked secrets
    "ruff": "auto",              # ruff check --fix handles most
    "bandit": "auto",
    "gosec": "auto",
    "staticcheck": "auto",
    "semgrep": "auto",
    "opengrep": "auto",
    "shellcheck": "auto",
    "hadolint": "auto",
    "trivy": "auto",             # dependency upgrades: agent bumps + verifies
    "clamav": "suggest",         # malware findings -> report only
}


@dataclass
class Finding:
    tool: str
    severity: str = "info"
    file: str = ""
    line: str = ""
    title: str = ""
    detail: str = ""
    category: str = "auto"
    raw: dict = field(default_factory=dict)


def _rel(path: str) -> str:
    """Strip the container mount prefix so paths are repo-relative."""
    return path[len("/repo/"):] if path.startswith("/repo/") else path


def _find_file(out_dir: Path, *names: str) -> Path | None:
    for name in names:
        p = out_dir / name
        if p.is_file():
            return p
    return None


def _load_json(path: Path) -> dict | list:
    try:
        return json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}


def _sev(sev: str) -> str:
    return str(sev).lower() if sev else "info"


def parse_dir(out_dir: Path, tool: str) -> list[Finding]:
    """Return findings for one tool's artifact directory (empty if absent)."""
    category = FIX_CATEGORY.get(tool, "auto")
    if tool == "gitleaks":
        p = _find_file(out_dir, "gitleaks.json")
        if not p:
            return []
        out = []
        for f in _load_json(p):
            if not isinstance(f, dict):
                continue
            out.append(Finding(
                tool=tool, severity=_sev(f.get("RuleID", "gitleaks")), category=category,
                file=_rel(str(f.get("File", ""))), line=str(f.get("StartLine", "")),
                title=f.get("RuleID", "gitleaks finding"),
                detail=f.get("Description", f.get("Match", ""))[:200], raw=f,
            ))
        return out

    if tool == "ruff":
        p = _find_file(out_dir, "ruff.json")
        if not p:
            return []
        out = []
        for f in _load_json(p):
            if not isinstance(f, dict):
                continue
            loc = f.get("location", {})
            out.append(Finding(
                tool=tool, severity="error", category=category,
                file=_rel(str(f.get("filename", ""))), line=str(loc.get("row", "")),
                title=f.get("code", "ruff") + " " + f.get("message", ""),
                detail=str(f.get("message", ""))[:200], raw=f,
            ))
        return out

    if tool == "bandit":
        p = _find_file(out_dir, "bandit.json")
        if not p:
            return []
        data = _load_json(p)
        out = []
        for f in (data.get("results") if isinstance(data, dict) else []):
            if not isinstance(f, dict):
                continue
            out.append(Finding(
                tool=tool, severity=_sev(f.get("issue_severity")), category=category,
                file=_rel(str(f.get("filename", ""))), line=str(f.get("line_number", "")),
                title=f.get("test_id", "bandit") + " " + f.get("issue_cwe", {}).get("name", ""),
                detail=str(f.get("issue_text", ""))[:200], raw=f,
            ))
        return out

    if tool == "gosec":
        p = _find_file(out_dir, "gosec.json")
        if not p:
            return []
        data = _load_json(p)
        out = []
        for f in (data.get("Issues") if isinstance(data, dict) else []):
            if not isinstance(f, dict):
                continue
            out.append(Finding(
                tool=tool, severity=_sev(f.get("severity")), category=category,
                file=_rel(str(f.get("file", ""))), line=str(f.get("line", "")),
                title=f.get("rule_id", "gosec"), detail=str(f.get("details", ""))[:200], raw=f,
            ))
        return out

    if tool == "staticcheck":
        p = _find_file(out_dir, "staticcheck.txt")
        if not p:
            return []
        out = []
        pat = re.compile(r"^(.*?):(\d+):(\d+):\s*(.*)$")
        for line in p.read_text(errors="replace").splitlines():
            m = pat.match(line)
            if m:
                out.append(Finding(
                    tool=tool, severity="warning", category=category,
                    file=_rel(m.group(1)), line=m.group(2), title="staticcheck", detail=m.group(4),
                ))
        return out

    if tool.startswith("semgrep-"):
        p = _find_file(out_dir, f"{tool}.json")
        if not p:
            return []
        data = _load_json(p)
        out = []
        for f in (data.get("results") if isinstance(data, dict) else []):
            if not isinstance(f, dict):
                continue
            extra = f.get("extra", {}) or {}
            start = f.get("start", {}) or {}
            out.append(Finding(
                tool=tool, severity=_sev(extra.get("severity")), category=category,
                file=_rel(str(f.get("path", ""))), line=str(start.get("line", "")),
                title=f.get("check_id", "semgrep"),
                detail=str(extra.get("message", ""))[:200], raw=f,
            ))
        return out

    if tool == "opengrep":
        p = _find_file(out_dir, "opengrep.json")
        if not p:
            return []
        data = _load_json(p)
        out = []
        for f in (data.get("results") if isinstance(data, dict) else []):
            if not isinstance(f, dict):
                continue
            extra = f.get("extra", {}) or {}
            start = f.get("start", {}) or {}
            out.append(Finding(
                tool=tool, severity=_sev(extra.get("severity")), category=category,
                file=_rel(str(f.get("path", ""))), line=str(start.get("line", "")),
                title=f.get("check_id", "opengrep"),
                detail=str(extra.get("message", ""))[:200], raw=f,
            ))
        return out

    if tool == "shellcheck":
        p = _find_file(out_dir, "shellcheck.json")
        if not p:
            return []
        out = []
        for f in _load_json(p):
            if not isinstance(f, dict):
                continue
            out.append(Finding(
                tool=tool, severity=_sev(f.get("level", "info")), category=category,
                file=_rel(str(f.get("file", ""))), line=str(f.get("line", "")),
                title=f"SC{f.get('code','')} {f.get('message','')}",
                detail=str(f.get("message", ""))[:200], raw=f,
            ))
        return out

    if tool == "hadolint":
        p = _find_file(out_dir, "hadolint.json")
        if not p:
            return []
        out = []
        for f in _load_json(p):
            if not isinstance(f, dict):
                continue
            out.append(Finding(
                tool=tool, severity=_sev(f.get("severity", "warning")), category=category,
                file=_rel(str(f.get("file", ""))), line=str(f.get("line", "")),
                title=f.get("code", "hadolint") + " " + str(f.get("message", "")),
                detail=str(f.get("message", ""))[:200], raw=f,
            ))
        return out

    if tool == "trivy":
        p = _find_file(out_dir, "trivy.json")
        if not p:
            return []
        data = _load_json(p)
        out = []
        for result in (data.get("Results") if isinstance(data, dict) else []):
            if not isinstance(result, dict):
                continue
            target = result.get("Target", "")
            for v in result.get("Vulnerabilities", []) or []:
                out.append(Finding(
                    tool=tool, severity=_sev(v.get("Severity", "unknown")), category=category,
                    file=_rel(target), line="",
                    title=v.get("VulnerabilityID", "CVE"),
                    detail=f"{v.get('PkgName','')} {v.get('InstalledVersion','')}"
                           f" -> {v.get('FixedVersion','-')}: {v.get('Title','')}"[:200],
                    raw=v,
                ))
        return out

    return []


# ---------------------------------------------------------------------------
# Output validation — used by the AI debug/retry loop to spot failures even
# when the container exits 0 (scripts end with `; true`).
# ---------------------------------------------------------------------------

# tool -> primary output file
PRIMARY_OUT = {
    "tokei": "tokei.json",
    "repomix": "repomix.txt",
    "ruff": "ruff.json",
    "bandit": "bandit.json",
    "gosec": "gosec.json",
    "staticcheck": "staticcheck.txt",
    "shellcheck": "shellcheck.json",
    "hadolint": "hadolint.json",
    "gitleaks": "gitleaks.json",
    "opengrep": "opengrep.json",
    "trivy": "trivy.json",
    "clamav": "clamav.log",
    "nuclei": "nuclei.jsonl",
    "naabu": "naabu.json",
    "httpx": "httpx.json",
}

_ERROR_MARKERS = (
    "error:", "traceback", "panic:", "exception", "failed to", "no such file",
    "cannot find", "command not found", "internal error", "network is unreachable",
    "unexpected eof", "429", "timeout", "connection refused", "unable to",
    "does not exist", "fatal:", "exit status",
)


def primary_output_name(tool: str) -> str:
    if tool.startswith("semgrep-"):
        return f"{tool}.json"
    return PRIMARY_OUT.get(tool, "")


def looks_failed(tool: str, out_dir: Path) -> tuple[bool, str]:
    """Return (is_bad, reason) for a tool's artifact directory.

    A tool run is suspect when the primary output is missing, empty, fails to
    parse, or an adjacent *.log file shows error markers.
    """
    json_root = None
    if tool == "bandit":
        json_root = "results"
    elif tool == "gosec":
        json_root = "Issues"
    elif tool == "trivy":
        json_root = "Results"
    elif tool == "opengrep":
        json_root = "results"

    name = primary_output_name(tool)
    if not name:
        return False, ""
    path = out_dir / name
    if not path.is_file():
        return True, f"primary output {name} missing"
    if path.stat().st_size == 0:
        return True, f"primary output {name} is empty"

    if json_root is not None or tool == "ruff" or tool.startswith("semgrep-"):
        try:
            data = json.loads(path.read_text(errors="replace"))
        except json.JSONDecodeError as exc:
            return True, f"primary output {name} is not valid JSON: {exc}"
        if json_root is not None and isinstance(data, dict) and data.get(json_root) is None:
            return True, f"primary output {name} missing {json_root} section"
        if tool.startswith("semgrep-") and (not isinstance(data, dict) or "results" not in data):
            return True, f"primary output {name} missing results section"

    for log in out_dir.glob("*.log"):
        if log.name == name:
            continue
        content = log.read_text(errors="replace")
        for marker in _ERROR_MARKERS:
            if marker in content:
                return True, f"{log.name} shows '{marker}'"
    return False, ""


def count_findings(out_dir: Path, tool: str) -> int:
    """Fast count used by the metrics tables; falls back to full parse."""
    if tool == "tokei":
        p = _find_file(out_dir, "tokei.json")
        if p:
            data = _load_json(p)
            if isinstance(data, dict):
                return sum(int(e.get("code", 0) or 0) for e in data.values() if isinstance(e, dict))
        return 0
    if tool == "repomix":
        p = _find_file(out_dir, "repomix.txt")
        if p:
            return int(p.stat().st_size // 1024)
        return 0
    if tool == "clamav":
        p = _find_file(out_dir, "clamav.log")
        if p:
            return sum(1 for line in p.read_text(errors="replace").splitlines() if "FOUND" in line)
    return len(parse_dir(out_dir, tool))
