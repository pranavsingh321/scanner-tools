#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_DIR="${SCRIPT_DIR}/artifacts"
SUMMARY_DIR="${SCRIPT_DIR}/summary"
DIGEST_DIR="${SUMMARY_DIR}/_digests"
OPENCODE_BIN="${OPENCODE_BIN:-opencode}"
MODEL="${OPENCODE_MODEL:-}"
OUTLINE=""

usage() {
    cat <<'EOF'
Usage: agent-summarize.sh [options] [repo ...]

Agentic summarizer: reads scan artifacts for each repo, builds a compact
digest, and drives `opencode run` (LLM agent) to write summary/<repo>.md.

Options:
  -o, --out DIR    Artifact directory (default: <script_dir>/artifacts)
  -m, --model X    LLM model for opencode run (e.g. anthropic/claude-sonnet-4)
  -f, --force      Regenerate summaries that already exist
  -h, --help       Show this help

Arguments:
  <repo>           Name of a repo under artifacts/ (e.g. java-gson)
  With no arguments, all repos that have artifacts are summarized.

Requires: opencode installed and configured with a model. Run
`run-tools.sh` first to produce artifacts. This stash does NOT scan; it only
writes markdown summaries.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--out) ARTIFACT_DIR="$2"; shift 2 ;;
        -m|--model) MODEL="$2"; shift 2 ;;
        -f|--force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) break ;;
    esac
done

[[ -d "$ARTIFACT_DIR" ]] || { echo "error: artifact dir not found: $ARTIFACT_DIR (run run-tools.sh first)" >&2; exit 1; }
command -v "$OPENCODE_BIN" >/dev/null 2>&1 || { echo "error: $OPENCODE_BIN not found on PATH" >&2; exit 1; }
mkdir -p "$SUMMARY_DIR" "$DIGEST_DIR"

# ---------------------------------------------------------------- helpers --

count() { grep -o "$1" "$2" 2>/dev/null | wc -l | tr -d ' '; }
count_unique() { grep -o "$1" "$2" 2>/dev/null | sort -u | wc -l | tr -d ' '; }
top_n() { # pattern file [n]
    local pat="$1" file="$2" n="${3:-8}"
    grep -o "$pat" "$file" 2>/dev/null | sort | uniq -c | sort -rn | head -n "$n"
}
first_int() { grep -oE "$1[0-9,]+" "$2" 2>/dev/null | head -1 | sed -E 's/[^0-9]//g' | tr -d ','; }
first_float() { grep -oE "$1[0-9,.]+" "$2" 2>/dev/null | head -1 | sed -E 's/[^0-9.]//g' | head -1; }

