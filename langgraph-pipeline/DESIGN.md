# Pipeline design — data flow, gates, and criteria

How the LangGraph multistage pipeline moves data between stages and which
criteria decide whether a stage runs, loops, or bails. Two graphs share one
state model; only the middle stages differ.

## Shared state

`PipelineState` (see `pipeline/state.py`) — a `TypedDict` threaded through
every node. Nodes mutate it and return the updated slices.

| Field | Type | What it carries |
|---|---|---|
| `cfg` | `RunConfig` | runtime, images, dirs, `min_code`, `force`, `remediate`, `no_merge` |
| `entries` | `list[RepoEntry]` | input repos/targets (`name`, `url`, `localdir`, `target`) |
| `results` | `dict[str, RepoResult]` | per-repo state: `repo_dir`, `languages`, `tools`, `quality_tools`, `remediation`, `round`, `remaining_total`, `can_merge`, `error` |
| `errors` | `list[str]` | collected failures (ingest, scan, LLM, PR) |
| `summaries` | `dict[str, str]` | repo → summary file path |

`RepoResult` is the unit of work. Each repo moves through the graph carrying
`repo_dir` (its **writable** checkout) plus accumulated tool results.

## Phase 1 — `transit_graph` (inventory + quality)

```
START
 │
 ▼
ensure_images ──────────► ingest ──────────► inventory_scan ──────────► detect_languages
 (build images,           (clone/resolve)     (tokei scc repomix          (pick quality tools
  retry once on             to work_dir/)      gitingest files-to-prompt    by language)
  failure + build log)                         every tool goes through
                                              the [debug/retry loop] ◄────┐
                                                       │                   │
                                                       ▼                   │
                                              quality_scan ────────────────┘
                                              (ruff bandit gosec staticcheck
                                               semgrep-* shellcheck hadolint gitleaks)
                                                       │
                                                       ▼
                                              llm_summarize  ───►  remediate ──┐
                                              (LLM writes                     │ (agent edits
                                               summary/<name>.md)              │  working tree;
                                                       ▲                        │  later rounds get
                                                       │                        │  verify logs)
                                                       │                        ▼
                                                       │                 verify_scan (re-run tools)
                                                       │                        │
                                                       │         ┌──────────────┼──────────────┐
                                                       │         ▼              ▼              ▼
                                                       │    (loop)        (settled)      (gate FAIL)
                                                       │         │              │              │
                                                       │         └──► remediate   ▼              │
                                                       │                     refactor           │
                                                       │                     (single-           │
                                                       │                      responsibility)   │
                                                       │                        │                │
                                                       │                        ▼                │
                                                       │                 verify_refactor        │
                                                       │                 (re-run tools)          │
                                                       │                   (loop back if         │
                                                       │                    regression)          │
                                                       │                        │                │
                                                       │         ┌──────────────┼────────────────┤
                                                       │         ▼              ▼                ▼
                                                       │   (gate PASS)    (gate FAIL)      (no edits)
                                                       │         │              │                │
                                                       │         ▼              ▼                ▼
                                                       │   merge_pr        leave_open        finalize
                                                       │   (auto-merge)    (PR stays open)
                                                       │         └──────┬──────┘
                                                       │                ▼
                                                       │           finalize
                                                       └─────────────── END
```

## Phase 2 — `internal_graph` (security)

Identical skeleton; `security_scan` (trivy, gitleaks, opengrep, clamav)
replaces inventory+quality, and an optional `target_scan` (nuclei/naabu/httpx)
runs only when an entry is a network target. One tool per category to avoid
duplicate/equivalent scanners: trivy = vuln+secret+misconfig+SBOM (replaces
osv-scanner/syft), gitleaks = secrets (replaces trufflehog/ggshield),
opengrep = SAST (replaces codeql), clamav = malware (unique). Targets have no
working tree, so they skip remediate/verify/PR entirely.

```
START → ensure_images → ingest → security_scan ──(any target?)──► target_scan ──┐
                                          │                                        │
                                          └────────────► llm_summarize ◄───────────┘
                                                          │
                                                          ▼
                                        remediate ⇄ verify_scan → merge_pr | leave_open → finalize → END
```

## Stage-by-stage data flow & criteria

### 1. ensure_images
- **Input:** `cfg` (runtime, image list, rebuild flag).
- **Action:** build image(s) if absent (or when `-r/--rebuild`): transit builds
  `analyzers:latest` + `quality:latest`; internal builds `internal-analyzers:latest`.
- **Criterion:** skip build when `runtime image exists` is true and no `-r`.
- **Output:** images available; state unchanged.

