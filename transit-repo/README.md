# multi-tool

Batch repository analysis using 5 repo-analysis tools, each run in a container against one or more repositories, producing raw artifacts and per-repo markdown summaries.

## Layout

| Path | What it is |
|---|---|
| `run-tools.sh` | Driver script: clones/loads repos, runs each tool in a container, saves output |
| `Dockerfile` | Builds the `analyzers:latest` image containing all 5 tools |
| `run-quality.sh` | Driver script: reads language artifacts, runs matching security/quality tools |
| `run-quality.py` | Python alternative to `run-quality.sh` (same CLI, no jq dependency) |
| `quality-tools.sh` | Sourced config: language → tool mapping and per-tool invocations |
| `quality.Dockerfile` | Builds the `quality:latest` image (ruff, bandit, semgrep, gosec, staticcheck, shellcheck, hadolint, gitleaks) |
| `compose.yaml` | Builds both images via `docker/podman compose build` |
| `run-batch.log` | Console output of the most recent batch run |
| `artifacts/<repo>/<tool>/` | Raw output files, one directory per tool and repo |
| `quality/<repo>/<tool>/` | Security/quality tool output, one directory per tool and repo |
| `summary/<repo>.md` | Hand-written analysis summary per repo (metrics + notes) |

## Tool → output file mapping

Each tool runs inside the container with the repo mounted read-only at `/repo` and its output directory mounted at `/out`. Per `run_tool()` in `run-tools.sh:81`:

| Tool | Language | GitHub stars | Output file(s) | What it produces |
|---|---|---|---|---|
| `tokei` | Rust | 14.8k | `tokei/tokei.json` | LOC, comment, blank counts per language (JSON) |
| `scc` | Go | 8.6k | `scc/scc.json` | Same style LOC metrics per language (JSON), alternative to tokei |
| `repomix` | Node | 27.6k | `repomix/repomix.txt` | Whole-repo packed into one file: summary, tree, all file contents (LLM prompt) |
| `gitingest` | Python | 15.3k | `gitingest/digest.txt`, `gitingest/gitingest.log` | `digest.txt` = directory tree + file contents + token estimate; `.log` = ingestion stats (files, size, tokens) |
| `files-to-prompt` | Python | 2.8k | `files-to-prompt/prompt.txt` | All text files concatenated in prompt-friendly form (skips binaries with warnings) |

Stars as of 2026-08-02: `XAMPPRocky/tokei`, `boyter/scc`, `yamadashy/repomix`, `coderamp-labs/gitingest`, `simonw/files-to-prompt`.

A `*.log` beside a tool's primary output is the tool's own console output, not a separate analysis.

## Tool comparison

### Redundancy
The 5 tools fall into two near-duplicate groups:

| Group | Tools | Notes |
|---|---|---|
| LOC metrics | `tokei` ↔ `scc` | Same per-language code/comment/blank counts. tokei adds per-file reports; scc adds a complexity metric. Keep one. |
| Full-content dumps | `repomix` ↔ `gitingest` ↔ `files-to-prompt` | All emit the repo's file contents (~95% overlap, ~36–38k lines for py-flask). repomix = richest (tree, security check, token metrics); gitingest = token estimate; files-to-prompt = bare concat, skips binaries. Keep one. |

Effective minimal set: **`tokei` (metrics) + `repomix` (content)** — the other three add nothing unique.

### Suitability for LLM input/processing
| Rank | Tool | Why |
|---|---|---|
| 1 | `repomix` | Purpose-built for LLMs: summary header, directory tree, per-file separators, security scan, token counts |
| 2 | `gitingest` | Lighter alternative, plain tree + token estimate |
| 3 | `files-to-prompt` | Bare concatenation, no structure, drops binaries |
| — | `tokei` / `scc` | Not code content — use as a small numeric context block only |

For huge repos (e.g. kubernetes ≈ 225 MB packed) full packing is impractical regardless of tool — prefer `digest.txt` or scope to a subtree.

### Internet access
All 5 tools scan local repos **offline**. Network is only needed for `git clone` (`run-tools.sh:141`) and the image build/tool installs. Optional: `repomix`/`gitingest` can fetch remote repos by URL when invoked that way.

### Language coverage
| Tool | Coverage |
|---|---|
| `tokei` | Broadest explicit database (~200+ languages incl. HCL/Terraform, Go, Java, Python, Rust) |
| `scc` | ~100+ languages, same majors incl. HCL/Terraform, smaller list |
| `repomix` / `gitingest` / `files-to-prompt` | Language-agnostic (pack any text file) — limited only by their ignore/config rules |