build_digest() { # <repoName> -> path of digest file
    local name="$1"
    local dir="$ARTIFACT_DIR/$name"
    local d="$DIGEST_DIR/$name.md"
    local f
    echo "# $name — scan digest" > "$d"
    echo "" >> "$d"
    echo "_Auto-extracted $(date -u +%Y-%m-%dT%H:%MZ) from artifacts/$name/. The LLM agent reads the full raw reports too._" >> "$d"

    # repomix pack stats
    f="$dir/repomix/repomix.log"
    if [[ -f "$f" ]]; then
        {
            echo -e "\n## repomix pack"
            echo "\`\`\`"
            grep -E "Total (Files|Tokens|Chars)" "$f" | tail -4 || true
            echo "\`\`\`"
        } >> "$d"
    fi

    # PMD quality/security rules
    f="$dir/pmd/pmd-report.xml"
    if [[ -f "$f" ]]; then
        {
            echo -e "\n## PMD (quality/security)"
            echo ""
            echo "- violations: $(count '<violation ' "$f")"
            echo -n "- by priority: "; grep -oE 'priority="[0-9]"' "$f" 2>/dev/null | sort | uniq -c | sort -rn | head -6 | sed 's/  */p/g' | tr '\n' ' '; echo ""
            echo -n "- by ruleset:  "; grep -oE 'ruleset="[^"]+"' "$f" 2>/dev/null | sort | uniq -c | sort -rn | head -8 | sed -E 's/ +([0-9]+) +(.+)/\1x \2/' | tr '\n' '|'; echo ""
            echo ""
            echo "Top rules:"
            top_n 'rule="[^"]+"' "$f" 10 | sed -E 's/^ *([0-9]+) +(.+)/- \1x \2/'
        } >> "$d"
    fi

    # CPD duplication
    f="$dir/pmd/cpd-report.xml"
    if [[ -f "$f" ]]; then
        local dup_lines; dup_lines=$(grep -oE 'lines="[0-9]+"' "$f" 2>/dev/null | sed -E 's/[^0-9]//g' | awk '{s+=$1} END{print s+0}')
        {
            echo -e "\n## CPD (duplication)"
            echo "- duplications: $(count '<duplication ' "$f")"
            echo "- duplicated lines: $dup_lines"
        } >> "$d"
    fi

    # Checkstyle
    f="$dir/checkstyle/checkstyle-report.xml"
    if [[ -f "$f" ]]; then
        {
            echo -e "\n## Checkstyle (style/code conventions)"
            echo ""
            echo "- violations (errors): $(count 'severity="error"' "$f")"
            echo "- violations (warnings): $(count 'severity="warning"' "$f")"
            echo -n "- by check: "; top_n 'source="[^"]+"' "$f" 8 | sed -E 's/^ *([0-9]+) +(.+)/\1x \2/' | tr '\n' '|'; echo ""
        } >> "$d"
    fi

    # SpotBugs + FindSecBugs
    f="$dir/spotbugs/spotbugs-report.xml"
    if [[ -f "$f" ]]; then
        {
            echo -e "\n## SpotBugs / FindSecBugs (bugs + security)"
            echo ""
            echo "- bug instances: $(count '<BugInstance' "$f")"
            echo -n "- by category: "
            grep -oE 'category="[^"]+"' "$f" 2>/dev/null | sort | uniq -c | sort -rn | head -8 | sed -E 's/ +([0-9]+) +(.+)/\1x \2/' | tr '\n' '|'; echo ""
            echo ""
            echo "Top bug types:"
            top_n 'type="[^"]+"' "$f" 8 | sed -E 's/^ *([0-9]+) +(.+)/- \1x \2/'
        } >> "$d"
    fi

    # OWASP dependency-check
    f="$dir/depcheck/dependency-check-report.json"
    if [[ -f "$f" ]]; then
        {
            echo -e "\n## OWASP dependency-check (dependency CVEs)"
            echo ""
            echo "- vulnerable-dependency entries: $(count '"vulnerabilities"' "$f")"
            echo "- total dependencies scanned: $(count '"fileName"' "$f")"
            echo -n "- CVEs: "
            grep -oE 'CVE-[0-9]{4}-[0-9]+' "$f" 2>/dev/null | sort -u | tr '\n' ' '; echo ""
        } >> "$d"
    fi

    # Knowledge graph / complexity
    f="$dir/kg/knowledge-graph.json"
    if [[ -f "$f" ]]; then
        {
            echo -e "\n## Knowledge graph (kg-extractor, JavaParser source-only)"
            echo ""
            echo "- files: $(first_int '"files":' "$f")"
            echo "- packages: $(first_int '"packages":' "$f")"
            echo "- types: $(first_int '"types":' "$f")"
            echo "- methods: $(first_int '"methods":' "$f")"
            echo "- fields: $(first_int '"fields":' "$f")"
            echo "- total LOC: $(first_int '"total_loc":' "$f")"
            echo "- avg method complexity: $(first_float '"avg_method_complexity":' "$f")"
            echo "- avg method LOC: $(first_float '"avg_method_loc":' "$f")"
            echo ""
            echo "Top complexity methods:"
            grep -oE '"type":"[^"]+","method":"[^"]+","complexity":[0-9]+' "$f" 2>/dev/null \
                | sed -E 's/"type":"([^"]+)","method":"([^"]+)","complexity":([0-9]+)/- cc=\3 \1::\2/' | sort -t= -k2 -rn | head -10
            echo ""
            echo "Hub types:"
            grep -oE '"type":"[^"]+","deps":[0-9]+,"dependents":[0-9]+' "$f" 2>/dev/null \
                | sed -E 's/"type":"([^"]+)","deps":([0-9]+),"dependents":([0-9]+)/- deps=\2 dependents=\3 \1/' \
                | sort -k2 -t= -rn | head -10
        } >> "$d"
    fi

    echo "$d"
}

