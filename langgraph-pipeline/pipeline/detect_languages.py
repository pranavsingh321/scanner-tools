"""Language-driven tool selection (port of transit-repo/run-quality.py)."""
from __future__ import annotations

import json
from pathlib import Path

# Tools that run on every repo regardless of language (secrets scanning).
ALWAYS_TOOLS = ["gitleaks"]

# Normalized language category -> security/code-quality tools to run.
LANG_TOOLS = {
    "python": ["ruff", "bandit"],
    "go": ["gosec", "staticcheck"],
    "java": ["semgrep-java"],
    "rust": ["semgrep-rust"],
    "js": ["semgrep-js"],
    "kotlin": ["semgrep-kotlin"],
    "ruby": ["semgrep-ruby"],
    "php": ["semgrep-php"],
    "c": ["semgrep-c"],
    "terraform": ["semgrep-terraform"],
    "shell": ["shellcheck"],
    "dockerfile": ["hadolint"],
}

# File globs semgrep should scan for each category (--include is repeatable).
SEMGREP_INCLUDE = {
    "java": "*.java",
    "rust": "*.rs",
    "js": "*.js,*.jsx,*.mjs,*.ts,*.tsx",
    "kotlin": "*.kt,*.kts",
    "ruby": "*.rb",
    "php": "*.php",
    "c": "*.c,*.h,*.cc,*.cpp,*.hpp,*.cxx",
    "terraform": "*.tf,*.tfvars",
}

_NORMALIZE = {
    "Python": "python", "python": "python",
    "Go": "go",
    "Java": "java",
    "Rust": "rust",
    "JavaScript": "js", "TypeScript": "js",
    "Kotlin": "kotlin", "Groovy": "kotlin",
    "Ruby": "ruby",
    "PHP": "php",
    "C": "c", "C++": "c", "C Header": "c", "C++ Header": "c",
    "Terraform": "terraform", "HCL": "terraform",
    "Shell": "shell", "BASH": "shell", "Zsh": "shell",
    "Dockerfile": "dockerfile",
}


def normalize_lang(name: str) -> str | None:
    return _NORMALIZE.get(name)


def detect_languages(out_dir: Path, name: str, min_code: int) -> list[str] | None:
    """Return language names present in a repo's inventory artifacts.

    Reads artifacts/<name>/tokei/tokei.json and keeps
    every language whose code line count is >= min_code. Dockerfile/Shell/BASH
    are kept by file count instead (a single small file triggers hadolint/shellcheck).
    Returns None if no inventory artifacts exist.
    """
    tokei_json = out_dir / name / "tokei" / "tokei.json"

    if tokei_json.is_file():
        data = json.loads(tokei_json.read_text())
        detected = []
        for lang, entry in data.items():
            code = entry.get("code", 0)
            reports = entry.get("reports", [])
            if code >= min_code or (lang in ("Dockerfile", "Shell", "BASH") and reports):
                detected.append(lang)
        return detected

    return None


def select_tools(languages: list[str]) -> tuple[list[str], list[str]]:
    """Return (tools, unmapped) for the detected languages."""
    categories: list[str] = []
    unmapped: list[str] = []
    for lang in languages:
        cat = normalize_lang(lang)
        if cat is None:
            unmapped.append(lang)
        elif cat not in categories:
            categories.append(cat)

    tools = list(ALWAYS_TOOLS)
    for cat in categories:
        for tool in LANG_TOOLS.get(cat, []):
            if tool not in tools:
                tools.append(tool)
    return tools, unmapped
