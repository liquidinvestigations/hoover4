# agent todo MCP server

One todo list per chat or agent run (a goal and a list of steps) is exposed as four tools:
`read_todo`, `write_todo`, `edit_todo` and `mark_todo`.

**The server holds no rules.** Every shape, limit and refusal lives in
[`../../processing/database/chat_todos.py`](../../processing/database/chat_todos.py),
which the chat workflow reads directly. This server is identity, typed arguments and a
readable refusal on top of it. Two of those rules must never be
relaxed here: a `cancelled` item requires a note, and a bare status flip is not a
material change. Both exist so the plan protocol cannot be gamed, and a second copy of
either at this layer is how the tool and the workflow start disagreeing about whether a
plan was abandoned or finished.

Four tools rather than one dispatcher with a `mode` argument: each argument shape is
different, and a typed schema is what makes a model call it correctly the first time.
`write_todo` takes a `goal` and `steps`, a list of step strings. `edit_todo` takes `steps`.
`mark_todo` takes `ids`, a list of step ids, one `status` and an optional `note`. No
argument is a JSON object: the store gives each step its id, `1`, `2`, `3` in order, and a
step that `edit_todo` keeps by its text keeps its id and status. An empty goal or an empty
step list is refused, and `edit_todo` in a conversation with no plan is refused with "No
plan exists yet. Call write_todo first." A refusal is a tool error whose text is the
response: the error and the plan as it still stands. The agent keeps a tool error as a
failed result.

## The caller

The list uses the user and chat session from request headers. Chat and organizer runs use
the session id. Planner runs use the run id. Sub-agent runs use their thread id, which
stays the same when a continuation gets a new run id.
The server reads the stored run kind before it selects the key. Tool arguments cannot
select another list.

## The plan tools

The same server serves the plan tools of a deep research plan, in `plan_tools.py`:
`read_plan`, `write_plan`, `read_plan_document` and `read_plan_report`. The tree rules and the storage are in
[`../../processing/database/agent_plans.py`](../../processing/database/agent_plans.py),
which the worker reads as well.

The server reads the agent run id from `X-Hoover4-Agent-Run`, reads that run's
`agent_runs` row under the owner from the other two headers, and takes its `plan_run_id`.
A sub-agent row copies the `plan_run_id`, so the sub-agents of a plan reach the plan too.
**No role check exists.** The plan run state is the only rule: a change is accepted only in
`planning` or `revising`. After approval `read_plan` returns the approved version.

`read_plan` shows each node with its outline number (`root`, `1`, `1.2`). Each top-level
node is a section, which one researcher runs with every node under it.

**A whole tree for each write.** `write_plan(version, children)` takes the root's children as
nested nodes. Each node has `text`, `children`, and optionally `node_id`: the stored id or the
outline number of a node of the current tree, which keeps that node's identity. A node with no
`node_id` gets a new id from the write key and its place in the tree. A node that the call
leaves out is removed. The root keeps its id and its text. The tree holds at most 4 sections
and 150 nodes.

**One writer at a time, at the exact version.** Each version is one row. The server holds one
`asyncio.Lock` for each plan run. A write takes the lock, reads the newest version, and writes
version plus one only when the call names the newest version. A call that names another
version gets `stale_version` with the current tree, and nothing is written. This holds because
the server runs as one process in one container.

**One version for each write key.** A write that carries a UUID in
`X-Hoover4-Idempotency-Key` stores it on the version it writes, in the `idempotency_key`
column of `agent_plan_snapshots`. A second write with that key returns that version before
the version test, and writes nothing. A write with no key, or with a value that is not a
UUID, needs the current version.

**A report is read in pages.** `read_plan_report(node_id, cursor)` reads the typed report
(`report_data` document) of the newest sub-agent thread of a node, which the worker writes
when the thread ends. The node is an id or a number path. The report is a list of units:
how the run ended, the final answer, the newest model texts, the diagnostics, and one unit
for each evidence entry. A long text is several units. A page holds the units that fit the
call's page share, at most 16,000 bytes, and at least one unit. `more` is the cursor of the
next page: the first 16 hex characters of the digest of the units, a colon, and the next
unit. A cursor of a report that changed is refused, and the caller reads from the first
page again. A thread with only a text `report` gives it as `legacy_text` units.
`read_plan_document` reads a body that the worker stored as an artifact, with the owner
and digest check of `agent_plans.document_body`.

`read_todo` returns the goal and all steps. `write_todo` returns the version and step ids.
`edit_todo` and `mark_todo` return open steps. Every result keeps the version.

## Build context

**Its build context is `main_services`**, wider than every other MCP server's, because the
image needs both `agents/agent_common` and `processing/database` and a Docker build cannot
reach outside its context. [`../../.dockerignore`](../../.dockerignore) narrows that
context back to those two directories; without it the context is the whole working tree.
If you move the Dockerfile, move `context:` in
[`../../ops/docker/compose/agents.yaml`](../../ops/docker/compose/agents.yaml) with it.

## Tests

```
docker exec hoover4-mcp-todo python -m pytest /app/tests -q
```

Storage is replaced with a dict, so the suite needs no ClickHouse; the validation it
exercises is the real module's.
