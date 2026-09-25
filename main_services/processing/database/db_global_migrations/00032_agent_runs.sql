-- Agent run storage. One row per agent run, the model conversation of each run thread, and
-- the stop requests of a chat turn.
--
-- A run row is the state of one AgentRun workflow. The workflow input holds ids only, and
-- every activity reads the row and the thread from these tables. A retry therefore reads the
-- same state, and no answer, tool result or briefing crosses a Temporal payload.
--
-- Every write uses a key made from the run id: agent_runs by run_id, agent_run_messages by
-- (thread_id, idx). agent_runs is versioned by state_version, which a writer reads and
-- increases by one, so a late creation write at version 1 never replaces a later write.
-- agent_run_messages is versioned by updated_at, so a streaming partial (is_final 0) is
-- rewritten in place and the complete message replaces it.
--
-- Every read uses FINAL and the full owner prefix of the sort key:
--   SELECT ... FROM agent_runs FINAL WHERE username = ? AND session_id = ? AND run_id = ?
--   SELECT ... FROM agent_run_messages FINAL WHERE username = ? AND session_id = ? AND thread_id = ? ORDER BY idx
--   SELECT ... FROM agent_turn_stops FINAL WHERE username = ? AND session_id = ? AND turn_seq = ?
-- Without FINAL, a read before a merge sees every partial version of a message.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS agent_runs
(
    run_id UUID COMMENT 'Run id. The workflow id is run-{run_id} for a run that a run starts',
    username LowCardinality(String) COMMENT 'Owner',
    session_id String COMMENT 'Owning chat session',
    turn_seq UInt32 COMMENT 'Seq of the user row of the turn this run belongs to',
    thread_id UUID COMMENT 'The run thread. A continuation keeps the thread of the run it continues',
    parent_run_id Nullable(UUID) COMMENT 'The run that delegated this one. A continuation copies it. Null at depth 0',
    batch_id Nullable(UUID) COMMENT 'The delegation batch of the parent. A continuation copies it. Null at depth 0',
    continues_run_id Nullable(UUID) COMMENT 'The run this one continues after its batch, null for the first run of a thread',
    depth UInt8 COMMENT '0 for a lead, 1 or 2 for a sub-agent',
    kind LowCardinality(String) COMMENT 'chat, subagent, planner or organizer',
    plan_run_id Nullable(UUID) COMMENT 'The agent_plan_runs row this run serves',
    plan_node_id Nullable(UUID) COMMENT 'The plan section a sub-agent works on',
    purpose LowCardinality(String) COMMENT 'execute, review or correct for a plan sub-agent, empty otherwise',
    queue LowCardinality(String) COMMENT 'Task queue of the agent activity',
    workflow_id String COMMENT 'Temporal workflow id',
    state LowCardinality(String) COMMENT 'running, waiting_for_children, completed, failed or cancelled',
    briefing String COMMENT 'The briefing JSON of a sub-agent, empty for a lead and a continuation',
    tool_call_id String COMMENT 'The run_subagent call of the parent that this run answers. A continuation copies it',
    delegated_batch_id Nullable(UUID) COMMENT 'The batch this run started, null until it delegates',
    delegate_seq UInt32 COMMENT 'Seq of the first run_subagent tool row of this run, 0 when it wrote none',
    refused_json String COMMENT 'JSON list of the briefings the budgets refused, with the reason',
    subagent_share UInt16 COMMENT 'Sub-agent runs a depth 1 run and its continuations may still create',
    result String COMMENT 'The answer or report, empty until the run ends. write_ending copies it into the chain',
    error String COMMENT 'The cause of a failure',
    start_seq UInt32 COMMENT 'First transcript seq this run may write, 0 for a run that writes no transcript row',
    next_seq UInt32 COMMENT 'Next free transcript seq after the rows this run wrote',
    tool_turns_used UInt16 COMMENT 'Tool turns of the current round, reset by a nag round',
    extra_tool_turns UInt16 COMMENT 'Nag allowance of the current round',
    nags_this_turn UInt8 COMMENT 'Nags in this user turn, for a chat lead',
    nags_without_progress UInt8 COMMENT 'Nags since the todo list last changed, for a chat lead',
    prompt_tokens UInt64 COMMENT 'Provider prompt tokens',
    completion_tokens UInt64 COMMENT 'Provider completion tokens',
    started_at DateTime64(3) COMMENT 'Row creation time',
    state_version UInt64 COMMENT 'Monotonic version, one more on each write',
    updated_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(state_version)
ORDER BY (username, session_id, run_id)
COMMENT 'Agent runs. Writers: the AgentRun activities and the agent run sweep, see agent_runs.py';

CREATE TABLE IF NOT EXISTS agent_run_messages
(
    username LowCardinality(String) COMMENT 'Owner',
    session_id String COMMENT 'Owning chat session',
    thread_id UUID COMMENT 'The run thread',
    idx UInt32 COMMENT 'Message index in the thread',
    run_id UUID COMMENT 'The run that wrote the message',
    role LowCardinality(String) COMMENT 'human, ai or tool',
    content String COMMENT 'Text, or the exact tool result text',
    reasoning String COMMENT 'Model reasoning text of an ai message',
    tool_calls_json String COMMENT 'JSON list of id, name and args for an ai message',
    tool_call_id String COMMENT 'The call a tool message answers',
    tool_name String COMMENT 'Tool name of a tool message',
    usage_json String COMMENT 'Provider usage of an ai message',
    is_final UInt8 COMMENT '0 while a partial is streaming, 1 when complete',
    updated_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (username, session_id, thread_id, idx)
COMMENT 'The model conversation of each run thread. Writers: the run_agent and append_nag activities';

CREATE TABLE IF NOT EXISTS agent_turn_stops
(
    username LowCardinality(String) COMMENT 'Owner',
    session_id String COMMENT 'Owning chat session',
    turn_seq UInt32 COMMENT 'Seq of the user row of the stopped turn',
    created_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (username, session_id, turn_seq)
COMMENT 'Stop requests. Writer: the website';
