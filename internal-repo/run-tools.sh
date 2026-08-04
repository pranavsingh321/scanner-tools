#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-internal-analyzers:latest}"
OUT_DIR="${SCRIPT_DIR}/artifacts"
WORK_DIR="${SCRIPT_DIR}/.multi-work"
REBUILD="${REBUILD:-0}"
KEEP_WORK="${KEEP_WORK:-0}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"

REPO_TOOLS=(osv-scanner syft trivy gitleaks trufflehog ggshield opengrep codeql clamav)
TARGET_TOOLS=(nuclei naabu httpx)

usage() {
    cat <<'EOF'
Usage: run-tools.sh [options] [entry ...]

Runs security analysis tools on each repo (or network target) in a container
and saves raw output under artifacts/<name>/<tool>/.

Repo tools (filesystem scans): osv-scanner, syft, trivy, gitleaks,
trufflehog, ggshield, opengrep, codeql, clamav
Target tools (need a live URL/host): nuclei, naabu, httpx

Options:
  -o, --out DIR     Output directory (default: <script_dir>/artifacts)
  -r, --rebuild     Force rebuild of the container image
  -R, --runtime X   Container runtime: podman|docker (default: auto-detect)
  -k, --keep        Keep temporary clones of remote repos
  -f, --force       Re-run tools even if an output file already exists
  -h, --help        Show this help

Environment:
  GITGUARDIAN_API_KEY   Enables the ggshield secrets scan (skipped if unset)

Arguments (one or more):
  /path/to/repo               Local repository directory to analyze
  https://.../repo            Remote repository URL (shallow-cloned to a temp dir)
  name:https://.../repo       Remote URL with an explicit artifact name
  target:https://example.com  Network target: runs nuclei, naabu, httpx only
  name:target:HOST            Network target with an explicit artifact name

With no arguments, the transit-repo default list is used minus k8s-kubernetes (too large).
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
    echo "==> Building image $IMAGE (first build downloads large tool bundles)"
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

primary_output() {
    case "$1" in
        osv-scanner) echo osv-scanner.json ;;
        syft) echo syft.sbom.json ;;
        trivy) echo trivy.json ;;
        gitleaks) echo gitleaks.json ;;
        trufflehog) echo trufflehog.json ;;
        ggshield) echo ggshield.json ;;
        opengrep) echo opengrep.json ;;
        codeql) echo codeql.sarif ;;
        clamav) echo clamav.log ;;
        nuclei) echo nuclei.jsonl ;;
        naabu) echo naabu.json ;;
        httpx) echo httpx.json ;;
        *) echo skip ;;
    esac
}

output_exists() {
    local f
    f="$(primary_output "$2")"
    [[ "$f" != "skip" && -f "$OUT_DIR/$1/$2/$f" ]]
}

