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

The todo list uses the user and session identifiers from request headers.
Tool arguments cannot select another list.

`read_todo` returns the goal and all steps.
`write_todo` returns the version and step identifiers.
`edit_todo` and `mark_todo` return open steps.
Every result includes the version.

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