## Repos analyzed (default list, `run-tools.sh:114`)

`go-gin` (gin-gonic/gin), `go-mux` (gorilla/mux), `java-gson` (google/gson), `java-springboot` (spring-projects/spring-boot), `os-nova` / `os-neutron` / `glance` (openstack/*), `py-flask` (pallets/flask).

## Usage

```bash
./run-tools.sh                      # analyze the 10 default repos
./run-tools.sh /path/to/local/repo  # analyze a local directory
./run-tools.sh https://github.com/user/repo   # shallow-clone a remote repo
./run-tools.sh myname:https://github.com/user/repo   # remote with explicit artifact name
```

Options: `-o/--out DIR`, `-r/--rebuild` (force image rebuild), `-R/--runtime podman|docker`, `-k/--keep` (keep temp clones), `-f/--force` (re-run even if output exists), `-h/--help`.

Behavior: requires `podman` or `docker`. Builds `analyzers:latest` on first run, then reuses it. Remote repos are shallow-cloned to `.multi-work/` (cleaned up on exit unless `-k`). Existing outputs are skipped by default (`-f` to override).

## Build note

The image is built in two stages (`Dockerfile`): a `rust:alpine` stage compiles `tokei` (cargo) and `scc` (go install), then an `alpine:3.21` runtime stage adds `git`, `nodejs`/`npm` (for `repomix`), and `python3`/`pip` (for `gitingest`, `files-to-prompt`).

The quality image (`quality.Dockerfile`) is separate so the inventory image stays lean: `python:3.12-slim` with pip (`semgrep`, `ruff`, `bandit`), apt (`shellcheck`), the Go toolchain, pinned release binaries (`gosec`, `staticcheck`, `gitleaks`, `hadolint`), and the semgrep `p/default` ruleset vendored at build time so scanning works fully offline.

Both images can be built together with `docker compose build` (or `podman compose build`).

## Security & code-quality analysis (`run-quality.sh`)

`run-quality.sh` is the language-driven complement to `run-tools.sh`: it reads the inventory artifact for each repo (`artifacts/<repo>/scc/scc.json`, falling back to `tokei.json`), selects only the security/code-quality tools mapped to the languages actually present, and runs them in the `quality:latest` image. Output lands in `quality/<repo>/<tool>/` plus a per-tool `.exit` file carrying the tool's own exit code (findings, not container failures).

Selection config lives in `quality-tools.sh` (functions `always_tools`, `lang_tools`, `semgrep_include`, `tool_cmd`).

`run-quality.py` is an equivalent driver with the same CLI and behavior, written in Python for readability and without the `jq` dependency.

| Detected language (scc name → category) | Tools |
|---|---|
| Python | `ruff`, `bandit` |
| Go | `gosec`, `staticcheck` |
| Java / Rust / JS+TS / Kotlin / Ruby / PHP / C++ / Terraform | `semgrep` scoped to that language (`semgrep-<lang>`) |
| Shell / BASH | `shellcheck` |
| Dockerfile | `hadolint` |
| every repo | `gitleaks` (secrets) |

`Dockerfile`/`Shell`/`BASH` are detected by file count (even a single small file triggers the tool); other languages need ≥ `MIN_CODE` lines (default 50).

```bash
./run-quality.sh                     # default repos (must already have artifacts)
./run-quality.sh py-flask            # just one repo (clones it, uses artifacts/ for languages)
./run-quality.sh -f go-gin           # force re-run
MIN_CODE=20 ./run-quality.sh os-nova # lower language threshold
```

Run `./run-tools.sh <repo>` first if `artifacts/<repo>/scc/scc.json` doesn't exist.


## Current results (2026-08-02 run)

| Repo | LOC (tokei) | LLM token estimate | repomix pack size |
|---|---|---|---|
| go-gin / gin | 19,341 | 250.5k | 872 KB |
| go-mux | ~3k | — | 260 KB |
| java-gson | ~70k | — | 2.3 MB |
| java-springboot | ~4.0M | — | 41 MB |
| os-nova | ~700k | — | 27 MB |
| os-neutron | ~700k | — | 28 MB |
| glance | ~180k | — | 7.3 MB |
| py-flask | 25,703 | 444.0k | 4.1 MB |

Cross-tool notes: tokei and scc agree closely on code LOC; they diverge on YAML/Markdown because scc counts embedded code blocks. For huge repos (e.g. kubernetes) full packing is impractical — prefer `digest.txt` or scope to a subtree.
