# agent todo MCP server

The session tool server. One plan per chat or agent run (a goal and a list of steps) is
exposed as one tool, `update_plan`. The workspace files of a conversation are exposed as
three more: `read_file`, `write_file` and `patch_file` (see [Workspace files](#workspace-files)).

**The server holds no rules.** Every shape, limit and refusal lives in
[`../../processing/database/chat_todos.py`](../../processing/database/chat_todos.py),
which the chat workflow reads directly. This server is identity, typed arguments and a
readable refusal on top of it. A new write uses two statuses, `pending` and `done`, and a
done step has a short reason in `note`. An identical call writes no new version. A second
copy of these rules at this layer is how the tool and the workflow start disagreeing
about the state of a plan.

`update_plan` takes a `goal` and `steps`, the whole ordered list of steps. Each step has
`text`, `status` (`pending` by default, or `done`) and `note`. The stored plan is the given
list. With the same goal, a step with the same text keeps its id, and a new step gets an id
above every id in the list. A new goal numbers the steps `1`, `2`, `3`. A done step without
a note gets the note `done`, or its earlier note. An empty goal or an empty step list is
refused. A refusal is a tool error whose text is the response: the error and the plan as it
still stands. The agent keeps a tool error as a failed result.

One tool replaces the earlier four (`read_todo`, `write_todo`, `edit_todo`, `mark_todo`).
With those tools, the agent model called `write_todo` when it meant to write a report file,
and it read their short results as a fault. Rows of older conversations keep the four names,
and the website still shows them.

## The caller

The plan uses the user and session identifiers from request headers.
Tool arguments cannot select another plan.

Every result holds the goal, every step with its id, status and note, the version and a
summary. A legacy `in_progress` step reads as `pending`, and a legacy `cancelled` step
reads as `done` with its note. A call that changed nothing also returns `unchanged`.

## Workspace files

[agent_todo_server/workspace.py](agent_todo_server/workspace.py) serves the workspace tools. The rules live in the
pipeline: the storage and the read format in
[`../../processing/database/chat_workspace.py`](../../processing/database/chat_workspace.py), and the write and patch
rules in [`../../processing/tasks/P_workspace/`](../../processing/tasks/P_workspace). `read_file` reads storage
directly. `write_file` and `patch_file` send the command to the session writer
workflow `WorkspaceWriter` on `chat-queue` with signal-with-start (`TEMPORAL_ADDRESS`), and
read the receipt of the operation id every 0.3 s for up to `WORKSPACE_WRITER_WAIT_SECONDS`
(60). The operation id is the `X-Hoover4-Idempotency-Key` header that the worker sends for
the tool call. A failed receipt is a tool error with the result as its text. A writer that
cannot be reached, or that gives no receipt in time, is a tool error with `retryable` true,
and the worker sends the call again with the same key.

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
