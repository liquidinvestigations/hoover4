-- Rolling AI-service call samples for /admin/ai_status use% and traffic strips.
--
-- Each writer (agent, website summariser, MCP servers that opt in) inserts one row per
-- outbound call to an AI capability. TTL 14 days, same discipline as llm_call_events:
-- do not trust the TTL for correctness, filter on event_time on every read.
--
-- Guests are recorded as the literal 'guest', never as an empty string.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS ai_service_telemetry
(
    event_time   DateTime DEFAULT now() COMMENT 'When the call completed',
    service      LowCardinality(String) COMMENT 'llm | embeddings | rerank | ner | ocr | browser | catalog',
    provider     LowCardinality(String) DEFAULT '' COMMENT 'Endpoint that actually answered, empty when unknown',
    username     LowCardinality(String) DEFAULT '' COMMENT 'Caller, or the literal guest for guest sessions',
    session_id   String DEFAULT '' COMMENT 'Chat session when known',
    latency_ms   UInt32 DEFAULT 0,
    ok           UInt8  DEFAULT 1,
    detail       String DEFAULT '' COMMENT 'Short free-form note: model id, error class, circuit open'
)
ENGINE = MergeTree
ORDER BY (service, event_time)
TTL event_time + INTERVAL 14 DAY DELETE
COMMENT 'AI service call samples. Feeds use% and recent-traffic panels on /admin/ai_status.';
