#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-analyzers-java:latest}"
OUT_DIR="${SCRIPT_DIR}/artifacts"
WORK_DIR="${SCRIPT_DIR}/.multi-work"
REBUILD="${REBUILD:-0}"
KEEP_WORK="${KEEP_WORK:-0}"
SKIP_EXISTING="${SKIP_EXISTING:-1}"
LANGS="${LANGS:-java}"

# Tool -> primary output file that indicates "already scanned"
JAVA_TOOLS="pmd|cpd-report.xml
checkstyle|checkstyle-report.xml
spotbugs|spotbugs-report.xml"
PY_TOOLS="py-ruff|ruff.json
py-bandit|bandit.json
py-radon|radon-cc.json"
SHARED_TOOLS="depcheck|dependency-check-report.json
scc|scc.json
repomix|repomix.txt"

usage() {
    cat <<'EOF'
Usage: run-tools.sh [options] [repo ...]

Offline static analysis pipeline. Runs analyzers in a container per repo:
  pmd / cpd  (code quality, security, design, duplication)
  checkstyle (Google Java style conventions)
  spotbugs   (bug patterns + FindSecBugs security, requires compiled classes)
  depcheck   (OWASP dependency-check: CVE scan of dependencies)
  scc        (LOC / complexity metrics)
  repomix    (full-codebase LLM pack)

Raw output is saved under artifacts/<repo>/<tool>/.

Options:
  -o, --out DIR     Output directory (default: <script_dir>/artifacts)
  -l, --lang X      Language scan set: java|python|all (default: java)
  -r, --rebuild     Force rebuild of the container image
  -R, --runtime X   Container runtime: podman|docker (default: auto-detect)
  -k, --keep        Keep temporary clones of remote repos
  -f, --force       Re-run tools even if an output file already exists
  -h, --help        Show this help

Arguments (one or more):
  /path/to/repo          Local repository directory to analyze
  https://.../repo       Remote repository URL (shallow-cloned to a temp dir)
  name:https://.../repo  Remote URL with an explicit artifact name

With no arguments, Java-facing default repos are used.

Language sets:
  java    PMD+CPD, checkstyle, spotbugs, depcheck, scc, repomix
  python  ruff, bandit, radon, depcheck, scc, repomix
  all     both of the above (language-matched tools skip repos they cannot scan)

Offline note: the image analyzers-java:latest bundles every tool. Build it on a
connected machine, then `docker save` / `docker load` it onto air-gapped hosts.
At scan time no network access is required (dependency-check reports CVEs only
as current as its bundled NVD snapshot).
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--out) OUT_DIR="$2"; shift 2 ;;
        -l|--lang) LANGS="$2"; shift 2 ;;
        -r|--rebuild) REBUILD=1; shift ;;
        -R|--runtime) RUNTIME="$2"; shift 2 ;;
        -k|--keep) KEEP_WORK=1; shift ;;
        -f|--force) SKIP_EXISTING=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) break ;;
    esac
done

case "$LANGS" in
    java)   TOOL_OUTPUTS="$JAVA_TOOLS
$SHARED_TOOLS" ;;
    python) TOOL_OUTPUTS="$PY_TOOLS
$SHARED_TOOLS" ;;
    all)    TOOL_OUTPUTS="$JAVA_TOOLS
$PY_TOOLS
$SHARED_TOOLS" ;;
    *) echo "error: unknown --lang '$LANGS' (use java|python|all)" >&2; exit 1 ;;
esac

