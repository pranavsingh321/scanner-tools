All data gathered. Source files themselves aren't in the workspace (artifacts reference `/repo/` container paths), but the reports carry the needed file:line detail. Writing the report now.
Report written to `summary/multi.md`. Key findings:

- **Python-only scan** — Java toolchain skipped (no `.java` files, no PMD/Checkstyle/SpotBugs artifacts).
- **Code quality:** 1 ruff error (`I001 unsorted-imports`, `app/main.py:1-4`) — safe auto-fix available; nothing else.
- **Security:** 0 bandit findings; dependency-check **inconclusive** (offline-stub engine, NVD DB missing, 0 deps scanned). Overall risk **Low** with caveats.
- **Complexity:** avg cc 2.36, max 5, all rank A; worst functions `speak`/`compute` (cc=4). All files grade A maintainability.
- **Graph:** 2 packages, clean `app → pkg` edge (weight 6), no cycles; `pkg.models` isolated at module level; `Runner.run` is the single composition point.
heck could not run offline), high maintainability. Because of the size, most "structural" conclusions are about how the skeleton is wired rather than about defect density.

| Metric | Value | Source |
|---|---|---|
| Files | 3 (app/main.py, pkg/models.py, pkg/util.py) | scc / repomix / py-kg |
| LOC / SLOC | 24 / 21 (0 comments, 3 blank) | radon-raw, scc |
| Classes | 3 (Base, Dog, Runner) | py-kg |
| Methods / functions | 5 / 5 | py-kg |
| Packages (top-level) | 2 (`app`, `pkg`) | py-kg |
| External type references | 4 | py-kg |
| Dependency-check scope | 0 dependencies scanned — **inconclusive** (NVD DB missing offline) | depcheck |
| LLM pack size | 538 tokens, 2,843 chars, 3 files | repomix |

Not available in artifacts: radon-raw totals per project (only per-file), Mi rank is present (see Complexity). No Java/PMD/Checkstyle/SpotBugs data exists because none was generated.

## Code Quality

**Python (ruff): 1 violation, severity `error`.**
- `I001` / `unsorted-imports` — `app/main.py:1-4`. The import block is un-sorted/un-formatted; ruff provides a **safe auto-fix** (`import pkg.util as u` and `from pkg.models import Base, Dog`). This is the only lint finding in the repo; it is style-only, not logic.
- No `E`/`F` (pycodestyle/pyflakes) violations — code is otherwise syntactically clean.

**PMD / Checkstyle / CPD:** not run. No `.java` files and no `pmd/` or `checkstyle/` artifacts exist. Copy-paste duplication analysis was therefore not performed.

## Security