### 2. ingest
- **Input:** `entries`.
- **Action:** local dirs used as-is; remote URLs shallow-cloned
  (`git clone --depth 1`) into `work_dir/<name>` — **writable**, because the
  remediation stage edits it. Network targets get a `RepoResult` with no `repo_dir`.
- **Fail criterion:** clone/`resolve_repo` raises → `RepoResult.error` set,
  error appended to `errors`; repo is carried forward but skipped by scan stages.
- **Output:** `results[name].repo_dir` populated.

### 3. inventory_scan (transit) / security_scan (internal)
- **Input:** `results` (each repo's `repo_dir`).
- **Action:** for each tool, `podman|docker run --rm -v repo:/repo:ro -v out:/out <image>`
  → raw output under `artifacts/<name>/<tool>/`.
- **Skip criterion:** `-f/--force` off AND the tool's primary output already
  exists (`tokei.json`, `repomix.txt`, `trivy.json`, `gitleaks.json`, …).
- **Tool criterion (internal):** none — every tool is unguarded, so no per-tool
  env var or probe is needed (removed the old ggshield/codeql special cases).
- **Output:** `results[name].tools[tool]` = `ToolResult(status, out_dir, exit_code)`.

### 4. detect_languages (transit only)
- **Input:** `artifacts/<name>/tokei/tokei.json`.
- **Criteria:** a language qualifies if `code >= MIN_CODE` (default 50); but
  Dockerfile/Shell/BASH qualify by **file count ≥ 1**. Language name → category
  via `normalize_lang` (`Python→python`, `Go→go`, `C++→c`, …).
- **Action:** `select_tools` = always-run `gitleaks` + per-category tools
  (python→ruff+bandit, go→gosec+staticcheck, others→`semgrep-<lang>`,
  shell→shellcheck, dockerfile→hadolint).
- **Fail criterion:** no `tokei.json` → `RepoResult.error`
  "no inventory artifacts"; repo routes to finalize.
- **Output:** `results[name].languages`, `results[name].quality_tools`.

### 5. quality_scan (transit)
- **Input:** `results[name].quality_tools` + `quality:latest`.
- **Action:** run each selected tool → `quality/<name>/<tool>/`; tool writes its
  own exit code to `/out/.exit` so "findings" (rc≠0) ≠ container failure.
- **Skip criterion:** `-f` off AND `quality/<name>/<tool>/.exit` exists.
- **Output:** `results[name].tools[tool]` with `exit_code` and status
  `ok | findings | skipped | failed`.

### 5b. Debug / retry loop (runs inside every scan stage)
Because the scan scripts end with `; true`, the container exits 0 even when a
tool failed. Every tool result therefore passes through `findings.looks_failed()`
which validates the **primary output** (present, non-empty, parses, has the right
JSON section) and scans `*.log` for error markers.
- **When bad:** `debug.diagnose_and_retry` runs the loop —
  1. gather the tool command + its logs;
  2. if an LLM is configured, ask it to propose a corrected `sh -c` command
     (e.g. `trivy sbom` fallback when `trivy fs` chokes on a registry 429);
     otherwise apply a built-in mechanical retry table;
  3. re-run the corrected command, clear the stale output, re-validate.
- **Loop bound:** `MAX_DEBUG_ATTEMPTS = 2`; after that the tool is marked
  `failed` with the reason recorded in `RepoResult.error`.
- **Known mechanical fallbacks:** `trivy` → skip `vendor` dirs.

### 6. llm_summarize
- **Input:** the repo's artifact dirs + `findings.py` parsed structure.
- **Action:** OpenAI-compatible model (`LLM_MODEL`, `OPENAI_BASE_URL`) writes
  `summary/<name>.md` from a metrics table + top findings per tool.
- **Skip/soft-fail criterion:** repo with an ingest error → placeholder summary;
  LLM exception → error logged, graph continues.
- **No-LLM fallback:** when no endpoint is configured, a mechanical
  metrics + findings report is written instead.
- **Output:** `results[name].summary_path`, `summaries[name]`.

### 7. remediate
- **Input:** parsed findings from the tools that ran; the **writable** checkout.
- **Action:** a LangGraph ReAct agent (`create_react_agent`) gets the findings,
  reads files, applies unified diffs (`apply_patch`), and re-checks with
  `verify_tool`. It never commits/pushes — the graph owns git.
- **Later rounds (log feedback):** on round ≥ 2 the agent is re-seeded with the
  **remaining** findings (re-parsed from the last verify run) plus the failing
  verify logs, so it can diagnose why a fix did not take.
- **Criterion to run:** `cfg.remediate` AND the repo has a `repo_dir` AND
  `remaining_total > 0` AND `round < MAX_FIX_ROUNDS` (default 2).
- **Output:** `results[name].round += 1`; `remediation["agent"]` = agent message.

### 8. verify_scan (the gate)
- **Input:** the edited working tree + the tools that had findings.
- **Action:** re-run each affected tool into `work_dir/.verify/<name>/<tool>/`
  and count remaining findings.
- **Gate criterion (merge decision):** `can_merge = (remaining_total == 0)`
  — all affected tools must report **zero** findings after the fix.
- **Output:** `remaining_total`, `remediation["remaining"]`, `can_merge`.

### 9. routing after verify_scan (conditional edge)
| Route | Criterion |
|---|---|
| `loop → remediate` | any repo has `remaining_total > 0` and `round < MAX_FIX_ROUNDS` |
| `refactor → refactor` | remediation settled AND `cfg.remediate` AND an LLM is configured |
| `merge → merge_pr` | no loop; any repo `can_merge` with non-empty `git diff` |
| `leave → leave_open` | no loop; edits exist but gate failed |
| `none → finalize` | no repo edited at all |

### 9b. refactor (single responsibility)
- **Criterion to run:** `cfg.remediate` AND LLM configured AND repo's
  remediation gate passed (`remaining_total == 0`) AND `refactor_round < 2`.
- **Action:** a ReAct agent audits the code for units that mix multiple
  responsibilities (god functions/classes, helpers in the wrong module,
  duplicated logic) and applies behavior-preserving refactors with the same
  toolset (`read_file`, `list_files`, `apply_patch`, `repo_status`,
  `verify_tool`). Public API changes must update every call site in the change.
- **Detect no-ops:** `git diff` hash is snapshotted before/after; unchanged →
  `refactor_changed = False`.
- **Output:** `refactor_round += 1`, `remediation["refactor_agent"]`.

### 9c. verify_refactor
- **Action:** re-run the full quality/security tool set on the refactored tree
  into `work_dir/.verify/<name>/<tool>/`; recompute `remaining_total` from the
  **post-refactor** state.
- **Gate:** `can_merge = (total == 0)`. A regression (new findings) loops back
  to `refactor` (bounded by `MAX_REFACTOR_ROUNDS`), otherwise the same
  `merge | leave | none` routing applies.

### 10. merge_pr / leave_open (GitHub automation)
- **Action (both):** `ensure_fork` (fork `owner/repo` under the authed gh
  account), branch `llm-fix/<name>-<ts>`, commit **all** changes (remediation +
  refactor, via `git add -A`), push to fork, open a **self-PR** against the
  fork's default branch (upstream untouched).
- **merge_pr adds (gate passed):**
  1. `gh repo edit <fork> --enable-auto-merge --delete-branch-on-merge`
  2. `gh pr merge <url> --auto --squash --delete-branch` → merges itself when
     checks pass.
- **leave_open adds (gate failed):** `gh pr comment` listing that verification
  did not pass; PR is **never** merged.
- **Abort criteria:** no upstream URL (local dir) or no `gh` → `skipped`;
  `--no-merge` forces the leave-open path for every repo.

### 11. finalize
- Clean `work_dir` unless `-k/--keep`; print a per-repo status table
  (`ok | <error> | remediation: <status>`); print collected errors; `END`.

## Fix classification (agent gating)

`findings.py` tags every finding with a category used by the agent prompt:

| Category | Tools | Agent behavior |
|---|---|---|
| `auto` | gitleaks, ruff, bandit, gosec, staticcheck, semgrep-*, opengrep, shellcheck, hadolint, **trivy** | edits code / bumps deps, verifies; merged if gate passes |
| `suggest` | clamav | report only; no edits, never merged |

The `verify_scan` gate is the single source of truth for whether a fix is
safe to merge — the LLM can propose, but only a zero-findings re-run merges.

## Environment knobs

| Variable | Default | Effect |
|---|---|---|
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL` | — / — / `gpt-4o-mini` | LLM stages |
| `RUNTIME` | auto | `podman` \| `docker` |
| `MIN_CODE` | `50` | language activation threshold |
| `REMEDIATE` | `1` | run the remediation agent |
| `AUTO_MERGE` | `1` | enable auto-merge on PR |
| `MERGE_METHOD` | `squash` | `squash` \| `merge` \| `rebase` |
| `MAX_FIX_ROUNDS` | `2` | remediation→verify loop cap |

CLI: `-o/--out`, `-r/--rebuild`, `-R/--runtime`, `-k/--keep`, `-f/--force`,
`--no-remediate`, `--no-merge`.
