# production/ — scalable dispatcher → queue → workers → aggregator

Designed for fleets of thousands of repos. The queue is the filesystem under
`RUN_ROOT`:

```
RUN_ROOT/
  manifests/run-<ts>.txt          # dispatcher: chunk inventory per run
  jobs/{transit,internal}/        # pending chunks (one JSON per chunk)
  done/{transit,internal}/        # processed chunks (chunk.json + .result.json)
  logs/{transit,internal}/        # per-repo status lines (NDJSON)
  summaries/                      # aggregator output (.json + .md)
```

## Workflows

| File | Role | Schedule |
|---|---|---|
| `00-dispatcher.json` | Split the inventory into `CHUNK_SIZE`-sized chunk files, write a manifest | 02:00 + manual |
| `01-worker-transit.json` | Claim one transit chunk, run inventory + quality per repo, log status, mark done | every 2 min + manual |
| `02-worker-internal.json` | Same for the internal pipeline | every 2 min + manual |
| `03-aggregator.json` | Read latest manifest + logs → summary JSON/MD, optional Slack, purge old runs | 05:30 + manual |
| `04-retry.json` | Re-enqueue non-ok repos from the last `RETRY_WINDOW_HOURS` | every 10 min + manual |

## How a run flows

1. **Dispatcher** reads the repo list (Code node — see below), groups repos
   into chunks, writes `jobs/<pipeline>/<chunkId>.json`, and appends
   `manifests/run-<ts>.txt` with the chunk list. Each chunk file contains
   `{ chunkId, runId, pipeline, repos: [{name, url, target}] }`.
2. **A worker execution** (every 2 min) finds one pending chunk, atomically
   renames it to `*.processing.json` (so no other worker can take it), and for
   each repo:
   - transit: `transit-repo/run-tools.sh <name>:<url>` then
     `transit-repo/run-quality.sh <name>`
   - internal: `internal-repo/run-tools.sh <name>:<url|target>`
   
   Each repo appends one line to `logs/<pipeline>/<chunkId>.ndjson` with
   `{ ts, chunkId, runId, pipeline, repo, url, target, status, msg, exitCode }`.
   When the chunk finishes it is moved to `done/<pipeline>/`.
3. **Aggregator** counts done chunks, joins the log lines, writes
   `summaries/run-<ts>.json` (status = `complete`/`incomplete`, `failedRepos`,
   counts per pipeline), and purges runs older than `PURGE_AFTER_DAYS`.
4. **Retry** reads non-ok lines from the logs, and for each distinct failed
   repo (within the window) writes a single-repo chunk back into `jobs/` so the
   next worker pass retries it. Already-pending chunks are not duplicated.

## Why this scales

- **Work per execution is bounded**: one chunk, no matter how many repos total.
  Parallelism = number of overlapping worker executions.
- **Queue mode**: `compose.scale.yml` runs n8n in queue mode with `N` worker
  replicas; each worker polls on its own 2-minute schedule, so effectively you
  get `WORKER_REPLICAS` concurrent lanes. Scale with
  `docker compose up -d --scale n8n-worker=N`.
- **Crash safe**: chunks are plain files; a killed worker leaves a
  `.processing.json` that is reclaimed by the next poll after `STALE_MIN`.
- **Idempotent**: retry skips files that already exist; re-dispatches overwrite
  the same chunk ids; the analyzer scripts themselves skip repos with existing
  output, so replays are cheap.

## Repo inventory (dispatcher)

The dispatcher's **Build Repo List** node returns
`[{ name, url, target?, pipelines: ['transit','internal'] }]`. Replace its
contents with any source you like — static JSON, a CSV in a Code node, or an
HTTP request to your internal inventory service. `run-tools.sh` accepts
`name:url` or `name:target` per the existing pipeline contract.

## Production stack (Docker)

```bash
cp .env.example .env   # edit MULTITOOL_ROOT, RUN_ROOT, DB creds
docker compose -f compose.scale.yml up -d --build
docker compose -f compose.scale.yml up -d --scale n8n-worker=8
```

The worker image adds `bash git curl jq python3 docker-cli` to the stock n8n
image and mounts the host docker socket, so Execute Command can `docker run`
the analyzer images. The socket mount is the same Dockerfile pattern n8n
itself documents; keep the socket on a trusted host.

> Note on scaling intent: n8n queue mode with scheduled executions does not
> give you sub-minute scheduling granularity, and each execution is one chunk.
> If you need higher throughput than ~1 chunk per scheduler tick per worker,
> run the worker workflows on shorter intervals or add replicas.

## Known limitations / notes

- **Execute Command is disabled by default** on n8n ≥ 2.0 and unavailable on
  n8n Cloud. This folder assumes a self-hosted instance with
  `NODE_FUNCTION_ALLOW_BUILTIN=*` (or at least `executeCommand`) set.
- The Slack node in `03-aggregator.json` uses a credential placeholder; wire
  yours or delete the node.
- Schedules are starting points; change the cron expressions to fit your fleet
  size and drain time.
