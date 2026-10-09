"""The chat control policy of `AgentRun`: definitions, handlers and their coordinator.

`AgentRun` stays the execution controller. At three hooks (`turn_started`,
`tool_batch_completed`, `answer_drafted`) it calls the `control_event` activity, whose
coordinator evaluates the rules of the run's pinned definition and writes the resulting
skill loads, policy calls and notes into the stored thread. Handlers are trusted, read-only
modules with one interface (`model.PolicyHandler`), registered by name (`registry`).
Definitions are JSON (`definitions`). Handlers return findings and proposed actions, and
never write rows, change permissions or call tools.
"""
