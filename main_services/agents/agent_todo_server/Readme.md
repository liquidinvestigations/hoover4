# agent todo MCP server

One todo list per chat conversation (a goal and a list of steps) exposed as four tools:
`read_todo`, `write_todo`, `edit_todo` and `mark_todo`.

**The server holds no rules.** Every shape, limit and refusal lives in
[`../../processing/database/chat_todos.py`](../../processing/database/chat_todos.py),
which the chat workflow reads directly. This server is identity, argument coercion and a
readable refusal on top of it. Two of those rules must never be
relaxed here: a `cancelled` item requires a note, and a bare status flip is not a
material change. Both exist so the plan protocol cannot be gamed, and a second copy of
either at this layer is how the tool and the workflow start disagreeing about whether a
plan was abandoned or finished.

Four tools rather than one dispatcher with a `mode` argument: each argument shape is
genuinely different, and a typed schema is what makes a model call it correctly the first
time.

## The caller

The list is keyed by `(username, session_id)` and **both come from request headers**,
never from a tool argument: `X-Hoover4-User` and `X-Hoover4-Chat-Session`, the same pair
the browser server uses for its per-chat isolation, behind the same bearer token the
collection server checks. A session id the model could write would let it read and
rewrite another conversation's plan.

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
