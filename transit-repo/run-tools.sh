#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-analyzers:latest}"
OUT_DIR="${SCRIPT_DIR}/artifacts"
WORK_DIR="${SCRIPT_DIR}/.multi-work"
REBUILD="${REBUILD:-0}"
KEEP_WORK="${KEEP_WORK:-0}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"

TOOLS=(tokei scc repomix gitingest files-to-prompt)

usage() {
    cat <<'EOF'
Usage: run-tools.sh [options] [repo ...]

Runs 5 repo-analysis tools (tokei, scc, repomix, gitingest, files-to-prompt)
in a container on each repo and saves raw output under artifacts/<repo>/<tool>/.

Options:
  -o, --out DIR     Output directory (default: <script_dir>/artifacts)
  -r, --rebuild     Force rebuild of the container image
  -R, --runtime X   Container runtime: podman|docker (default: auto-detect)
  -k, --keep        Keep temporary clones of remote repos
  -f, --force       Re-run tools even if an output file already exists
  -h, --help        Show this help

Arguments (one or more):
  /path/to/repo          Local repository directory to analyze
  https://.../repo       Remote repository URL (shallow-cloned to a temp dir)
  name:https://.../repo  Remote URL with an explicit artifact name

With no arguments, the 10 repos previously analyzed with whatsun are used.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--out) OUT_DIR="$2"; shift 2 ;;
        -r|--rebuild) REBUILD=1; shift ;;
        -R|--runtime) RUNTIME="$2"; shift 2 ;;
        -k|--keep) KEEP_WORK=1; shift ;;
        -f|--force) SKIP_EXISTING=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) break ;;
    esac
done

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

image_exists() { "$RUNTIME" image exists "$IMAGE" 2>/dev/null; }

if [[ "$REBUILD" -eq 1 ]] || ! image_exists; then
    echo "==> Building image $IMAGE"
    "$RUNTIME" build -t "$IMAGE" "$SCRIPT_DIR"
else
    echo "==> Image $IMAGE already present (use -r/--rebuild to force)"
fi

mkdir -p "$OUT_DIR"

cleanup() {
    if [[ "$KEEP_WORK" -ne 1 && -d "$WORK_DIR" ]]; then
        echo "==> Cleaning up temp clones"
        rm -rf "$WORK_DIR"
    fi
}
trap cleanup EXIT

run_tool() {
    local repo_dir="$1" name="$2" tool="$3"
    local td="$OUT_DIR/$name/$tool"
    mkdir -p "$td"
    local base=("$RUNTIME" run --rm -v "$repo_dir:/repo:ro" -v "$td:/out" "$IMAGE")
    echo "==> [$name] $tool"
    case "$tool" in
        tokei)
            "${base[@]}" sh -c 'tokei /repo --output json > /out/tokei.json'
            ;;
        scc)
            "${base[@]}" sh -c 'scc /repo --format json > /out/scc.json'
            ;;
        repomix)
            "${base[@]}" sh -c 'cd /out && repomix /repo --output repomix.txt --style plain' > "$td/repomix.log" 2>&1
            ;;
        gitingest)
            "${base[@]}" sh -c 'cd /out && gitingest /repo' > "$td/gitingest.log" 2>&1
            ;;
        files-to-prompt)
            "${base[@]}" sh -c 'files-to-prompt /repo > /out/prompt.txt'
            ;;
    esac
    echo "       -> $td/"
}

REPOS=("$@")
if [[ ${#REPOS[@]} -eq 0 ]]; then
    REPOS=(
        "go-gin|https://github.com/gin-gonic/gin"
        "gin|https://github.com/gin-gonic/gin"
        "go-mux|https://github.com/gorilla/mux"
        "java-gson|https://github.com/google/gson"
        "java-springboot|https://github.com/spring-projects/spring-boot"
        "k8s-kubernetes|https://github.com/kubernetes/kubernetes"
        "os-nova|https://github.com/openstack/nova"
        "os-neutron|https://github.com/openstack/neutron"
        "py-flask|https://github.com/pallets/flask"
        "glance|https://github.com/openstack/glance"
    )
fi

fail=0

for entry in "${REPOS[@]}"; do
    name=""; url=""; localdir=""
    if [[ "$entry" == *"|"* ]]; then
        name="${entry%%|*}"; url="${entry#*|}"
    elif [[ "$entry" =~ ^https?:// ]]; then
        url="$entry"; name="$(basename "$entry" .git)"
    else
        localdir="$entry"; name="$(basename "$entry")"
    fi

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
        if [[ ! -d "$localdir" ]]; then
            echo "error: not a directory: $localdir" >&2
            continue
        fi
        repo_dir="$(cd "$localdir" && pwd)"
    fi

    for tool in "${TOOLS[@]}"; do
        if [[ "$SKIP_EXISTING" -eq 1 ]]; then
            if [[ -f "$OUT_DIR/$name/$tool/tokei.json" || -f "$OUT_DIR/$name/$tool/scc.json" \
                  || -f "$OUT_DIR/$name/$tool/repomix.txt" || -f "$OUT_DIR/$name/$tool/digest.txt" \
                  || -f "$OUT_DIR/$name/$tool/prompt.txt" ]]; then
                echo "==> [$name] $tool already has output, skipping (-f to force)"
                continue
            fi
        fi
        if ! run_tool "$repo_dir" "$name" "$tool"; then
            echo "!! [$name] $tool FAILED" >&2
            fail=1
        fi
    done
done

if [[ "$fail" -eq 1 ]]; then
    echo "==> Done with errors. Some outputs may be missing."
    exit 1
fi
echo "==> Done. Artifacts in $OUT_DIR"
