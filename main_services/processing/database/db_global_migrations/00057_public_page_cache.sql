CREATE TABLE IF NOT EXISTS public_page_cache
(
    cache_key String,
    body_key String,
    body_bytes UInt64,
    fetched_ms UInt64,
    expires_at DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(fetched_ms)
ORDER BY cache_key
TTL toDateTime(expires_at) DELETE
