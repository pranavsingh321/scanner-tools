# LangGraph Crash Course (practical)

A dense, example-first tour of LangGraph, written against a real codebase:
this repo's `transit_graph.py` / `internal_graph.py` (a multi-stage analysis
pipeline: scan -> summarize -> agent-remediate -> verify -> refactor -> auto-PR).
Installation and model-setup are skipped; the focus is on the patterns you
actually reach for.

The running example graph:

```
ensure_images → ingest → inventory_scan → quality_scan → llm_summarize
     → remediate ⇄ verify_scan (loop) → refactor ⇄ verify_refactor (loop)
     → merge_pr | leave_open → finalize
```

## 0. Mental model

LangGraph is a **state machine with a shared state dictionary**. Three concepts:

1. **State** — a `TypedDict` (or dataclass) describing what is carried between
   nodes. It is the only contract between nodes.
2. **Nodes** — plain Python functions `(state) -> partial state dict`. Each node
   reads state, does work, and returns a **dict of the keys it wants to update**.
3. **Edges** — transitions. A plain edge says "always go A -> B". A
   **conditional edge** says "go to B, C, or back to A, depending on the state".

You build a `StateGraph`, add nodes and edges, then `compile()` it into an
executable `CompiledGraph`. Invoking it is `graph.invoke(input)`.

```
flowchart:  node(node fn) --edge--> node2 --conditional--> {A, B}
state:      {key: value} flows along the edges, mutated by node returns
```

## 1. Minimal graph

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class State(TypedDict):
    question: str
    answer: str = ""

def answer_node(state: State) -> dict:
    return {"answer": f"you asked: {state['question']}"}   # return ONLY what changed

g = StateGraph(State)
g.add_node("answer", answer_node)
g.add_edge(START, "answer")
g.add_edge("answer", END)
app = g.compile()
print(app.invoke({"question": "hi"}))   # {'question': 'hi', 'answer': 'you asked: hi'}
```

That's the whole core. Everything else is making nodes/edges smarter.

## 2. State: the contract (and reducers)

Two state schemas exist: `TypedDict` (functional, immutable-ish updates) and a
`StateGraph` subclass with `Annotated` fields (reducers — see §3.1 in docs).
The TypedDict style is what this repo uses (`pipeline/state.py`).

Key rule: **every key a node returns must already exist in the state schema**,
or LangGraph raises at compile time (`ChannelUpdate` errors). Add all keys up
front, even with empty defaults:

```python
class PipelineState(TypedDict):
    cfg: RunConfig
    entries: list[RepoEntry]
    results: dict[str, RepoResult]     # per-repo result, built up across nodes
    errors: list[str]                  # accumulated diagnostics
    summaries: dict[str, str]
```

A node mutates one repo's result *in place* inside the dict, then returns the
whole `{"results": results}` so the new dict is written back:

```python
def node_ingest(state: PipelineState) -> dict:
    results = state.get("results", {})
    for entry in state["entries"]:
        results[entry.name] = RepoResult(name=entry.name)   # mutate the inner object
    return {"results": results}                              # return the key we changed
```

### When to use a reducer

If two nodes run in **parallel** and both return the same key, the last write
wins by default and you lose data. Use a reducer to merge instead:

```python
from typing import Annotated, TypedDict
from operator import add

class State(TypedDict):
    log: Annotated[list[str], add]      # += each node's list into one big list
```

`add` is the reducer for lists/numbers. Custom reducers are just functions —
e.g. a de-duplicating merge for parallel nodes that may return overlapping items:

```python
def uniq_merge(a: list[str], b: list[str]) -> list[str]:
    return sorted(set(a) | set(b))

class State(TypedDict):
    seen: Annotated[list[str], uniq_merge]
```

## 3. Nodes: pure update functions

Nodes receive the full state and return a partial update dict. Two common bugs:

- Returning **more than you changed** is fine (it just overwrites), but
- Returning **nothing changed** (`return {}`) is also fine — LangGraph treats it
  as "no update" and continues. This repo's guard nodes do exactly that:

```python
def node_refactor(state: PipelineState) -> dict:
    if not cfg.remediate or not llm_configured():
        return {}                       # nothing to do, keep the graph moving
    ...
    return {"results": results}
