#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-quality:latest}"
OUT_DIR="${SCRIPT_DIR}/artifacts"
QUALITY_DIR="${SCRIPT_DIR}/quality"
WORK_DIR="${SCRIPT_DIR}/.multi-work"
REBUILD="${REBUILD:-0}"
KEEP_WORK="${KEEP_WORK:-0}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
MIN_CODE="${MIN_CODE:-50}"

usage() {
    cat <<'EOF'
Usage: run-quality.sh [options] [repo ...]

Reads the language mix from inventory artifacts (artifacts/<repo>/scc/scc.json,
falling back to tokei.json) and runs only the security/code-quality tools mapped
to the languages present in each repo (quality/<repo>/<tool>/).

Options:
  -o, --out DIR      Inventory artifacts directory (default: <script_dir>/artifacts)
  -q, --quality DIR  Quality output directory (default: <script_dir>/quality)
  -r, --rebuild      Force rebuild of the quality image
  -R, --runtime X    Container runtime: podman|docker (default: auto-detect)
  -k, --keep         Keep temporary clones of remote repos
  -f, --force        Re-run tools even if an output already exists
  -h, --help         Show this help

Arguments (one or more):
  /path/to/repo          Local repository directory to analyze
  https://.../repo       Remote repository URL (shallow-cloned to a temp dir)
  name:https://.../repo  Remote URL with an explicit artifact name
  name                   Repo already analyzed (artifacts/<name> must exist)

Environment: MIN_CODE (default 50) sets the minimum code lines for a language
to be considered present.

With no arguments, the repos with existing inventory artifacts are used.
EOF
}

# --- Parse command-line options -------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--out) OUT_DIR="$2"; shift 2 ;;
        -q|--quality) QUALITY_DIR="$2"; shift 2 ;;
        -r|--rebuild) REBUILD=1; shift ;;
        -R|--runtime) RUNTIME="$2"; shift 2 ;;
        -k|--keep) KEEP_WORK=1; shift ;;
        -f|--force) SKIP_EXISTING=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) break ;;
    esac
done

# --- Container runtime & image ---------------------------------------------------
RUNTIME="${RUNTIME:-}"
if [[ -z "$RUNTIME" ]]; then
    if command -v podman >/dev/null 2>&1; then RUNTIME=podman
    elif command -v docker >/dev/null 2>&1; then RUNTIME=docker
    else echo "error: neither podman nor docker found" >&2; exit 1; fi
fi

if ! "$RUNTIME" info >/dev/null 2>&1; then
    echo "error: $RUNTIME daemon is not running" >&2
    exit 1
fi

command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 1; }

source "$SCRIPT_DIR/quality-tools.sh"

image_exists() { "$RUNTIME" image exists "$IMAGE" 2>/dev/null; }

if [[ "$REBUILD" -eq 1 ]] || ! image_exists; then
    echo "==> Building image $IMAGE"
    "$RUNTIME" build -t "$IMAGE" -f "$SCRIPT_DIR/quality.Dockerfile" "$SCRIPT_DIR"
else
    echo "==> Image $IMAGE already present (use -r/--rebuild to force)"
fi

mkdir -p "$QUALITY_DIR"

cleanup() {
    if [[ "$KEEP_WORK" -ne 1 && -d "$WORK_DIR" ]]; then
        echo "==> Cleaning up temp clones"
        rm -rf "$WORK_DIR"
    fi
}
trap cleanup EXIT

DEFAULT_REPOS=(
    "go-gin|https://github.com/gin-gonic/gin"
    "go-mux|https://github.com/gorilla/mux"
    "java-gson|https://github.com/google/gson"
    "java-springboot|https://github.com/spring-projects/spring-boot"
    "os-nova|https://github.com/openstack/nova"
    "os-neutron|https://github.com/openstack/neutron"
    "py-flask|https://github.com/pallets/flask"
    "glance|https://github.com/openstack/glance"
)

