# scanner-tools — offline Java static analysis + agentic reporting

Batch Java code analysis with static-analysis tools (PMD, Checkstyle, SpotBugs/FindSecBugs, OWASP dependency-check, scc, repomix), each run in a container per repository, producing raw artifacts and an LLM-agent-generated markdown summary per repo.

Fully **offline at scan time**: every tool is bundled into a single Docker image. Build the image once on a connected machine, transfer it, and scan air-gapped clones with zero internet access.

## Layout

| Path | What it is |
|---|---|
| `Dockerfile` | Multi-stage build → `analyzers-java:latest`, all tools self-contained |
| `run-tools.sh` | Scan driver: runs the analyzers per repo in a container |
| `agent-summarize.sh` | Agentic summarizer: reads artifacts + drives `opencode run` → `summary/<repo>.md` |
| `artifacts/<repo>/<tool>/` | Raw output, one dir per tool per repo |
| `summary/<repo>.md` | LLM-generated code-quality/security/complexity/graph report |

## Tool → output mapping

Per `run_tool()` in `run-tools.sh`:

| Tool | Objective | Output file(s) |
|---|---|---|
| `pmd` | Code quality, security, design, performance, error-prone (6 PMD category rulesets) | `pmd/pmd-report.xml`, `pmd.log` |
| `cpd` (bundled with PMD) | Copy-paste duplication | `pmd/cpd-report.xml` |
| `checkstyle` | Google Java style conventions | `checkstyle/checkstyle-report.xml` |
| `spotbugs` | Bug patterns + FindSecBugs security detectors (needs compiled classes/jars; empty report otherwise) | `spotbugs/spotbugs-report.xml` |
| `depcheck` | OWASP dependency-check — CVEs in dependencies | `depcheck/dependency-check-report.json` |
| `py-ruff` | Python lint/quality (ruff: E/P rules) | `py-ruff/ruff.json` |
| `py-bandit` | Python security scanner (bandit) | `py-bandit/bandit.json` |
| `py-radon` | Python cyclomatic complexity, raw LOC, maintainability index (radon) | `py-radon/radon-cc.json` (+ `radon-raw.json`, `radon-mi.json`) |
| `scc` | LOC/complexity by language | `scc/scc.json` |
| `repomix` | Full-codebase LLM pack (tree, contents, token counts) | `repomix/repomix.txt`, `repomix.log` |

`spotbugs` is the one analyzer that wants bytecode; provide a repo that already contains `*.class`/`*.jar` output or vendored `lib/*.jar`, otherwise it emits an explicit "no bytecode" report. The Python set (`py-ruff`, `py-bandit`, `py-radon`) is 100% source-level and fully offline by construction.

## Language selection

`run-tools.sh -l/--lang java|python|all` picks the analyzer set (default `java`):

| `--lang` | Tools that run |
|---|---|
| `java` | pmd/cpd, checkstyle, spotbugs, depcheck, scc, repomix |
| `python` | py-ruff, py-bandit, py-radon, depcheck, scc, repomix |
| `all` | both sets — language-matched tools auto-skip repos they cannot scan |

Tool applicability is detected per repo (`*.java` / `*.py` presence), so `--lang all` against a mixed codebase runs each analyzer only where it makes sense. `scc` (multi-language), `repomix` (any codebase) and `depcheck` (Python deps via pip/poetry as well as Maven) always run.

```bash
./run-tools.sh --lang python /path/to/python/repo
./run-tools.sh --lang all  /path/to/mixed/repo
```

## Offline workflow

```bash
# 1. On a machine WITH internet: build and export the image
docker build -t analyzers-java:latest .
docker save analyzers-java:latest | gzip > analyzers-java.tar.gz

# 2. Transfer the tarball to the air-gapped machine

# 3. On the OFFLINE machine: load, then scan (no network needed)
gunzip -c analyzers-java.tar.gz | docker load
./run-tools.sh /path/to/cloned/repo
./agent-summarize.sh /path/to/cloned/repo      # requires opencode + a model
```