```

Prefer this "no-op by returning empty dict" style over drawing conditional
edges everywhere — it keeps the graph topology simple and pushes decisions
into the nodes where they're easy to unit test.

## 4. Edges and routing (conditional edges)

A conditional edge is the LangGraph way to make a *decision* based on state.
The function receives state and returns the name of the node to go to (or a
list of names, for fan-out). It **must** return one of the names in the
`path_map`.

```python
g.add_conditional_edges(
    "verify_scan",                 # node whose output triggers the decision
    after_verify,                  # (state) -> str  |  e.g. "loop" | "refactor" | "merge"
    {"loop": "remediate",          # path_map: allowed return values -> targets
     "refactor": "refactor",
     "merge": "merge_pr",
     "leave": "leave_open",
     "none": "finalize"},
)
```

Real decision function from `transit_graph.py:247` — note the **priority
ordering** (loops beat refactor, refactor beats merge):

```python
def after_verify(state: PipelineState) -> str:
    for entry in state["entries"]:
        result = state["results"].get(entry.name)
        if result and result.remaining_total and result.round < MAX_ROUNDS:
            return "loop"                     # more fixes needed -> go back
    if state["cfg"].remediate and llm_configured():
        return "refactor"                     # fixes settled -> refactor next
    return _route_after_automation(state)     # else final merge/leave/none
```

Gotchas:
- The return value that isn't in `path_map` → `InvalidUpdateError` at runtime.
- Every possible branch must be reachable — you cannot "not return". If a path
  leads nowhere, point it at `finalize` (a node) or `END`.
- Routing on the *last* write wins; there is no join logic unless you write it.

## 5. Returning control from inside a node: `Command`

Conditional edges decide *between* nodes. Sometimes the decision is **inside**
the node, right where the data is. `Command` lets a node update state **and**
pick its own next node in one return value — no router function needed:

```python
from langgraph.types import Command

def node(state: State) -> Command:
    ...
    if state["remaining"] == 0:
        return Command(update={"status": "clean"}, goto="merge_pr")
    return Command(update={"status": "dirty"}, goto="remediate")
```

`Command` also powers interrupts from *inside* agents and lets you inject state
on resume. The two forms are equivalent in outcome; prefer `Command` when the
next step is obvious from the node's own result (one node, one fan-in), and
prefer a conditional edge when several nodes need to route through the same
decision logic (N → M routing).

The most common bug: mixing the two. If a node returns `Command(goto=...)`,
the edge you also drew from that node is ignored. Pick one style per node.

## 6. Loops (cycles) — the part that's really different

LangGraph's killer feature: **a graph can cycle**. `remediate -> verify_scan ->
(remediate | next)` is a genuine loop, not a while-loop in a node. This is how
you build "do X, check Y, retry until Z" pipelines declaratively.

Rules you must add yourself:
- **A cycle needs a stop condition** or it runs forever. Track a `round` counter
  in state and break when exhausted. The counter increments *inside the node*,
  and the router reads it:

```python
def repair(state: State) -> dict:
    ...
    return {"fixed": [...], "round": state["round"] + 1}   # bump the counter

def after_verify(state: State) -> str:
    if state["flagged"] and state["round"] < MAX_ROUNDS:   # read it here
        return "repair"
    return "done"
```

- **A cycle never terminates at runtime** — it just keeps flowing back through
  the same node. LangGraph runs nodes until you hit `END`, so make sure every
  path eventually reaches an edge to `END`.

Bounded retry loop sketch (this repo's `remediate ⇄ verify_scan`):

```python
g.add_node("remediate", node_remediate)
g.add_node("verify_scan", node_verify_scan)
g.add_edge("remediate", "verify_scan")
g.add_conditional_edges("verify_scan", after_verify, {
    "loop": "remediate",      # findings remain AND round < MAX -> go back
    "merge": "merge_pr",      # zero findings -> PR
    "leave": "leave_open",
    "none": "finalize",
})
```

## 7. Agents: `create_react_agent` + tools

ReAct agent = LLM + tools + a loop. LangGraph ships a prebuilt agent:
`create_react_agent(model, tools)` returns a **compiled graph**. It is exactly
the right tool when a node needs open-ended work (read files, edit code, run a
check). This repo's remediation stage is a node whose body is a ReAct agent
(see `pipeline/remediate.py`, `pipeline/refactor.py`):

```python
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

