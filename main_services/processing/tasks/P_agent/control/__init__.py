"""The chat control policy of `AgentRun`: definitions, handlers and their coordinator.

`AgentRun` stays the execution controller. A turn with rules calls `control_event` at
`turn_started` and `tool_batch_completed`. The coordinator evaluates the pinned rules
and writes the resulting skill loads, policy calls and notes into the thread. A turn with
an empty rule list skips those activities. Handlers are trusted, read-only
modules with one interface (`model.PolicyHandler`), registered by name (`registry`).
Definitions are JSON (`definitions`). Handlers return findings and proposed actions, and
never write rows, change permissions or call tools.
"""