For full dependency-CVE coverage offline, pre-seed the NVD database **at build time** on the connected machine (~400 MB extra). NVD requires a free API key (register at https://nvd.nist.gov/developers/request-an-api-key):

```bash
docker build --build-arg PRESEED_NVD=1 --build-arg NVD_API_KEY=<your-key> -t analyzers-java:latest .
```

Without it, `depcheck` writes a stub report noting that no offline NVD snapshot is available. All other tools are unaffected.

`docker save`/`load` also works with podman (`podman save`/`podman load`).

## Usage

```bash
./run-tools.sh                       # scan the default Java repo set (see below)
./run-tools.sh /path/to/local/repo   # scan a local directory
./run-tools.sh https://github.com/user/repo              # shallow-clone a remote repo (needs network)
./run-tools.sh myname:https://github.com/user/repo       # remote with explicit artifact name
./agent-summarize.sh java-gson       # generate/refresh one markdown summary
./agent-summarize.sh -m anthropic/claude-sonnet-4        # pick the LLM model (default: OPENCODE_MODEL env)
```

Options (`run-tools.sh`): `-o/--out DIR`, `-l/--lang java|python|all`, `-r/--rebuild`, `-R/--runtime podman|docker`, `-k/--keep` (keep temp clones), `-f/--force`, `-h/--help`.

Options (`agent-summarize.sh`): `-o/--out DIR`, `-m/--model`, `-f/--force`, `-h/--help`. Set `OPENCODE_MODEL` to avoid passing `-m` every time.

Behavior: requires `podman` or `docker`. Builds `analyzers-java:latest` on first run, then reuses it. Remote repos are shallow-cloned to `.multi-work/` (cleaned on exit unless `-k`). Existing outputs are skipped by default (`-f` to override). Tool exit codes are tolerated on purpose — static analyzers exit non-zero when they *find* violations, and the report files are still written.

## Default repos (Java-facing, `run-tools.sh`)

`java-gson` (google/gson), `java-guava` (google/guava), `java-commons-lang` (apache/commons-lang), `java-caffeine` (ben-manes/caffeine), `java-junit5` (junit-team/junit5), `java-netty` (netty/netty), `java-springboot` (spring-projects/spring-boot), `java-kafka` (apache/kafka), `java-tomcat` (apache/tomcat), `java-elasticsearch` (elastic/elasticsearch).

## Agentic summary pipeline

`agent-summarize.sh` is the "agentic" layer. For each repo it:

1. Builds a **machine digest** (`summary/_digests/<repo>.md`) by counting violations/priorities/rules/CVEs/graph totals directly from the XML/JSON artifacts (grep/awk only — no host tooling needed).
2. Invokes `opencode run` (non-interactive) with a detailed analyst prompt that references every raw artifact path (`-f <digest>` attaches the digest).
3. Instructs the model to **open the raw reports itself** and write `summary/<repo>.md` with fixed sections: Overview, Code Quality, Security, Complexity, Knowledge Graph, Recommendations.

The agent reads the full PMD/Checkstyle/SpotBugs/DepCheck data, so the digest only anchors totals — specific findings (file:line, rule ids, CVEs) come from the raw evidence the model inspects.

Requires `opencode` installed and a configured model. Non-interactive `opencode run` auto-rejects permission prompts, so run it from a directory the model may read freely (i.e. this repo, where `artifacts/` lives) — you may need a permissive `opencode.json` permission block in an automation context.

## Build notes

- **Stage 1 (`golang:1.25-alpine`)** builds `scc`.
- **Stage 2 (`eclipse-temurin:21-jdk-alpine`)** downloads PMD 7.27, Checkstyle 14.1 (incl. extracted `google_checks.xml`), SpotBugs 4.10.4 + FindSecBugs 1.14.0, OWASP dependency-check 13.0, and optionally pre-seeds NVD data (`PRESEED_NVD=1` + `NVD_API_KEY`).
- **Final stage** = same JDK base + `git`, `nodejs`/`npm` (for `repomix`), `python3` + `ruff`/`bandit`/`radon` (via pip), all copied tools, and the `scc` binary.

Versions are pinned via build args (`PMD_VERSION`, `CHECKSTYLE_VERSION`, `SPOTBUGS_VERSION`, `FINDSECBUGS_VERSION`, `DEPCHECK_VERSION`, `PRESEED_NVD`, `NVD_API_KEY`).