model = ChatOpenAI(model="gpt-4o-mini")   # base_url -> any OpenAI-compatible endpoint

agent = create_react_agent(
    model,
    tools=[read_file, apply_patch, verify_tool, repo_status],  # @tool functions
)

result = agent.invoke({
    "messages": [
        ("system", agent_system_prompt),          # task framing + constraints
        ("user", findings_text),                  # the findings to fix
    ]
})
message = result["messages"][-1]
```

The tools are plain functions decorated with `@tool` from
`langchain_core.tools` — the agent decides when to call them, in a loop, until
it produces a final answer. This gives you an **autonomous node inside a bigger
state machine**: the outer graph still controls sequencing, retries, and the
merge gate, while the agent handles the messy "figure out what to edit" work.

Nested-agent tip: an agent's message list is its own loop state; the outer
`PipelineState` should store only the agent's **final message/result**, not the
whole transcript.

## 8. Parallel fan-out with `Send`

To process N items in parallel you don't loop in a node — you return a list of
`Send` objects from a node, and LangGraph fans out to N copies of a sub-node.
Each copy gets its own slice of state via `Send("target_node", payload)`.

```python
from langgraph.types import Send

def fan_out(state: State) -> list[Send]:
    return [Send("scan_one", {"name": r, "dir": state["dirs"][r]})
            for r in state["repos"]]

g.add_node("scan_one", scan_one)                 # runs once per repo, concurrently
g.add_conditional_edges("fan_out", fan_out, ["scan_one"])   # fan_out IS the router
g.add_edge("scan_one", "collect")                # gather results back
```

Two details that trip people up:

- The fan-out node is a **conditional-edge router that returns `Send` objects**
  instead of a string. The "condition" is the *count of items*, decided at
  runtime.
- Results come back through a **reducer on the shared key**. Each parallel
  `scan_one` returns `{"findings": [...]}`; with
  `findings: Annotated[list, add]` the next node (`collect`) sees one merged
  list, not the last writer's slice:

```python
def collect(state: State) -> dict:
    return {"summary": f"found {len(state['findings'])} findings across all repos"}
```

This repo processes repos sequentially per node (a design choice for simple
routing and log clarity), but any per-item work — scanning many repos, checking
many services, evaluating many test cases — is a textbook `Send` use case.

## 9. Static parallel branches and joins

`Send` is *dynamic* fan-out (N decided at runtime). For a fixed fan-out —
e.g. run "lint", "security", and "metrics" at the same time — draw **two edges
out of one node**. LangGraph runs the two downstream branches concurrently and
the join node starts only after **both** complete:

```python
g.add_edge("scan", "lint")
g.add_edge("scan", "security")
g.add_edge("scan", "metrics")
g.add_edge("lint", "review")        # review waits for ALL of
g.add_edge("security", "review")    # lint, security, metrics
g.add_edge("metrics", "review")
```

The join is implicit: a node with several incoming edges only runs once every
upstream branch feeding it has finished. This is a plain DAG — no reducer
required, because the branches write *different* keys:

```python
def lint(state):     return {"lint_report": ...}
def security(state): return {"security_report": ...}
def metrics(state):  return {"metrics_report": ...}
def review(state):   # state has all three reports
    ...
```

Common mistake: two branches write the **same key** → last-write-wins and the
join sees one report. Give each parallel branch its own state key (or use a
reducer).

## 10. Subgraphs

A compiled graph is just a node to another graph. Reuse a whole pipeline as one
step:

```python
quality_agent = build_quality_graph().compile()

g.add_node("quality", quality_agent)             # a CompiledGraph IS a node fn
g.add_edge("quality", "summarize")
```

Subgraph caveats:
- The subgraph's state must be a **superset-compatible** with the parent's
  channel where they connect (typically they share nothing, so it's clean).
- Errors in a subgraph propagate to the parent like any node exception.
- For complex cross-graph state, prefer `Send` + shared state channels over
  nesting.

## 11. Persistence & resumability (checkpointing)

The "graph runs to completion" model breaks for long jobs and crashed runs.
LangGraph checkpoints let you **resume from where it stopped**. Compile with a
checkpointer and pass `config={"configurable": {"thread_id": ...}}`.

```python
from langgraph.checkpoint.memory import MemorySaver

