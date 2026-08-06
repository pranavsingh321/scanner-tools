# langgraph-pipeline

Fully-automated multi-stage repository analysis, orchestrated by [LangGraph](https://langchain-ai.github.io/langgraph/).
Each stage is a graph node; an AI agent remediates findings and, when the post-fix
verification passes, auto-merges the fix into a fork of the analyzed repo.

The existing shell/Python runners (`transit-repo/`, `internal-repo/`) are left
untouched — this pipeline drives the *same* container images.

## Graphs

> Data flow and per-stage criteria: see [DESIGN.md](DESIGN.md).

### Phase 1 — `transit_graph` (inventory + quality)

```
START → ensure_images → ingest → inventory_scan → detect_languages
     → quality_scan → llm_summarize → remediate
remediate ─loop─→ verify_scan ─(findings remain, rounds<MAX_FIX_ROUNDS)─→ remediate
verify_scan ─(gate PASS)─→ merge_pr → finalize → END
           └─(gate FAIL)─→ leave_open → finalize
```

### Phase 2 — `internal_graph` (security)

Same shape with a `security_scan` stage (SBOM/SCA/secrets/SAST/malware) plus an
optional `target_scan` stage for network targets (nuclei/naabu/httpx).

## Setup

```bash
cd langgraph-pipeline
uv venv && uv pip install -e .
```

Requirements: `podman` or `docker` with a running daemon, `gh` CLI (authenticated)
for the fork/PR/merge flow, and an OpenAI-compatible endpoint:

```bash
export OPENAI_API_KEY=...            # required
export OPENAI_BASE_URL=https://...   # optional; point at Ollama/vLLM/OpenRouter
export LLM_MODEL=gpt-4o-mini         # optional
```

## Usage

```bash
uv run python transit_graph.py                        # 3 default repos
uv run python transit_graph.py os-nova                # one repo
uv run python transit_graph.py myname:https://github.com/user/repo
uv run python transit_graph.py /path/to/local/repo    # local dir (no fork/PR)
uv run python internal_graph.py                       # security pipeline
```

### Options
| Flag | Meaning |
|---|---|
| `-o/--out DIR` | artifacts output directory (default `<graph-dir>/artifacts`) |
| `-r/--rebuild` | force rebuild of the container image |
| `-R/--runtime X` | container runtime: `podman` \| `docker` (auto-detect) |
| `-k/--keep` | keep temp clones of remote repos |
| `-f/--force` | re-run tools even if an output file already exists |
| `--no-remediate` | scan + summarize only (no fixes, no PRs) |
| `--no-merge` | open the PR but never merge it |

### Environment
| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | — | required for the LLM stages |
| `OPENAI_BASE_URL` | — | override for OpenAI-compatible endpoints |
| `LLM_MODEL` | `gpt-4o-mini` | chat model name |
| `RUNTIME` | auto | `podman` \| `docker` |
| `IMAGE` | graph-specific | container image tag |
| `MIN_CODE` | `50` | min code lines for a language to trigger quality tools |
| `REMEDIATE` | `1` | run the remediation agent |
| `AUTO_FORK` | `1` | fork the analyzed repo before pushing a fix branch |
| `AUTO_MERGE` | `1` | enable auto-merge on the PR |
| `MERGE_METHOD` | `squash` | `squash` \| `merge` \| `rebase` |
| `MAX_FIX_ROUNDS` | `2` | remediation/verify loop cap |
| `GITHUB_ACTOR` | `gh api user` | account owning the forks |

## Full-automation GitHub flow

1. `gh repo fork <owner>/<repo>` creates a fork under the authed account.
2. The remediation agent edits a writable clone, re-runs the affected tools (verify).
3. Branch `llm-fix/<repo>-<ts>` pushed to the fork; a **self-PR** is opened against the
   fork's default branch (upstream is never touched).
4. If verification passed: `gh repo edit --enable-auto-merge` + `gh pr merge --squash --auto`.
5. If verification failed: a comment lists the failing checks and the PR stays open.

## Graph internals

`pipeline/`
| Module | Role |
|---|---|
| `config.py` | runtime/image/dirs, repo parsing, env |
| `state.py` | TypedDict state + `RepoEntry`, `RepoResult` |
| `containers.py` | image build + container dispatch |
| `repos.py` | resolve + shallow-clone (writable) |
| `detect_languages.py` | tokei → language categories → tool selection |
| `findings.py` | tool artifacts → structured findings |
| `llm.py` | OpenAI-compatible chat client + prompts |
| `summarize.py` | artifacts + findings → `summary/<name>.md` |
| `agent_tools.py` | tools exposed to the remediation agent |
| `remediate.py` | prebuilt ReAct agent + git/gh flow |
