-- One row for each attempt of an agent model call, tool call and title call. The step
-- activities write it, and the AgentRun workflow writes the row of an attempt that never
-- ran or lost its heartbeat. The reports on /admin/llm read it.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS agent_step_events
(
    event_time        DateTime64(3) COMMENT 'When the attempt ended',
    username          LowCardinality(String) COMMENT 'Owner of the run, or the literal guest',
    session_id        String COMMENT 'Chat session',
    run_id            UUID COMMENT 'agent_runs.run_id. The chat lead run for a title call',
    run_kind          LowCardinality(String) COMMENT 'chat, subagent, planner, organizer or title',
    step              LowCardinality(String) COMMENT 'model, tool or title',
    mode              LowCardinality(String) DEFAULT '' COMMENT 'tools, final or plan for a model step, empty otherwise',
    name              LowCardinality(String) COMMENT 'Tool name for a tool step, model id for a model or title step',
    tool_call_id      String DEFAULT '' COMMENT 'The call a tool step answers',
    task_queue        LowCardinality(String) COMMENT 'Queue of the activity',
    attempt           UInt16 COMMENT 'Temporal attempt, 1 for the first, 0 when the workflow wrote the row',
    queue_wait_ms     UInt32 COMMENT 'Time the attempt waited for a slot',
    duration_ms       UInt32 COMMENT 'Wall time of the attempt, 0 when it never started',
    ok                UInt8 COMMENT '1 when the step produced its result',
    error_class       LowCardinality(String) DEFAULT '' COMMENT 'Short class, for example read_timeout or tool_error',
    error             String DEFAULT '' COMMENT 'First 500 characters of the error',
    prompt_tokens     UInt32 DEFAULT 0,
    completion_tokens UInt32 DEFAULT 0,
    reasoning_tokens  UInt32 DEFAULT 0
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, step, name)
TTL toDateTime(event_time) + INTERVAL 90 DAY DELETE
COMMENT 'One row for each attempt of an agent model call, tool call and title call. Feeds the reports on /admin/llm';
