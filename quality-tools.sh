# quality-tools.sh — sourced by run-quality.sh.
# Language -> tools mapping and per-tool container invocations for the quality image.
# To add a tool: add its language to lang_tools() and a case branch in tool_cmd().

# Tools that run on every repo regardless of language.
always_tools() {
    echo "gitleaks"
}

# Quality tools selected for a normalized language category.
# "semgrep-<lang>" runs semgrep with the vendored ruleset scoped by file glob.
lang_tools() {
    case "$1" in
        python)     echo "ruff bandit" ;;
        go)         echo "gosec staticcheck" ;;
        java)       echo "semgrep-java" ;;
        rust)       echo "semgrep-rust" ;;
        js)         echo "semgrep-js" ;;
        kotlin)     echo "semgrep-kotlin" ;;
        ruby)       echo "semgrep-ruby" ;;
        php)        echo "semgrep-php" ;;
        c)          echo "semgrep-c" ;;
        terraform)  echo "semgrep-terraform" ;;
        shell)      echo "shellcheck" ;;
        dockerfile) echo "hadolint" ;;
    esac
}

# Comma-separated file globs semgrep should scan for a category (--include is repeatable).
semgrep_include() {
    case "$1" in
        java)      echo "*.java" ;;
        rust)      echo "*.rs" ;;
        js)        echo "*.js,*.jsx,*.mjs,*.ts,*.tsx" ;;
        kotlin)    echo "*.kt,*.kts" ;;
        ruby)      echo "*.rb" ;;
        php)       echo "*.php" ;;
        c)         echo "*.c,*.h,*.cc,*.cpp,*.hpp,*.cxx" ;;
        terraform) echo "*.tf,*.tfvars" ;;
    esac
}

# Normalize an scc.json / tokei.json language name to a category key in lang_tools().
normalize_lang() {
    case "$1" in
        Python|python)            echo python ;;
        Go)                       echo go ;;
        Java)                     echo java ;;
        Rust)                     echo rust ;;
        JavaScript|TypeScript)    echo js ;;
        Kotlin|Groovy)            echo kotlin ;;
        Ruby)                     echo ruby ;;
        PHP)                      echo php ;;
        C|C++|"C Header"|"C++ Header") echo c ;;
        Terraform|HCL)            echo terraform ;;
        Shell|BASH|Zsh)           echo shell ;;
        Dockerfile)               echo dockerfile ;;
        *)                        echo "none" ;;
    esac
}

# Run one quality tool in the container. Mounts repo read-only at /repo,
# output dir at /out. Writes the tool's own exit code to /out/.exit so
# "findings" (non-zero) can be distinguished from container/script failures.
tool_cmd() {
    local runtime="$1" tool="$2" repo_dir="$3" out_dir="$4"
    local c=("$runtime" run --rm -v "$repo_dir:/repo:ro" -v "$out_dir:/out" "$IMAGE")
    case "$tool" in
        ruff)
            "${c[@]}" sh -c 'ruff check --no-cache /repo --output-format json > /out/ruff.json 2> /out/ruff.log; echo "rc=$?" > /out/.exit'
            ;;
        bandit)
            "${c[@]}" sh -c 'bandit -r /repo -q -f json -o /out/bandit.json; echo "rc=$?" > /out/.exit'
            ;;
        gosec)
            "${c[@]}" sh -c 'cd /repo && gosec -fmt=json -out=/out/gosec.json ./...; echo "rc=$?" > /out/.exit'
            ;;
        staticcheck)
            "${c[@]}" sh -c 'cd /repo && staticcheck ./... > /out/staticcheck.txt 2>&1; echo "rc=$?" > /out/.exit'
            ;;
        shellcheck)
            "${c[@]}" sh -c 'find /repo -type f \( -name "*.sh" -o -name "*.bash" \) -print0 | xargs -0 -r shellcheck -f json - > /out/shellcheck.json 2> /out/shellcheck.log; echo "rc=$?" > /out/.exit'
            ;;
        hadolint)
            "${c[@]}" sh -c 'find /repo -type f \( -iname "Dockerfile" -o -iname "Dockerfile.*" -o -iname "Containerfile" -o -iname "Containerfile.*" \) -print0 | xargs -0 -r hadolint -f json - > /out/hadolint.json 2> /out/hadolint.log; echo "rc=$?" > /out/.exit'
            ;;
        gitleaks)
            "${c[@]}" sh -c 'gitleaks dir /repo --report-format json --report-path /out/gitleaks.json --no-banner 2> /out/gitleaks.log; echo "rc=$?" > /out/.exit'
            ;;
        semgrep-*)
            local category="${tool#semgrep-}" globs="" g="" include_args=""
            IFS=',' read -r -a globs <<< "$(semgrep_include "$category")"
            for g in "${globs[@]}"; do include_args+=" --include '$g'"; done
            "${c[@]}" sh -c "cd /repo && semgrep scan --config /opt/semgrep/default.yaml --oss-only --metrics=off ${include_args} --json -o '/out/${tool}.json' 2> '/out/${tool}.log'; echo \"rc=\$?\" > /out/.exit"
            ;;
    esac
}
