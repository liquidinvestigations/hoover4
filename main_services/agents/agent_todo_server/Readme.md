# agent todo MCP server

One todo list per chat or agent run (a goal and a list of steps) is exposed as four tools:
`read_todo`, `write_todo`, `edit_todo` and `mark_todo`.

**The server holds no rules.** Every shape, limit and refusal lives in
[`../../processing/database/chat_todos.py`](../../processing/database/chat_todos.py),
which the chat workflow reads directly. This server is identity, typed arguments and a
readable refusal on top of it. A new write uses two statuses, `pending` and `done`, and a
step that a call moves to `done` requires a short reason in `note`. Done and replaced
steps stay in the list with their ids. An identical call writes no new version. A second
copy of these rules at this layer is how the tool and the workflow start disagreeing
about the state of a plan.

Four tools rather than one dispatcher with a `mode` argument: each argument shape is
different, and a typed schema is what makes a model call it correctly the first time.
`write_todo` takes a `goal` and `steps`, a list of step strings. A new goal starts a list
whose steps get the ids `1`, `2`, `3` in order. The same goal again keeps the done steps,
as `edit_todo` does. `edit_todo` takes `steps` and optional `replacements`, a list of
`{id, text, note}` entries. A step that `edit_todo` keeps by its text keeps its id, status
and note. A new step gets an id above every id in the list. An open step that the new list
omits becomes done with the note `removed from plan`. A replacement ends the old step with
its note and puts it directly above the new step, which records `replaces_id`.
`mark_todo` takes `ids`, a list of step ids, one `status`, `pending` or `done`, and a
`note`, which `done` requires. An empty goal or an empty step list is refused, and
`edit_todo` in a conversation with no plan is refused with "No plan exists yet. Call
write_todo first." A refusal is a tool error whose text is the response: the error and the
plan as it still stands. The agent keeps a tool error as a failed result.

## The caller

The todo list uses the user and session identifiers from request headers.
Tool arguments cannot select another list.

`read_todo` returns the goal and all steps. A legacy `in_progress` step reads as
`pending`, and a legacy `cancelled` step reads as `done` with its note.
`write_todo` returns the version and step identifiers.
`edit_todo` and `mark_todo` return open steps.
Every result includes the version. A call that changed nothing also returns `unchanged`.

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