REPOS=("$@")
if [[ ${#REPOS[@]} -eq 0 ]]; then
    REPOS=("${DEFAULT_REPOS[@]}")
fi

default_url() {
    local n="$1" entry=""
    for entry in "${DEFAULT_REPOS[@]}"; do
        if [[ "$entry" == "$n|"* ]]; then
            echo "${entry#*|}"
            return 0
        fi
    done
    return 1
}

detect_languages() {
    local name="$1" scc_json="$OUT_DIR/$name/scc/scc.json" tokei_json="$OUT_DIR/$name/tokei/tokei.json"
    if [[ -f "$scc_json" ]]; then
        # Dockerfile/Shell/BASH are detected by file count: even a single
        # small Dockerfile or .sh (under MIN_CODE lines) warrants tooling.
        jq -r --argjson m "$MIN_CODE" '.[] | select((.Code >= $m) or
            ((.Name == "Dockerfile" or .Name == "Shell" or .Name == "BASH") and .Count > 0)) | .Name' "$scc_json"
    elif [[ -f "$tokei_json" ]]; then
        jq -r --argjson m "$MIN_CODE" 'to_entries[] | select((.value.code >= $m) or
            ((.key == "Dockerfile" or .key == "Shell" or .key == "BASH") and (.value.reports | length) > 0)) | .key' "$tokei_json"
    fi
}

# --- Main loop: one pass per repo ----------------------------------------------
fail=0

for entry in "${REPOS[@]}"; do
    # Step 0 — parse the argument into an artifact name, a clone URL, and/or a
    # local dir. Supported forms: name|url, url (name = basename), local dir,
    # or bare name (URL looked up in DEFAULT_REPOS).
    name=""; url=""; localdir=""
    if [[ "$entry" == *"|"* ]]; then
        name="${entry%%|*}"; url="${entry#*|}"
    elif [[ "$entry" =~ ^https?:// ]]; then
        url="$entry"; name="$(basename "$entry" .git)"
    elif [[ -d "$entry" ]]; then
        localdir="$entry"; name="$(basename "$entry")"
    else
        name="$entry"
        if ! url="$(default_url "$name")"; then
            echo "!! [$name] no local dir and no known URL (add name:https://github.com/... )" >&2
            fail=1
            continue
        fi
    fi

    # Step 1 — make sure the source is on disk (shallow clone remote URLs).
    if [[ -n "$url" ]]; then
        mkdir -p "$WORK_DIR"
        clone_dir="$WORK_DIR/$name"
        if [[ ! -d "$clone_dir/.git" ]]; then
            rm -rf "$clone_dir"
            echo "==> Cloning $name (shallow)"
            git clone --depth 1 --quiet "$url" "$clone_dir"
        fi
        repo_dir="$clone_dir"
    else
        repo_dir="$(cd "$localdir" && pwd)"
    fi

    # Step 2 — read the languages present from the inventory artifacts.
    languages="$(detect_languages "$name")"
    if [[ -z "$languages" ]]; then
        echo "!! [$name] no inventory artifacts (no scc.json/tokei.json). Run ./run-tools.sh $name first." >&2
        fail=1
        continue
    fi

    # Step 3 — map each language to a category, dropping unknown ones (kept in
    # unmapped for reporting) and de-duplicating (bash 3.2 has no associative
    # arrays, so dedup is a linear scan).
    categories=()
    unmapped=()
    while IFS= read -r lang; do
        cat="$(normalize_lang "$lang")"
        if [[ "$cat" == "none" ]]; then
            unmapped+=("$lang")
        else
            present=0
            for existing in ${categories[@]+"${categories[@]}"}; do
                [[ "$existing" == "$cat" ]] && { present=1; break; }
            done
            if [[ "$present" -eq 0 ]]; then
                categories+=("$cat")
            fi
        fi
    done <<< "$languages"

    # Step 4 — select tools: always_tools() run everywhere, plus the tools
    # mapped to each detected category (de-duplicated).
    tools=()
    for t in $(always_tools); do tools+=("$t"); done
    for cat in ${categories[@]+"${categories[@]}"}; do
        for t in $(lang_tools "$cat"); do
            present=0
            for existing in ${tools[@]+"${tools[@]}"}; do
                [[ "$existing" == "$t" ]] && { present=1; break; }
            done
            if [[ "$present" -eq 0 ]]; then
                tools+=("$t")
            fi
        done
    done

    echo "==> [$name] languages: $(echo "$languages" | tr '\n' ' ')"
    echo "==> [$name] tools: ${tools[*]}"
    if [[ ${#unmapped[@]} -gt 0 ]]; then
        echo "==> [$name] no tool mapped for: ${unmapped[*]}"
    fi

    # Step 5 — run each selected tool. Output goes to quality/<name>/<tool>/,
    # tool exit code recorded in .exit (non-zero = findings, not an error).
    for tool in ${tools[@]+"${tools[@]}"}; do
        td="$QUALITY_DIR/$name/$tool"
        mkdir -p "$td"
        if [[ "$SKIP_EXISTING" -eq 1 && -f "$td/.exit" ]]; then
            echo "==> [$name] $tool already has output, skipping (-f to force)"
            continue
        fi
        echo "==> [$name] $tool"
        if ! tool_cmd "$RUNTIME" "$tool" "$repo_dir" "$td"; then
            echo "!! [$name] $tool container error" >&2
            fail=1
            continue
        fi
        if [[ -f "$td/.exit" ]]; then
            rc="$(sed -n 's/^rc=//p' "$td/.exit")"
            if [[ "$rc" -eq 0 ]]; then
                echo "       -> $td/ OK"
            else
                echo "       -> $td/ findings (exit $rc)"
            fi
        fi
    done

    unset categories unmapped present
done

if [[ "$fail" -eq 1 ]]; then
    echo "==> Done with errors. Some outputs may be missing."
    exit 1
fi
echo "==> Done. Quality output in $QUALITY_DIR"
