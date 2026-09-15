-- The LLM model catalog, refreshed from each provider's /v1/models.
--
-- Model ids are discovered at runtime, never hardcoded: NIM retires ids, and a
-- hardcoded one turns into a 404 months after the code was written. The chat and
-- summarisation choices are stored in server_settings and must be matched against this
-- table by pattern (nemotron.*super, then nemotron.*ultra) at the time they are set.
--
-- The refresh must not sit on the request path. "Refresh if older than 3h" with N
-- concurrent readers is a thundering herd against every provider: single-flight it with
-- an in-process lock, run it in the background, time-box each provider, and serve stale
-- rows meanwhile. fetched_at is what makes stale rows recognisable as stale.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS llm_models
(
    provider        LowCardinality(String) COMMENT 'Provider name as configured: nvidia | selfhosted | openai | anthropic | moonshot',
    model_id        String   COMMENT 'Provider-native model id, sent verbatim in the API call',
    display_name    String   DEFAULT '' COMMENT 'Human-readable label for the picker',
    context_window  UInt32   DEFAULT 0 COMMENT 'Max context in tokens, 0 when the provider does not say',
    price_in_milli  UInt32   DEFAULT 0 COMMENT 'Input price in thousandths of a cent per 1k tokens, 0 when unknown',
    price_out_milli UInt32   DEFAULT 0 COMMENT 'Output price in thousandths of a cent per 1k tokens, 0 when unknown',
    supports_tools  UInt8    DEFAULT 0 COMMENT 'Passed a tool-calling smoke test',
    supports_vision UInt8    DEFAULT 0,
    is_reasoning    UInt8    DEFAULT 0 COMMENT 'Emits reasoning content that must be stripped from the answer body',
    is_allowed      UInt8    DEFAULT 1 COMMENT 'Admin allowlist. Enforced server-side: a forged model id in a request is rejected, not merely absent from the dropdown',
    fetched_at      DateTime DEFAULT now() COMMENT 'When this row was last confirmed by the provider - the staleness clock',
    updated_at      DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted      UInt8    DEFAULT 0 COMMENT 'Soft-delete tombstone, set when a provider stops listing the model'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (provider, model_id)
COMMENT 'Provider model catalog, discovered from /v1/models and refreshed in the background.';