has_files() { # <dir> <glob> — true if the repo contains matching source files
    [[ -d "$1" ]] && find "$1" -type f -name "$2" \
        -not -path "*/.git/*" -not -path "*/node_modules/*" \
        -not -path "*/__pycache__/*" -not -path "*/.venv/*" \
        -print -quit 2>/dev/null | grep -q .
}

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
    echo "==> Building image $IMAGE (requires network; first build only)"
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
    local repo_dir="$1" name="$2" tool="$3" outfile="$4"
    local td="$OUT_DIR/$name/$tool"
    mkdir -p "$td"
    local base=("$RUNTIME" run --rm -v "$repo_dir:/repo:ro" -v "$td:/out" "$IMAGE")
    echo "==> [$name] $tool"
    case "$tool" in
        pmd)
            # code quality + security + design + performance rulesets, then CPD duplication
            "${base[@]}" sh -c \
                'cd /out && /opt/pmd/bin/pmd check -d /repo -f xml \
                    -R category/java/errorprone.xml \
                    -R category/java/bestpractices.xml \
                    -R category/java/design.xml \
                    -R category/java/codestyle.xml \
                    -R category/java/performance.xml \
                    -R category/java/security.xml \
                    --report-file pmd-report.xml \
                    --no-cache || true' \
                > "$td/pmd.log" 2>&1 || true
            "${base[@]}" sh -c \
                'cd /out && /opt/pmd/bin/pmd cpd --minimum-tokens 100 --dir /repo \
                    --language java --format xml -r cpd-report.xml \
                    --no-fail-on-violation --no-fail-on-error || true' \
                > "$td/cpd.log" 2>&1 || true
            ;;
        checkstyle)
            "${base[@]}" sh -c \
                'java -Xmx4g -jar /opt/checkstyle/checkstyle.jar \
                    -c /opt/checkstyle/google_checks.xml \
                    -f xml -o /out/checkstyle-report.xml /repo || true' \
                > "$td/checkstyle.log" 2>&1 || true
            ;;
        spotbugs)
            # requires compiled classes/jars in the repo (e.g. vendored lib/*.jar
            # or prior build output); reports an empty result otherwise.
            "${base[@]}" sh -c '
                find /repo -type f \( -name "*.jar" -o -name "*.class" \) \
                    ! -path "*/test/*" ! -path "*/test-classes/*" \
                    ! -name "*sources.jar" ! -name "*javadoc.jar" 2>/dev/null \
                    > /tmp/sb-targets.txt
                if [ -s /tmp/sb-targets.txt ]; then
                    java -Xmx4g -jar /opt/spotbugs/lib/spotbugs.jar -textui \
                        -effort:max \
                        -pluginList /opt/spotbugs/plugin/findsecbugs-plugin.jar \
                        -xml:withMessages -output /out/spotbugs-report.xml \
                        -analyzeFromFile /tmp/sb-targets.txt || true
                else
                    printf '"'"'%s\n'"'"' \
                        "<?xml version=\"1.0\"?><BugCollection version=\"4.0\"><BugInstance><ShortMessage>No compiled classes or jars found; SpotBugs requires bytecode. Run a build or vendor dependencies first.</ShortMessage></BugInstance></BugCollection>" \
                        > /out/spotbugs-report.xml
                    echo "no compiled classes/jars found — SpotBugs empty result" >&2
                fi' \
                > "$td/spotbugs.log" 2>&1 || true
            ;;
        depcheck)
            # OWASP dependency-check. Offline: uses bundled NVD snapshot if
            # PRESEED_NVD was used at build; otherwise reports a warning and
            # exits non-zero (tolerated). Exit code 1 just means "CVEs found".
            "${base[@]}" sh -c \
                'cd /out && timeout 1800 /opt/dependency-check/bin/dependency-check.sh \
                    --scan /repo --project "'"$name"'" --format JSON --out /out \
                    --data /opt/dependency-check/data \
                    --noupdate --disableCentral --disableRetireJs \
                    --disableHostedSuppressions 2>&1 || true' \
                > "$td/depcheck.log" 2>&1 || true
            # Offline without a pre-seeded NVD snapshot yields no report; stub it.
            if [[ ! -f "$td/dependency-check-report.json" ]]; then
                {
                    echo '{"project":{"name":"'"$name"'"},"reportSchema":"1.0",'
                    echo '"scanInfo":{"engineVersion":"offline-stub"},'
                    echo '"dependencies":[],"warnings":["NVD database unavailable offline; pre-seed via: docker build --build-arg PRESEED_NVD=1"]}'
                } > "$td/dependency-check-report.json"
            fi
            ;;
        scc)
            "${base[@]}" sh -c 'scc /repo --format json > /out/scc.json' \
                > "$td/scc.log" 2>&1 || true
            ;;
        repomix)
            "${base[@]}" sh -c \
                'cd /out && repomix /repo --output repomix.txt --style plain' \
                > "$td/repomix.log" 2>&1 || true
            ;;
        py-ruff)
            # Python lint/quality (ruff); exit 1 = violations found, tolerated
            "${base[@]}" sh -c \
                'cd /out && ruff check /repo --no-cache \
                    --output-format json --output-file ruff.json || true' \
                > "$td/ruff.log" 2>&1 || true
            ;;
        py-bandit)
            # Python security scanner; exit 1 = issues found, tolerated
            "${base[@]}" sh -c \
                'cd /out && bandit -r /repo -f json -o bandit.json -q || true' \
                > "$td/bandit.log" 2>&1 || true
            ;;
        py-radon)
            # Cyclomatic complexity (cc), raw LOC and maintainability index
            "${base[@]}" sh -c \
                'cd /out && radon cc /repo -j > radon-cc.json; \
                 radon raw /repo -j > radon-raw.json; \
                 radon mi /repo -j > radon-mi.json' \
                > "$td/radon.log" 2>&1 || true
            ;;
    esac
    if [[ ! -f "$td/$outfile" ]]; then
        echo "!! [$name] $tool produced no $outfile" >&2
        return 1
    fi
    echo "       -> $td/"
}

# Default Java-facing repo set (name|URL).
REPOS=("$@")
if [[ ${#REPOS[@]} -eq 0 ]]; then
    REPOS=(
        "java-gson|https://github.com/google/gson"
        "java-guava|https://github.com/google/guava"
        "java-commons-lang|https://github.com/apache/commons-lang"
        "java-caffeine|https://github.com/ben-manes/caffeine"
        "java-junit5|https://github.com/junit-team/junit5"
        "java-netty|https://github.com/netty/netty"
        "java-springboot|https://github.com/spring-projects/spring-boot"
        "java-kafka|https://github.com/apache/kafka"
        "java-tomcat|https://github.com/apache/tomcat"
        "java-elasticsearch|https://github.com/elastic/elasticsearch"
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
            echo "==> Cloning $name (shallow; requires network)"
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

    while read -r line; do
        [[ -z "$line" ]] && continue
        tool="${line%%|*}"; outfile="${line#*|}"
        case "$tool" in
            pmd|checkstyle|spotbugs)
                if ! has_files "$repo_dir" "*.java"; then
                    echo "==> [$name] $tool skipped (no .java files)"
                    continue
                fi ;;
            py-ruff|py-bandit|py-radon)
                if ! has_files "$repo_dir" "*.py"; then
                    echo "==> [$name] $tool skipped (no .py files)"
                    continue
                fi ;;
        esac
        if [[ "$SKIP_EXISTING" -eq 1 && -f "$OUT_DIR/$name/$tool/$outfile" ]]; then
            echo "==> [$name] $tool already has output, skipping (-f to force)"
            continue
        fi
        if ! run_tool "$repo_dir" "$name" "$tool" "$outfile"; then
            echo "!! [$name] $tool FAILED" >&2
            fail=1
        fi
    done <<< "$TOOL_OUTPUTS"
done

if [[ "$fail" -eq 1 ]]; then
    echo "==> Done with errors. Some outputs may be missing."
    exit 1
fi
echo "==> Done. Artifacts in $OUT_DIR"