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
the session id. Planner and sub-agent runs use the run id from `X-Hoover4-Agent-Run`.
The server reads the stored run kind before it selects the key. Tool arguments cannot
select another list.

## The plan tools

The same server serves the plan tools of a deep research plan, in `plan_tools.py`:
`read_plan`, `append_node`, `append_child`, `move_node`, `edit_node`, `remove_node` and
`read_plan_document`. The tree rules and the storage are in
[`../../processing/database/agent_plans.py`](../../processing/database/agent_plans.py),
which the worker reads as well.

The server reads the agent run id from `X-Hoover4-Agent-Run`, reads that run's
`agent_runs` row under the owner from the other two headers, and takes its `plan_run_id`.
A sub-agent row copies the `plan_run_id`, so the sub-agents of a planner reach the plan too.
**No role check exists.** The plan run state is the only rule: a change is accepted only in
`planning` or `revising`. After approval `read_plan` returns the approved version.

`read_plan` shows each node with its outline number (`root`, `1`, `1.2`).
Every node argument accepts that number or the stored id. A refusal lists numbers and text.
Each mutation takes the version of the last plan result. Calls of one reply can give the same
version. A call is refused if a later change moved or removed a node that its number names.

**One change of a plan at a time.** Each version is one row, so two parallel changes that
read the same version would lose one of them. The server holds one `asyncio.Lock` for each
plan run. A change takes the lock, reads the newest version, writes version plus one, and
releases the lock. This holds because the server runs as one process in one container.

**One version for each mutation key.** A change that carries a UUID in
`X-Hoover4-Idempotency-Key` stores it on the version it writes, in the `idempotency_key`
column of `agent_plan_snapshots`. A second change with that key writes nothing and returns
that version. A change with no key, or with a value that is not a UUID, writes a new
version each time.

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