app = g.compile(checkpointer=MemorySaver())
config = {"configurable": {"thread_id": "run-transit-1"}}

app.invoke(initial_state, config=config)   # run...
app.invoke(None, config=config)            # resume after a crash/interrupt
```

For real runs use a durable store (`SqliteSaver`, `PostgresSaver`) instead of
`MemorySaver` (which lives only in-process). This is the mechanism behind
"human-in-the-loop" (see next) and long-running pipelines that survive restarts.

```python
from langgraph.checkpoint.sqlite import SqliteSaver

with SqliteSaver.from_conn_string("graph.db") as saver:
    app = g.compile(checkpointer=saver)               # survives process restarts
    config = {"configurable": {"thread_id": "transit-2026-08-06"}}
    app.invoke(initial_state, config=config)          # interrupted by a crash...
    app.invoke(None, config=config)                   # ...resumes exactly where it stopped
```

## 12. Interrupts (human-in-the-loop)

`interrupt()` pauses the graph mid-run, hands control to the caller, and
resumes with the caller's value — with the state exactly as it was:

```python
from langgraph.types import interrupt, Command

def approval_node(state):
    decision = interrupt({"message": f"merge {state['repo']}?", "findings": state["remaining"]})
    if decision == "reject":
        return {"policy": "leave_open"}
    return {"policy": "merge"}

# caller:
graph.invoke(state, config=config)        # runs up to approval_node, pauses
graph.invoke(Command(resume="approve"), config=config)   # feeds decision in, continues
```

Without a checkpointer this does nothing — interrupts *are* checkpoint
restores. Use for dangerous gates (auto-merge, paying APIs, deleting things)
that you still want to run unattended most of the time.

## 13. Long-term memory with a Store

Checkpoints remember *state per thread*. When you want memory that is **shared
across threads or survives graph runs** (e.g. "which repos did we already scan",
project conventions, user preferences), use a `Store`. Compiled graphs accept
a store alongside the checkpointer:

```python
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

store = InMemoryStore()

def recall_node(state: State) -> Command:
    # namespace: (scope, user_or_team) -> key
    prior = store.get(("prefs", "team-a"), "lint_rules")
    ...
    store.put(("prefs", "team-a"), "lint_rules", {"rules": ["B106", "S101"]})

app = g.compile(checkpointer=MemorySaver(), store=store)
```

`store.get/put/search` give every node (and every run, on every thread) the
same memory. In this repo's world: the store is where "we already analyzed
repos X, Y, Z" lives so you don't rescan them, or where the refactor agent
persists agreed code conventions across repos. Use `InMemoryStore` for tests,
`PostgresStore`/`RedisStore`/`UpstashStore` for anything you need to survive a
restart.

## 14. Streaming

`app.stream(state, stream_mode="updates")` yields `(node_name, updates)` as each
node finishes; `stream_mode="messages"` (on agent nodes) yields token-level LLM
output. Useful for progress bars and live logs:

```python
for node, update in app.stream(initial_state, stream_mode="updates"):
    print(f"==> {node}: {list(update)}")
```

## 15. Error handling & retries

A node that raises an exception **fails the whole invoke** unless you contain
it. Three layers, from local to global:

1. **Contain it in the node** — the pattern this repo uses for external
   services that can fail (a scanner crashing must not kill the run):

```python
def node_scan(state: State) -> dict:
    try:
        result = run_scanner(...)
    except ScannerError as exc:
        state["errors"].append(str(exc))     # record and keep going
        return {"status": "failed"}          # router can decide what to do
    return {"status": "ok", "findings": result}
```

2. **Retry with backoff** — attach a `RetryPolicy` to the node so transient
   errors (rate limits, timeouts) retry automatically:

```python
from langgraph.pregel import RetryPolicy

g.add_node("scan", node_scan,
           retry=RetryPolicy(max_attempts=3, initial_interval=1.0,
                             backoff_factor=2.0, retry_on=TransientError))
