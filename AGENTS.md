# AGENTS.md — scanner-tools

Offline static-analysis pipeline (PMD, Checkstyle, SpotBugs+FindSecBugs, OWASP depcheck, scc, repomix + Python ruff/bandit/radon). Everything runs inside a single Docker image — no host tooling needed at scan time.

## Build & run

```bash
# First run auto-builds the image; takes several minutes.
./run-tools.sh /path/to/repo

# Rebuild image explicitly (e.g. after Dockerfile changes):
./run-tools.sh -r /path/to/repo

# Python-only scan:
./run-tools.sh --lang python /path/to/repo

# Both language sets against a mixed repo:
./run-tools.sh --lang all /path/to/mixed/repo

# Generate LLM summary (requires `opencode` + a model):
./agent-summarize.sh <repo-name>           # e.g. java-gson
./agent-summarize.sh -m anthropic/claude-sonnet-4 <repo-name>
```

Container runtime auto-detects podman vs docker. Override with `-R docker` or `-R podman`.

## Key gotchas

- **Tool exit codes are non-zero by design.** Static analyzers exit non-zero when they find violations. The scripts tolerate this (`|| true`). Do not treat a non-zero exit from a tool as a script failure — only a missing output file is a real failure.
- **SpotBugs needs bytecode.** It scans `*.class`/`*.jar` files. If the repo has no compiled output, it emits a stub report saying "no bytecode found." This is expected for source-only repos.
- **depcheck offline** uses a bundled NVD snapshot (only if built with `--build-arg PRESEED_NVD=1`). Without it, a stub JSON report is generated noting NVD is unavailable.
- **`-f` / `--force`** re-runs tools even if output files already exist. Without it, existing outputs are skipped.
- **`-k` / `--keep`** preserves temp clones of remote repos in `.multi-work/`. Without it, they are cleaned up on exit.
- **`agent-summarize.sh`** runs `opencode run` (non-interactive). It auto-rejects permission prompts, so run it from this repo where `artifacts/` is accessible. Set `OPENCODE_MODEL` env var or pass `-m` to avoid interactive model selection.

## Output layout

- `artifacts/<repo>/<tool>/` — raw XML/JSON per analyzer
- `summary/<repo>.md` — LLM-generated markdown report
- `summary/_digests/<repo>.md` — machine-extracted totals (grep/awk, no host deps)

## Architecture

1. `run-tools.sh` iterates repos → for each repo, runs one `docker run --rm` per tool, mounting the repo read-only and the output dir read-write.
2. `agent-summarize.sh` builds a grep/awk digest from artifacts, then pipes an analyst prompt + digest into `opencode run` which reads the raw XML/JSON and writes `summary/<repo>.md`.
3. The Dockerfile is multi-stage: scc build → tool downloads → final image with everything bundled.

## Cross-arch image builds

`docker-compose.yml` wraps multi-arch builds; `PLATFORM`/`TARGETARCH` default to `linux/arm64`. The host is x86_64 (dependency-check, PMD, scc all compile cleanly under buildx/QEMU), so for amd/arm images use buildx:

```bash
docker buildx build --platform linux/amd64 --load -t analyzers-java:latest-amd64 .
docker buildx build --platform linux/arm64 --load -t analyzers-java:latest-arm64 .
docker save analyzers-java:latest-amd64 | gzip > analyzers-java-amd64.tar.gz
docker save analyzers-java:latest-arm64 | gzip > analyzers-java-arm64.tar.gz
```

On a bare x86 host, arm64 builds need QEMU emulation (`docker run --privileged --rm tonistiigi/binfmt --install arm64`).