mk_prompt() { # <repoName> <digestPath>
    local name="$1" digest_path="$2"
    cat <<PROMPT_EOF
You are a senior Java code-quality & security analyst. Produce a markdown report for the repository "$name" scanned with an offline static-analysis pipeline.

Evidence to use (read these raw reports yourself inside artifacts/$name/):
- artifacts/$name/pmd/pmd-report.xml and pmd/cpd-report.xml     (PMD rules + copy-paste duplication; includes security.xml, errorprone, bestpractices, design, codestyle, performance)
- artifacts/$name/checkstyle/checkstyle-report.xml               (Google Java style violations)
- artifacts/$name/spotbugs/spotbugs-report.xml                   (SpotBugs + FindSecBugs security bug patterns; note if it says no bytecode found)
- artifacts/$name/depcheck/dependency-check-report.json          (OWASP dependency-check CVEs of dependencies)
- artifacts/$name/kg/knowledge-graph.json                        (knowledge graph: packages, types, edges, complexity, hubs, package deps, cycles; read the "summaries" block)
- artifacts/$name/scc/scc.json                                   (LOC and complexity by language)
- artifacts/$name/repomix/repomix.log                            (LLM pack totals)

A machine-built digest is attached for orientation: $digest_path
Trust the digest numbers for totals, but open the raw XML/JSON when you need specific file/rule/class names. The edge data in knowledge-graph.json is authoritative for the graph section.

OUTPUT FORMAT — write strictly as GitHub-flavored markdown with exactly these sections:

# $name — Java static-analysis report
\`\`\`header row with source repo (if known: derive from artifacts path/user input), scan date, tool versions\`\`\`

## Overview
Leading paragraph + a metrics table (files, LOC, types, methods, LLM pack size). Be truthful to the artifacts; mark anything missing/inconclusive.

## Code Quality
- PMD violation totals split by priority and ruleset; top 5-10 rules with the clearest examples (class/file:line). 
- Checkstyle totals (errors vs warnings) and top checks.
- CPD duplication (amount, % of code if computable, worst files).

## Security
- SpotBugs/FindSecBugs: prioritize categories SECURITY/others; list concrete bug types with a couple of file examples each; state explicitly whether bytecode was unavailable.
- OWASP dependency-check: count of vulnerable dependencies and every CVE id; flag the highest-severity ones.
- PMD security rules violations that stand out (e.g. injection, weak crypto).
- Give a plain-language risk assessment (Low/Medium/High) with justification.

## Complexity
- Cyclomatic complexity: average, max, top-10 worst methods (name + cc + file). Correlate with CPD duplication if relevant.
- Methods/classes with unusual LOC.

## Knowledge graph
- Package count and biggest/most-connected packages (hub types with deps/dependents).
- Strongest package dependency edges (from/to/weight).
- Isolated packages and any dependency cycles.
- 3-5 key architectural takeaways the graph reveals.

## Recommendations
Prioritized, actionable, concrete list (file-level where possible). Distinguish quick wins vs structural work.

Rules: only use evidence from the artifacts. Do not invent metrics. If a tool produced no output, say so. Do not include this prompt. Use precision over hype.
PROMPT_EOF
}

# ------------------------------------------------------------- main ------

REPOS=("$@")
if [[ ${#REPOS[@]} -eq 0 ]]; then
    mapfile -t REPOS < <(find "$ARTIFACT_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
fi

if [[ ${#REPOS[@]} -eq 0 ]]; then
    echo "error: no repos found under $ARTIFACT_DIR" >&2
    exit 1
fi

for name in "${REPOS[@]}"; do
    if [[ ! -d "$ARTIFACT_DIR/$name" ]]; then
        echo "!! $name: no artifacts (skipping)" >&2
        continue
    fi
    out="$SUMMARY_DIR/$name.md"
    if [[ -z "${FORCE:-}" && -f "$out" && "$out" -nt "$ARTIFACT_DIR/$name" ]]; then
        echo "==> [$name] summary exists and is newer than artifacts, skipping (-f to force)"
        continue
    fi
    echo "==> [$name] building digest"
    digest=$(build_digest "$name")
    echo "       digest: $digest"
    prompt=$(mk_prompt "$name" "$digest")
    echo "==> [$name] invoking $OPENCODE_BIN run"
    cmd=("$OPENCODE_BIN" run --title "scan-summary-$name")
    [[ -n "$MODEL" ]] && cmd+=(--model "$MODEL")
    cmd+=("-f" "$digest")
    echo "       cmd: ${cmd[*]}"
    if pushd "$SCRIPT_DIR" >/dev/null; then
        ok=0
        if printf '%s' "$prompt" | "${cmd[@]}" > "$out" 2> "$DIGEST_DIR/$name.opencode.log"; then
            ok=1
        fi
        popd >/dev/null
        [[ "$ok" -eq 1 ]] || { echo "!! [$name] opencode run failed (see $DIGEST_DIR/$name.opencode.log)" >&2; continue; }
    fi
    echo "       -> $out"
done

echo "==> Done. Summaries in $SUMMARY_DIR"