detect_language() {
    local dir="$1"
    if [[ -f "$dir/go.mod" ]]; then echo go
    elif [[ -f "$dir/pom.xml" || -f "$dir/build.gradle" || -f "$dir/build.gradle.kts" ]]; then echo java
    elif [[ -f "$dir/package.json" ]]; then echo javascript
    elif [[ -f "$dir/requirements.txt" || -f "$dir/setup.py" || -f "$dir/pyproject.toml" ]]; then echo python
    elif [[ -f "$dir/Gemfile" ]]; then echo ruby
    elif [[ -f "$dir/Cargo.toml" ]]; then echo rust
    elif ls "$dir"/*.csproj >/dev/null 2>&1 || ls "$dir"/*.sln >/dev/null 2>&1; then echo csharp
    elif [[ -f "$dir/CMakeLists.txt" || -f "$dir/Makefile" ]]; then echo cpp
    else echo javascript
    fi
}

run_repo_tool() {
    local repo_dir="$1" name="$2" tool="$3"
    local td="$OUT_DIR/$name/$tool"
    mkdir -p "$td"
    local base=("$RUNTIME" run --rm -v "$repo_dir:/repo:ro" -v "$td:/out" "$IMAGE")
    echo "==> [$name] $tool"
    case "$tool" in
        osv-scanner)
            "${base[@]}" sh -c 'osv-scanner --format json -r /repo > /out/osv-scanner.json 2>/dev/null; true'
            ;;
        syft)
            "${base[@]}" sh -c 'syft dir:/repo -q --output spdx-json=/out/syft.sbom.json && syft dir:/repo --output table > /out/syft.table.txt 2>/dev/null'
            ;;
        trivy)
            "${base[@]}" sh -c 'trivy fs --scanners vuln,secret,misconfig --format json --exit-code 0 --no-progress -o /out/trivy.json /repo > /out/trivy.log 2>&1; true'
            ;;
        gitleaks)
            "${base[@]}" sh -c 'gitleaks dir /repo --report-format json --report-path /out/gitleaks.json --no-banner > /out/gitleaks.log 2>&1; true'
            ;;
        trufflehog)
            "${base[@]}" sh -c 'trufflehog filesystem /repo --json > /out/trufflehog.json 2>/dev/null; true'
            ;;
        ggshield)
            if [[ -n "${GITGUARDIAN_API_KEY:-}" ]]; then
                "$RUNTIME" run --rm -e GITGUARDIAN_API_KEY="$GITGUARDIAN_API_KEY" \
                    -v "$repo_dir:/repo:ro" -v "$td:/out" "$IMAGE" \
                    sh -c 'ggshield secret scan path --recursive --json /repo > /out/ggshield.json 2>/dev/null; true'
            else
                echo "       -> skipped: set GITGUARDIAN_API_KEY to enable ggshield"
                return 0
            fi
            ;;
        opengrep)
            "${base[@]}" sh -c 'opengrep scan --json --config auto /repo > /out/opengrep.json 2>/dev/null; true'
            ;;
        codeql)
            if ! "$RUNTIME" run --rm "$IMAGE" sh -c 'command -v codeql >/dev/null 2>&1' >/dev/null 2>&1; then
                echo "       -> skipped: codeql not installed (GitHub ships an x86_64-only bundle; rebuild on amd64 to enable)"
                return 0
            fi
            local lang
            lang="$(detect_language "$repo_dir")"
            echo "       (codeql language: $lang)"
            "${base[@]}" sh -c "codeql database create /out/codeql-db --overwrite --source-root /repo --language=$lang > /out/codeql.log 2>&1 && codeql database analyze /out/codeql-db --format sarif-latest --output /out/codeql.sarif codeql/$lang-queries >> /out/codeql.log 2>&1; true"
            ;;
        clamav)
            "${base[@]}" sh -c 'freshclam --quiet > /dev/null 2>&1 || echo "(freshclam: no network or already current)"; clamscan --recursive --infected --suppress-ok-results /repo > /out/clamav.log 2>&1; true'
            ;;
    esac
    echo "       -> $td/"
}

run_target_tool() {
    local target="$1" name="$2" tool="$3"
    local td="$OUT_DIR/$name/$tool"
    mkdir -p "$td"
    echo "==> [target:$name] $tool ($target)"
    case "$tool" in
        nuclei)
            "$RUNTIME" run --rm -v "$td:/out" "$IMAGE" \
                sh -c "nuclei -u '$target' -jsonl -o /out/nuclei.jsonl" > "$td/nuclei.log" 2>&1; true
            ;;
        naabu)
            "$RUNTIME" run --rm -v "$td:/out" "$IMAGE" \
                sh -c "naabu -host '$target' -json -o /out/naabu.json" > "$td/naabu.log" 2>&1; true
            ;;
        httpx)
            "$RUNTIME" run --rm -v "$td:/out" "$IMAGE" \
                sh -c "httpx -u '$target' -json -o /out/httpx.json" > "$td/httpx.log" 2>&1; true
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
        "os-nova|https://github.com/openstack/nova"
        "os-neutron|https://github.com/openstack/neutron"
        "py-flask|https://github.com/pallets/flask"
        "glance|https://github.com/openstack/glance"
    )
fi

fail=0

for entry in "${REPOS[@]}"; do
    name=""; url=""; localdir=""; target=""
    if [[ "$entry" == *":target:"* ]]; then
        name="${entry%%:target:*}"; target="${entry#*:target:}"
    elif [[ "$entry" == "target:"* ]]; then
        target="${entry#target:}"
        name="${target#https://}"; name="${name#http://}"; name="$(basename "$name")"
    elif [[ "$entry" == *"|"* ]]; then
        name="${entry%%|*}"; url="${entry#*|}"
    elif [[ "$entry" =~ ^https?:// ]]; then
        url="$entry"; name="$(basename "$entry" .git)"
    else
        localdir="$entry"; name="$(basename "$entry")"
    fi

    if [[ -n "$target" ]]; then
        for tool in "${TARGET_TOOLS[@]}"; do
            if [[ "$SKIP_EXISTING" -eq 1 ]] && output_exists "$name" "$tool"; then
                echo "==> [target:$name] $tool already has output, skipping (-f to force)"
                continue
            fi
            if ! run_target_tool "$target" "$name" "$tool"; then
                echo "!! [target:$name] $tool FAILED" >&2
                fail=1
            fi
        done
        continue
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

    for tool in "${REPO_TOOLS[@]}"; do
        if [[ "$SKIP_EXISTING" -eq 1 ]] && output_exists "$name" "$tool"; then
            echo "==> [$name] $tool already has output, skipping (-f to force)"
            continue
        fi
        if ! run_repo_tool "$repo_dir" "$name" "$tool"; then
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