```

3. **Catch it at the graph level** — `invoke`/`stream` raise; wrap the call in
   `try/except` and decide whether to resume the same thread (checkpointer
   makes the state recoverable) or fail the run.

Best practice for real pipelines: *nodes never throw for expected failures* —
they return a status field and let a router branch to a fallback path. Reserve
exceptions for programmer bugs and unexpected conditions, then let `RetryPolicy`
absorb transient ones.

## 16. Debugging & testing

- **See the graph.** `app.get_graph().draw_mermaid()` prints a mermaid diagram
  (paste into mermaid.live); `draw_ascii()` gives a quick text layout. This
  repo does the same check on every change:

```python
app.get_graph().print_ascii()
```

- **Unit-test a node.** A node is just a function: call it with a fake state
  dict and assert the returned updates. No graph required.

```python
assert node_scan({"url": "x", "findings": []}) == {"status": "ok", "findings": [...]}
```

- **Replay / time travel.** With a checkpointer, inspect past states and even
  re-run from them:

```python
config = {"configurable": {"thread_id": "t1"}}
app.invoke(initial, config=config)
snapshots = list(app.get_state_history(config))     # every checkpoint
app.get_state(config)                               # latest state
app.update_state(config, {"status": "clean"})       # force-correct state, then resume
```

- **Trace token/step usage** via `app.stream(..., stream_mode=["updates", "debug"])`.

## 17. RunnableConfig: passing config into nodes

Nodes receive only `state` — but they can read the runtime config (thread_id,
tags, recursion limits) with `get_config()`:

```python
from langgraph.config import get_config

def node(state: State) -> dict:
    cfg = get_config()
    thread = cfg["configurable"]["thread_id"]
    ...
```

Raise the step cap for legitimately long runs (default is 25) per-invocation,
not globally:

```python
app.invoke(initial, config={"configurable": {"thread_id": "t1"},
                            "recursion_limit": 200})
