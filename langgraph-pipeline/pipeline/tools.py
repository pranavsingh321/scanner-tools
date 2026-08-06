"""Container shell commands per tool (ports of the transit/internal runners)."""
from __future__ import annotations

from .detect_languages import SEMGREP_INCLUDE

TRANSIT_INVENTORY_TOOLS = ["tokei", "repomix"]
INTERNAL_TOOLS = ["trivy", "gitleaks", "opengrep", "clamav"]
INTERNAL_TARGET_TOOLS = ["nuclei", "naabu", "httpx"]


# ---------------------------------------------------------------------------
# transit inventory stage
# ---------------------------------------------------------------------------
def transit_inventory_script(tool: str) -> str:
    if tool == "tokei":
        return "tokei /repo --output json > /out/tokei.json"
    if tool == "repomix":
        return "cd /out && repomix /repo --output repomix.txt --style plain"
    raise ValueError(f"no inventory command for tool: {tool}")


# ---------------------------------------------------------------------------
# transit quality stage
# ---------------------------------------------------------------------------
def transit_quality_script(tool: str) -> str:
    """Port of run-quality.py tool_script(); each writes rc to /out/.exit."""
    if tool == "ruff":
        return 'ruff check --no-cache /repo --output-format json > /out/ruff.json 2> /out/ruff.log; echo "rc=$?" > /out/.exit'
    if tool == "bandit":
        return 'bandit -r /repo -q -f json -o /out/bandit.json; echo "rc=$?" > /out/.exit'
    if tool == "gosec":
        return 'cd /repo && gosec -fmt=json -out=/out/gosec.json ./...; echo "rc=$?" > /out/.exit'
    if tool == "staticcheck":
        return 'cd /repo && staticcheck ./... > /out/staticcheck.txt 2>&1; echo "rc=$?" > /out/.exit'
    if tool == "shellcheck":
        return ('find /repo -type f \\( -name "*.sh" -o -name "*.bash" \\) '
                '-print0 | xargs -0 -r shellcheck -f json - > /out/shellcheck.json 2> /out/shellcheck.log; '
                'echo "rc=$?" > /out/.exit')
    if tool == "hadolint":
        return ('find /repo -type f \\( -iname "Dockerfile" -o -iname "Dockerfile.*" '
                '-o -iname "Containerfile" -o -iname "Containerfile.*" \\) '
                '-print0 | xargs -0 -r hadolint -f json - > /out/hadolint.json 2> /out/hadolint.log; '
                'echo "rc=$?" > /out/.exit')
    if tool == "gitleaks":
        return ('gitleaks dir /repo --report-format json --report-path /out/gitleaks.json '
                '--no-banner 2> /out/gitleaks.log; echo "rc=$?" > /out/.exit')
    if tool.startswith("semgrep-"):
        category = tool.split("-", 1)[1]
        includes = " ".join(f"--include '{g}'" for g in SEMGREP_INCLUDE[category].split(","))
        return (f'cd /repo && semgrep scan --config /opt/semgrep/default.yaml '
                f'--oss-only --metrics=off {includes} --json -o /out/{tool}.json '
                f'2> /out/{tool}.log; echo "rc=$?" > /out/.exit')
    raise ValueError(f"no command defined for tool: {tool}")


# ---------------------------------------------------------------------------
# internal security stage
# ---------------------------------------------------------------------------
def internal_security_script(tool: str, *, lang: str = "") -> str:
    if tool == "trivy":
        return 'trivy fs --scanners vuln,secret,misconfig --format json --exit-code 0 --no-progress -o /out/trivy.json /repo > /out/trivy.log 2>&1; true'
    if tool == "gitleaks":
        return ('gitleaks dir /repo --report-format json --report-path /out/gitleaks.json '
                '--no-banner > /out/gitleaks.log 2>&1; true')
    if tool == "opengrep":
        return 'opengrep scan --json --config auto /repo > /out/opengrep.json 2>/dev/null; true'
    if tool == "clamav":
        return ('freshclam --quiet > /dev/null 2>&1 || echo "(freshclam: no network or already current)"; '
                'clamscan --recursive --infected --suppress-ok-results /repo > /out/clamav.log 2>&1; true')
    raise ValueError(f"no command defined for tool: {tool}")


def internal_target_script(tool: str, target: str) -> str:
    if tool == "nuclei":
        return f"nuclei -u '{target}' -jsonl -o /out/nuclei.jsonl"
    if tool == "naabu":
        return f"naabu -host '{target}' -json -o /out/naabu.json"
    if tool == "httpx":
        return f"httpx -u '{target}' -json -o /out/httpx.json"
    raise ValueError(f"no command defined for tool: {tool}")
