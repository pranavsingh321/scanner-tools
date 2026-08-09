# n8n workflows for the multi-tool repo pipelines

Orchestrates the existing `transit-repo` and `internal-repo` analyzer scripts
through n8n. All pipeline work happens in **Execute Command** nodes that call
the same bash scripts the pipelines already use, so n8n is a scheduler +
orchestrator and nothing in this folder re-implements a pipeline.

There are two layouts:

| Folder | Purpose | Scale |
|---|---|---|
| `simple/` | Two small workflows (one per pipeline) that loop over repos inline | Fine for a handful of repos, first runs, debugging |
| `production/` | Dispatcher + file-queue + N workers + aggregator + retry | Thousands of repos, unattended nightly |

## Requirements

- n8n self-hosted (or the included Docker image). The **Execute Command**
  node must be enabled — it is blocked by default on n8n ≥ 2.0 and is **not
  available on n8n Cloud**. Enable it by setting
  `NODE_FUNCTION_ALLOW_BUILTIN=*` (or the finer-grained
  `NODE_FUNCTION_ALLOW_LIST` with `executeCommand`) in the instance env and
  restarting.
- `docker` (or `podman` with `docker` aliased) reachable from the n8n host,
  with the analyzer images buildable:
  - `transit-repo/Dockerfile` → inventory,
  - `transit-repo/quality.Dockerfile` → quality,
  - `internal-repo/Dockerfile` → internal.
- The checkout at `MULTITOOL_ROOT` (default `/opt/multi-tool`). Artifacts are
  written inside the checkout (`transit-repo/output/`, `internal-repo/output/`),
  so it must be writable by the n8n process.

## Shared env vars

Set these on the n8n instance; every workflow reads them with `{{ $env.* }}`.

| Var | Default | Used by |
|---|---|---|
| `MULTITOOL_ROOT` | `/opt/multi-tool` | all (path to scripts) |
| `RUN_ROOT` | `$MULTITOOL_ROOT/n8n/runs` | production (file queue) |
| `CHUNK_SIZE` | `50` | production dispatcher |
| `STALE_MIN` | `15` | production workers |
| `RETRY_WINDOW_HOURS` | `24` | production retry |
| `RETRY_MAX` | `200` | production retry |
| `PURGE_AFTER_DAYS` | `14` | production aggregator |

## Importing

1. In n8n: **Workflows → Import from File** and pick the `.json` files.
2. The workflows are checked in with `active: false` and a `n8n` placeholder
   for credentials (Slack). Open each one, wire credentials, **Save**, then
   activate schedules (dispatcher 02:00, workers every 2 min, aggregator 05:30,
   retry every 10 min — all editable in the workflow).

See `production/README.md` for deployment of the scalable stack.
