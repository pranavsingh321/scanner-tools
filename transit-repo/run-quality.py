#!/usr/bin/env python3
"""Language-driven security & code-quality runner (Python alternative).

Python counterpart to run-quality.sh. It reads the language mix from the
inventory artifacts produced by run-tools.sh (artifacts/<repo>/scc/scc.json,
falling back to tokei.json) and runs only the security/code-quality tools
mapped to the languages actually present in each repo. Results land in
quality/<repo>/<tool>/.

Why this exists: it is a more readable, comment-driven version of the shell
script, using Python data structures instead of stringly bash parsing. Keep
the tool mapping (LANG_TOOLS, SEMGREP_INCLUDE, tool_script) in sync with
quality-tools.sh if you change one.

Usage:
    ./run-quality.py                        # default repos (need artifacts first)
    ./run-quality.py py-flask               # single already-analyzed repo
    ./run-quality.py go-gin:https://github.com/gin-gonic/gin
    ./run-quality.py -f go-gin              # force re-run
    MIN_CODE=20 ./run-quality.py os-nova    # lower language threshold
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Configuration (mirrors quality-tools.sh). Edit these to add tools/languages.
# ---------------------------------------------------------------------------

# Container image that holds all quality tools; built from quality.Dockerfile.
IMAGE = os.environ.get("IMAGE", "quality:latest")
DOCKERFILE = "quality.Dockerfile"

# The default set of repos, as (artifact name, clone URL) pairs.
DEFAULT_REPOS = [
    ("go-gin", "https://github.com/gin-gonic/gin"),
    ("go-mux", "https://github.com/gorilla/mux"),
    ("java-gson", "https://github.com/google/gson"),
    ("java-springboot", "https://github.com/spring-projects/spring-boot"),
    ("os-nova", "https://github.com/openstack/nova"),
    ("os-neutron", "https://github.com/openstack/neutron"),
    ("py-flask", "https://github.com/pallets/flask"),
    ("glance", "https://github.com/openstack/glance"),
]

# Tools that run on every repo regardless of language (secrets scanning).
ALWAYS_TOOLS = ["gitleaks"]

# Normalized language category -> security/code-quality tools to run.
# "semgrep-<lang>" runs the vendored semgrep ruleset scoped to that language.
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


def normalize_lang(name: str):
    """Map an scc.json / tokei.json language name to a category key.

    Returns None for languages that have no tooling mapped to them.
    """
    mapping = {
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
    return mapping.get(name)


def detect_languages(out_dir: Path, name: str, min_code: int) -> list | None:
    """Return the language names present in a repo's inventory artifacts.

    Reads artifacts/<name>/scc/scc.json (falling back to tokei.json) and keeps
    every language whose code line count is >= min_code. Dockerfile/Shell/BASH
    are kept by file count instead: even a single small Dockerfile or .sh
    (under min_code lines) warrants running hadolint/shellcheck.

    Returns None if no inventory artifacts exist (the repo was never analyzed
    by run-tools.sh).
    """
    scc_json = out_dir / name / "scc" / "scc.json"
    tokei_json = out_dir / name / "tokei" / "tokei.json"

    if scc_json.is_file():
        data = json.loads(scc_json.read_text())
        detected = []
        for entry in data:
            lang = entry.get("Name", "")
            code = entry.get("Code", 0)
            count = entry.get("Count", 0)
            if code >= min_code or (lang in ("Dockerfile", "Shell", "BASH") and count > 0):
                detected.append(lang)
        return detected

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


def select_tools(languages: list) -> tuple:
    """Turn a repo's detected languages into the list of tools to run.

    Returns (tools, unmapped) where `unmapped` lists detected languages that
    have no tooling mapped to them (only reported, not an error).
    """
    categories = []
    unmapped = []
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


def tool_script(tool: str) -> str:
    """The container shell command for one tool.

    Each command writes the tool's own exit code to /out/.exit after running,
    so a non-zero linter exit code ("findings") is not mistaken for a
    container/script failure by the caller.
    """
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
        # One semgrep run per language, restricted to that language's files
        # via --include globs. Uses the ruleset vendored into the image at
        # build time, so scanning works fully offline.
        category = tool.split("-", 1)[1]
        globs = SEMGREP_INCLUDE[category].split(",")
        includes = " ".join(f"--include '{g}'" for g in globs)
        return (f'cd /repo && semgrep scan --config /opt/semgrep/default.yaml '
                f'--oss-only --metrics=off {includes} --json -o /out/{tool}.json '
                f'2> /out/{tool}.log; echo "rc=$?" > /out/.exit')
    raise ValueError(f"no command defined for tool: {tool}")


def resolve_repo(entry: str):
    """Parse a repo argument into (name, url_or_None, localdir_or_None).

    Accepted forms:
      name:https://...      artifact name + remote URL
      https://...           bare URL (name derived from the URL)
      /path/to/repo         local directory
      name                  bare name resolved against DEFAULT_REPOS
    """
    if ":" in entry and not entry.startswith(("http://", "https://")):
        name, url = entry.split(":", 1)
        return name, url, None
    if entry.startswith(("http://", "https://")):
        url = entry.rstrip("/")
        return url.rsplit("/", 1)[-1].removesuffix(".git"), url, None
    path = Path(entry).expanduser()
    if path.is_dir():
        return path.name, None, str(path.resolve())
    # Bare name: look it up in DEFAULT_REPOS for the clone URL.
    for name, url in DEFAULT_REPOS:
        if name == entry:
            return name, url, None
    raise ValueError(f"not a directory and no known URL: {entry}")


def ensure_repo(runtime: str, work_dir: Path, name: str, url: str, localdir: str) -> str:
    """Make sure the repo source is available on disk and return its path.

    Local dirs are used as-is. Remote URLs are shallow-cloned into work_dir
    (cleaned up on exit unless --keep is given).
    """
    if url:
        clone_dir = work_dir / name
        if not (clone_dir / ".git").is_dir():
            if clone_dir.exists():
                shutil.rmtree(clone_dir)
            print(f"==> Cloning {name} (shallow)")
            subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, str(clone_dir)], check=True)
        return str(clone_dir)
    return localdir


def image_present(runtime: str) -> bool:
    return subprocess.run([runtime, "image", "exists", IMAGE], capture_output=True).returncode == 0


def ensure_image(runtime: str, rebuild: bool) -> None:
    if rebuild or not image_present(runtime):
        print(f"==> Building image {IMAGE}")
        subprocess.run([runtime, "build", "-t", IMAGE, "-f", str(SCRIPT_DIR / DOCKERFILE), str(SCRIPT_DIR)], check=True)
    else:
        print(f"==> Image {IMAGE} already present (use -r/--rebuild to force)")


def run_tool(runtime: str, tool: str, repo_dir: str, out_dir: Path) -> int:
    """Run one quality tool against a repo in the container.

    Mounts the repo read-only at /repo and the output dir at /out, then runs
    the tool's shell command. Returns the container's exit code (a non-zero
    value means the container itself failed to run); the tool's own exit code
    is left in out_dir/.exit.
    """
    cmd = [
        runtime, "run", "--rm",
        "-v", f"{repo_dir}:/repo:ro",
        "-v", f"{out_dir}:/out",
        IMAGE, "sh", "-c", tool_script(tool),
    ]
    return subprocess.run(cmd).returncode


def detect_runtime() -> str:
    """Pick podman or docker, whichever is installed and has a running daemon."""
    for candidate in ("podman", "docker"):
        if shutil.which(candidate):
            if subprocess.run([candidate, "info"], capture_output=True).returncode == 0:
                return candidate
    raise SystemExit("error: neither podman nor docker with a running daemon found")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="run-quality.py",
        description="Run security/code-quality tools for each repo, selected from "
                    "the languages detected in its inventory artifacts.",
    )
    parser.add_argument("-o", "--out", default=str(SCRIPT_DIR / "artifacts"), help="inventory artifacts directory")
    parser.add_argument("-q", "--quality", dest="quality", default=str(SCRIPT_DIR / "quality"), help="quality output directory")
    parser.add_argument("-r", "--rebuild", action="store_true", help="force rebuild of the quality image")
    parser.add_argument("-R", "--runtime", help="container runtime: podman|docker")
    parser.add_argument("-k", "--keep", action="store_true", help="keep temporary clones of remote repos")
    parser.add_argument("-f", "--force", action="store_true", help="re-run tools even if output exists")
    parser.add_argument("repos", nargs="*", help="name, URL, name:URL, or local directory")
    args = parser.parse_args()

    out_dir = Path(args.out)
    quality_dir = Path(args.quality)
    work_dir = SCRIPT_DIR / ".multi-work"
    min_code = int(os.environ.get("MIN_CODE", "50"))

    runtime = args.runtime or detect_runtime()
    ensure_image(runtime, args.rebuild)

    quality_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    repos = args.repos or [f"{name}:{url}" for name, url in DEFAULT_REPOS]
    failed = False

    for entry in repos:
        name = None
        try:
            name, url, localdir = resolve_repo(entry)
        except ValueError as exc:
            print(f"!! [{entry}] {exc}", file=sys.stderr)
            failed = True
            continue

        try:
            repo_dir = ensure_repo(runtime, work_dir, name, url, localdir)
        except subprocess.CalledProcessError:
            print(f"!! [{name}] clone failed", file=sys.stderr)
            failed = True
            continue

        # 1. Read the repo's languages from its inventory artifacts.
        languages = detect_languages(out_dir, name, min_code)
        if languages is None:
            print(f"!! [{name}] no inventory artifacts (no scc.json/tokei.json). Run ./run-tools.sh {name} first.", file=sys.stderr)
            failed = True
            continue

        # 2. Select only the tools relevant to those languages.
        tools, unmapped = select_tools(languages)
        print(f"==> [{name}] languages: {' '.join(languages)}")
        print(f"==> [{name}] tools: {' '.join(tools)}")
        if unmapped:
            print(f"==> [{name}] no tool mapped for: {' '.join(unmapped)}")

        # 3. Run each selected tool, skipping existing outputs unless forced.
        for tool in tools:
            out_dir_tool = quality_dir / name / tool
            out_dir_tool.mkdir(parents=True, exist_ok=True)

            if args.force is False and (out_dir_tool / ".exit").is_file():
                print(f"==> [{name}] {tool} already has output, skipping (-f to force)")
                continue

            print(f"==> [{name}] {tool}")
            if run_tool(runtime, tool, repo_dir, out_dir_tool) != 0:
                print(f"!! [{name}] {tool} container error", file=sys.stderr)
                failed = True
                continue

            exit_file = out_dir_tool / ".exit"
            if exit_file.is_file():
                rc = exit_file.read_text().strip().removeprefix("rc=")
                status = "OK" if rc == "0" else f"findings (exit {rc})"
                print(f"       -> {out_dir_tool}/ {status}")

    # Clean up temp clones unless the user asked to keep them.
    if not args.keep and work_dir.is_dir():
        print("==> Cleaning up temp clones")
        shutil.rmtree(work_dir, ignore_errors=True)

    if failed:
        print("==> Done with errors. Some outputs may be missing.")
        sys.exit(1)
    print(f"==> Done. Quality output in {quality_dir}")


if __name__ == "__main__":
    main()
