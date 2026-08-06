-- LLM call telemetry, TTL 14 days.
--
-- Feeds the median-latency figure in the model picker and the provider health strip on
-- /admin/llm. Rolling and bounded, like usage_events and api_events.
--
-- Two recording rules that read as bugs when broken:
--   * guests are recorded as 'guest', never as an empty string
--   * reasoning tokens are billed while contributing nothing to the visible answer, so
--     they get their own column. reply_bytes under-reports the cost of a reasoning model
--     by design and cannot be used as a proxy for it.
--
-- Do not trust the TTL for correctness: merges apply it lazily, so every read filters on
-- event_time as well.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS llm_call_events
(
    event_time        DateTime DEFAULT now() COMMENT 'When the call completed',
    username          LowCardinality(String) COMMENT 'Caller, or the literal guest for guest sessions',
    session_id        String   DEFAULT '' COMMENT 'Chat session, empty for background calls like summarisation',
    kind              LowCardinality(String) COMMENT 'chat | summarize | title | catalog_probe',
    provider          LowCardinality(String) COMMENT 'Provider that actually served the call',
    model_id          String   COMMENT 'Model that actually served the call, never the configured one',
    prompt_tokens     UInt32 DEFAULT 0,
    completion_tokens UInt32 DEFAULT 0,
    reasoning_tokens  UInt32 DEFAULT 0 COMMENT 'Billed, invisible in the answer body',
    reply_bytes       UInt32 DEFAULT 0 COMMENT 'Size of the visible answer - under-reports reasoning models by design',
    latency_ms        UInt32 DEFAULT 0,
    ok                UInt8  DEFAULT 1,
    error             String DEFAULT ''
)
ENGINE = MergeTree
ORDER BY (event_time, username)
TTL event_time + INTERVAL 14 DAY DELETE
COMMENT 'LLM call telemetry, rolling 14 days. Feeds model-picker latency and provider health.';
