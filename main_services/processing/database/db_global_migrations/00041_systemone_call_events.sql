-- One row records one classifier or requirement-completion request of a chat hook.
-- Stable request ids identify retries. The table contains no request or source text.
CREATE TABLE IF NOT EXISTS systemone_call_events
(
    event_time DateTime64(3),
    username LowCardinality(String),
    session_id String,
    run_id String,
    turn_seq UInt32,
    hook LowCardinality(String),
    rule_id LowCardinality(String),
    handler LowCardinality(String),
    definition_revision String,
    request_id String,
    model_id LowCardinality(String),
    route LowCardinality(String),
    question_ids Array(LowCardinality(String)),
    question_types Array(LowCardinality(String)),
    answer_values Array(Nullable(Float32)),
    answer_status Array(LowCardinality(String)),
    outcome LowCardinality(String),
    http_status UInt16 COMMENT '0 means no HTTP response',
    latency_ms UInt32,
    deadline_ms UInt32 COMMENT 'Time left in the hook when the request started',
    actions UInt16,
    positive_answers UInt16,
    scored_answers UInt16
)
ENGINE = MergeTree
ORDER BY (event_time, hook)
TTL toDateTime(event_time) + INTERVAL 90 DAY DELETE;