- **SpotBugs / FindSecBugs:** not run — Java toolchain skipped, no bytecode produced. State: *bytecode unavailable*.
- **Bandit (Python): 0 findings** across all 3 files (`results: []`; all severity/confidence counters zero). No `nosec` suppressions, no skipped tests.
- **OWASP dependency-check (CVEs): inconclusive.** The report (`dependency-check-report.json`, engine `offline-stub`) scanned **0 dependencies** and returned no CVEs. `depcheck.log` shows a fatal error: *"Autoupdate is disabled and the database does not exist."* With the NVD database unavailable offline, no vulnerability conclusion can be drawn — this is a data-availability failure, not a clean bill of health. The repo declares no third-party dependencies (scc/Python tooling found none to parse), so the practical exposure surface is near zero, but the scan itself must be re-run with a pre-seeded NVD DB (per the artifact's own warning: `docker build --build-arg PRESEED_NVD=1`) to be meaningful.
- **PMD security rules (injection / weak crypto):** not run (Java toolchain absent).

**Risk assessment: Low.** Justification: 21 SLOC with no external dependencies, no file/network/system access patterns flagged by bandit, no secrets tooling findings, and no dependency CVEs computable. Residual risk is limited to (a) dependency-check being blind offline and (b) the fact that 5 functions × 4-5 lines is too little surface to draw strong security confidence — the "Low" rating holds for current content but should be re-litigated if the project grows or adds dependencies.

## Complexity

Cyclomatic complexity (radon-cc, 11 blocks: classes + functions + methods):

| Metric | Value |
|---|---|
| Avg complexity (blocks) | 2.36 |
| Max complexity | 5 (class `pkg.models.Dog`) |
| Blocks with cc ≥ 10 | 0 |
| Overall project complexity (scc) | 7 |

Top functions by cc (all rank A):

| Function | cc | LOC | File |
|---|---|---|---|
| `Dog.speak` | 4 | 4 | pkg/models.py:6 |
| `util.compute` | 4 | 4 | pkg/util.py:1 |
| `Runner.run` | 1 | 4 | app/main.py:5 |
| `Base.greet` | 1 | 2 | pkg/models.py:2 |
| `util.helper` | 1 | 2 | pkg/util.py:6 |

Notes:
- Every block scores rank **A**; there is no hot spot. `speak`/`compute` at cc=4 are the highest, consistent with them being the only nodes that fan out (branches) — both are ~4 LOC, so density is high but absolute size trivial.
- Maintainability Index (radon-mi): `app/main.py` 100.0 (A), `pkg/util.py` 74.9 (A), `pkg/models.py` 69.5 (A) — all grade A.
- LOC per function is uniform (max 4); no unusually long methods/classes exist (`Dog` is the largest class at 5 LOC).
- CPD correlation: n/a (CPD not run). The one structural mirror is `speak` and `compute` sharing identical cc=4/LOC=4 shape — worth a glance when CPD tooling is enabled.

## Knowledge graph

Package/module graph (py-kg-extractor, stdlib AST; 3 files parsed, 0 parse failures):

- **Packages:** 2 — `app`, `pkg` (3 modules: `app.main`, `pkg.models`, `pkg.util`).
- **Edge totals:** CONTAINS 8, EXTENDS 2, CALLS 3, IMPORTS 3.
- **Hub modules:** `pkg.util` — deps 0, dependents 1 (a leaf utility); `app.main` — deps 1, dependents 0 (entry point).
- **Strongest package edge:** `app` → `pkg`, weight **6** (the only inter-package edge; 6 = 3 IMPORTS + CALLS/type references across both `models` and `util`).
- **Isolated modules:** `pkg.models` — no *module-level* import edges to/from it (imports in the graph attach at class level, e.g. `app.main` → `Dog`/`Base`; no other module imports `pkg.models`).
- **Dependency cycles:** none.

Architectural takeaways:
1. **Layering is clean and acyclic**: a single downstream direction (`app` → `pkg`) with no cycles — the kind of structure you want to preserve as it grows.
2. **`pkg.util` is a dependency-free leaf**: `compute`/`helper` depend on nothing, making it trivially testable and reusable; `app.main` sits atop it with zero dependents.
3. **`pkg.models` is only reached through intra-package type references** (via `app.main` → `Dog`/`Base`), suggesting its contract is consumed through classes rather than module imports — fine now, but worth a coherent public API if models grow.
4. **The only fan-out is `Runner.run`** (CALLS `Dog` and `compute`): it is the single composition point, so it will accumulate complexity first — the natural place to watch for cc growth and the likely target for dependency injection.
5. **Quantity of structure is minimal but consistent** — 1 EXTENDS chain (`Dog` → `Base`, `Runner` → `Base`) and 3 CALLS edges give a clear, small seam for introducing tests/interfaces.

## Recommendations

**Quick wins (minutes):**
1. Fix `I001 unsorted-imports` in `app/main.py:1-4` — apply ruff's safe auto-fix (sort `import pkg.util as u` before `from pkg.models import Base, Dog`). One `ruff check --fix` call.
2. Make dependency-check meaningful: re-run with the NVD DB pre-seeded (`docker build --build-arg PRESEED_NVD=1`) so the "0 dependencies / no CVEs" result isn't an artifact of an unavailable database. Until then, treat the security result as *unknown*, not *clean*.
3. Record tool versions for ruff/bandit/radon/radon/scc in the scan pipeline's metadata so future digests can compare severity drift (repomix v1.18.0 is the only version recorded).

**Structural work (discretionary — current size is trivial):**
4. Watch `Runner.run` (app/main.py:5) — it is the single composition point (calls `Dog.speak` and `util.compute`); if more logic lands, keep it delegating instead of branching to avoid the cc rising past the current flat profile.
5. Centralize `pkg.models` exposure: import `Base`/`Dog` through the package (e.g. keep `pkg.models` as the canonical place) so the model contract isn't reached only via class-level imports — cheap future-proofing and it removes the "isolated module" oddity.
6. Add a maintainability floor: all files are grade A today (MI 69.5–100); consider tracking radon-raw (currently only per-file, no per-project total in artifacts) so LOC growth is captured per release.