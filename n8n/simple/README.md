# simple/ — two workflows for small fleets

Minimal, readable versions of the pipelines for small repo lists. Each workflow
handles one pipeline; the repo list is a hardcoded JSON array in a Code node.
For thousands of repos use `../production`.

## transit-pipeline.json

For every repo in the list, runs in order:

1. `transit-repo/run-tools.sh <name>:<url>` (inventory scan)
2. `transit-repo/run-quality.sh <name>` (quality report)

then lists what it produced (`transit-repo/output/<name>.md` and
`quality/<name>/…`) and returns a summary array.

## internal-pipeline.json

For every target in the list, runs:

1. `internal-repo/run-tools.sh <name>:<url>` or `internal-repo/run-tools.sh <name>:<ip>`

then lists outputs under `internal-repo/output/<name>/` and returns a summary.

## Editing the repo list

Open the **Repo List** node. It returns `[{ name, url, target?, pipeline }]`:

- `transit` → transit-pipeline.json (uses `url`)
- `internal` → internal-pipeline.json (uses `url` or `target`)

## Running

- **Manual Trigger** → run once.
- Optional **Nightly Schedule** (commented-out cron `0 2 * * *`): activate it
  if you want the run automated.

Each iteration executes sequentially (one repo at a time). To run repos in
parallel, duplicate the workflow and split the list, or move to `../production`.