```

`tags` on the config are useful to filter traces and logs when one graph is
shared by many callers.

## 18. Common gotchas (from this codebase)

| Trap | Symptom | Fix |
|---|---|---|
| Node returns a key not in the TypedDict | `InvalidUpdateError` at compile | add the key to the schema with a default |
| Conditional edge returns an unmapped string | `InvalidUpdateError` at runtime | every branch must be in `path_map` |
| Cycle without a counter | infinite loop | track `round`/attempts in state, break below a cap |
| Loop can't reach `END` | `GraphRecursionError` (default 25 steps) | every conditional path eventually leads to `END`; raise `recursion_limit` only if truly needed |
| Mutating `results` in place and forgetting the return | changes silently lost | always return `{"results": results}` after mutating |
| Parallel nodes writing the same key | last-write-wins data loss | use `Annotated[key, add]` or custom reducer |
| Agent node re-running the LLM on no-op | wasted tokens | guard node: `if not llm_configured(): return {}` |
| All work inside one giant node | no routing, no resumability, no retries | split into nodes; let edges + state be the workflow |
| Default 25-step recursion limit on legit big loops | `GraphRecursionError` | raise `g.compile(checkpointer=...).with_config({"recursion_limit": 200})` |

Two rules of thumb:
- **State is the source of truth.** If two nodes need to agree on something,
  it lives in the state dict, not in globals or files.
- **Nodes stay small and side-effect-free-ish.** Logging is fine, but return
  what changed. It makes graphs testable (`app.invoke({...})` with a fake
  state) and the routing logic decidable by reading one function.

## 19. One complete runnable example: review → repair → verify

Everything above, in one self-contained script you can run as-is (no LLM, no
containers — the "linter" is simulated). It shows the full toolset in action:
TypedDict state, a reducer for parallel aggregation, `Send` fan-out, a **bounded
retry cycle**, conditional edges, and streaming.

```python
"""review -> repair -> verify loop. Run: python mini_review_graph.py"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

MAX_ROUNDS = 2  # stop the loop after this many repair passes


class State(TypedDict):
    files: list[str]
    # reducer: every node's returned list is *appended*, so the N parallel
    # lint_one results arrive as ONE aggregated list at the next node.
    flagged: Annotated[list[str], "add"]
    fixed: list[str]      # entries fixed in the most recent repair pass
    round: int            # loop counter (no reducer: last write wins)


def todos(path: str) -> list[str]:
    """Simulated linter: flags every line that contains a TODO marker."""
    return [f"{path}:{i}:TODO" for i, ln in enumerate(Path(path).read_text().splitlines())
            if "TODO" in ln]


# --- fan-out: one Send per file, executed concurrently ---------------------
def fan_out(state: State) -> list[Send]:
    return [Send("lint_one", {"path": p}) for p in state["files"]]


def lint_one(payload: dict) -> dict:
    return {"flagged": todos(payload["path"])}


def repair(state: State) -> dict:
    """'Agent' node: fixes every flagged file and reports what it changed."""
    fixed = []
    for entry in state["flagged"]:
        path, _, _ = entry.split(":")
        lines = [ln for ln in Path(path).read_text().splitlines() if "TODO" not in ln]
        Path(path).write_text("\n".join(lines) + "\n")
        fixed.append(entry)
    return {"flagged": [], "fixed": fixed, "round": state["round"] + 1}


def verify(state: State) -> dict:
    """The gate: re-run the check on the (possibly repaired) files."""
    return {"flagged": [f for path in state["files"] for f in todos(path)]}


def after_verify(state: State) -> str:
    """Cycle breaker: loop only while TODOs remain AND we have budget left."""
    if state["flagged"] and state["round"] < MAX_ROUNDS:
        return "repair"
    return "done"


g = StateGraph(State)
g.add_node("fan_out", fan_out)
g.add_node("lint_one", lint_one)
g.add_node("repair", repair)
g.add_node("verify", verify)
g.add_edge(START, "fan_out")
g.add_conditional_edges("fan_out", fan_out, ["lint_one"])   # Send = dynamic fan-out
g.add_edge("lint_one", "repair")                            # reducer joins results
g.add_edge("repair", "verify")
g.add_conditional_edges("verify", after_verify, {"repair": "repair", "done": END})
app = g.compile()

# --- run it ---------------------------------------------------------------
demo = [Path(f"/tmp/demo-{i}.txt") for i in range(3)]
for i, p in enumerate(demo):
    p.write_text("line one\nTODO fix this\nline three\n")   # every file starts broken

initial = {"files": [str(p) for p in demo], "flagged": [], "fixed": [], "round": 0}

# stream it so you can watch the fan-out + loop happen live:
for node, update in app.stream(initial, stream_mode="updates"):
    print(f"{node:>9} -> {update}")

final = app.invoke(initial)
print("final round:", final["round"], "| remaining TODOs:", len(final["flagged"]))
```

Expected trace (reducer aggregation visible on `flagged`):

```
fan_out -> {'files': [...], ...}
lint_one -> {'flagged': ['/tmp/demo-1.txt:2:TODO']}   (three of these, one per file)
repair   -> {'flagged': [], 'fixed': [3 entries], 'round': 1}
verify   -> {'flagged': [...]}                          # re-linted: none remain? loop...
done
```

This is a miniature of this repo's pipeline: swap `lint_one` for the container
scan, `repair` for the ReAct agent, and `verify` for the re-run that decides
`merge | leave | none`. The loop bound (`MAX_ROUNDS`), the reducer, the router
and the gate are the exact same shape.

## 20. When *not* to use LangGraph

- Single linear LLM call → a plain `model.invoke(...)` or LangChain chain.
- One interactive agent chat session → `create_react_agent` alone (no outer graph).
- Pure numeric batch jobs → plain functions + multiprocessing.
- You need a **long-lived stateful worker** (no checkpoints) → LangGraph will
  fight you; use a queue/job system.

Reach for LangGraph when the flow is **conditional, looping, stateful across
many steps, resumable, or needs an autonomous agent embedded in a larger
process** — i.e. this repo's exact use case.

## Quick reference

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Send, interrupt, Command

g = StateGraph(State)                 # build
g.add_node(name, fn)                  # node = (state) -> partial state dict
g.add_edge(a, b)                      # plain transition
g.add_conditional_edges(a, router, path_map)   # router: (state) -> str
app = g.compile(checkpointer=MemorySaver())    # compile
out = app.invoke(state, config)       # run
out = app.invoke(Command(resume=v), config)    # resume from interrupt
for node, upd in app.stream(state, stream_mode="updates"): ...   # stream
```
