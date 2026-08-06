-- Rolling 24h per-API-call timings and sizes for the admin metrics page.
--
-- Same privacy rule as usage_events: function names only — a bounded,
-- low-cardinality set of Rust handler / server-function names — never a URL,
-- never a query string.
--
-- The TTL is applied by background merges, so rows can outlive 24h briefly.
-- Every read query must therefore filter on event_ts itself rather than trusting
-- the TTL.
CREATE TABLE IF NOT EXISTS api_events
(
    username LowCardinality(String),
    event_type LowCardinality(String) COMMENT 'Same vocabulary as usage_events, so the two tables can be shown side by side',
    event_ts DateTime64(3),
    function_name LowCardinality(String) COMMENT 'Rust handler or server-function name. NOT the URL',
    is_error UInt8 COMMENT '1 when the handler returned an error',
    duration_ms UInt32,
    bytes_in UInt32,
    bytes_out UInt32
)
ENGINE = MergeTree
ORDER BY (username, event_type, event_ts)
TTL toDateTime(event_ts) + INTERVAL 24 HOUR DELETE
COMMENT 'Rolling 24h per-API-call timings and sizes for the admin metrics page. Function names only - never a URL or a query string.';
