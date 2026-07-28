CREATE TABLE IF NOT EXISTS search_manticore_cache (
    query_hash String COMMENT 'The hash of the search query string',
    query_string String COMMENT 'The search query string',
    result_json String COMMENT 'The search result in JSON format',
    date_created DateTime DEFAULT now() COMMENT 'Timestamp when the search cache was created',
    duration_ms UInt32 DEFAULT 0 COMMENT 'The duration of the search in milliseconds',
)
ENGINE = MergeTree
ORDER BY (query_hash, query_string)
TTL date_created + INTERVAL 1 HOUR
COMMENT 'Cached website search responses. Global: a response may span several collections.';
