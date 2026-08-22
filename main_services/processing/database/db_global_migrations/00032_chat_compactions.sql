-- The trail left by a context compaction, so a compaction error can be debugged.
--
-- Compaction never edits the transcript. chat_messages is not touched, no row is deleted
-- and no row is rewritten - a user scrolling back through their own conversation sees
-- exactly what they saw before. What changes is only the list handed to the model on the
-- next call inside a turn, and this table is the record of that change.
--
-- Layer one is eviction: the content of old tool results is replaced by a placeholder
-- while the assistant messages that requested them keep their tool calls intact, so the
-- model still sees that it searched and what it searched for. evicted names those tools
-- in the order they ran.
--
-- tokens_before is the prompt-plus-completion the provider billed for the model call
-- that crossed the threshold. tokens_after is the prompt the provider billed for the
-- first call made on the shortened list, so it arrives one call later and is 0 until
-- then. Both are provider counts - nothing here is estimated from a tokeniser that is
-- not the model's.
--
-- threshold_tokens is the trigger as it was evaluated, and context_window the
-- denominator it came from. A window of 0 means the provider never stated one, in which
-- case no compaction is evaluated at all and no row reaches this table.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS chat_compactions
(
    compaction_id    String   COMMENT 'Unique id of this compaction, so tokens_after can be filled in on a later insert',
    event_time       DateTime DEFAULT now() COMMENT 'When the compaction was applied',
    username         String   DEFAULT '' COMMENT 'Owner of the conversation, guests recorded as the literal guest',
    session_id       String   DEFAULT '' COMMENT 'Chat session the turn belongs to',
    model_id         String   DEFAULT '' COMMENT 'Model that was about to be called',
    layer            LowCardinality(String) DEFAULT 'eviction' COMMENT 'Which compaction layer produced this row',
    context_window   UInt32   DEFAULT 0 COMMENT 'Denominator the trigger divided by, from the model catalog',
    threshold_tokens UInt32   DEFAULT 0 COMMENT 'Token count at or above which compaction fires - the configured fraction of context_window',
    tokens_before    UInt32   DEFAULT 0 COMMENT 'Prompt plus completion of the model call that crossed the threshold',
    tokens_after     UInt32   DEFAULT 0 COMMENT 'Prompt of the first model call made on the shortened list. 0 until that call returns',
    messages_before  UInt32   DEFAULT 0 COMMENT 'Length of the model-visible message list before eviction',
    messages_after   UInt32   DEFAULT 0 COMMENT 'Length of the model-visible message list after eviction - unchanged by layer one, which shortens content rather than dropping messages',
    evicted_count    UInt32   DEFAULT 0 COMMENT 'How many tool results had their content replaced',
    kept_count       UInt32   DEFAULT 0 COMMENT 'How many recent tool results were left intact',
    chars_before     UInt64   DEFAULT 0 COMMENT 'Characters of tool-result content before eviction',
    chars_after      UInt64   DEFAULT 0 COMMENT 'Characters of tool-result content after eviction',
    evicted          Array(String) COMMENT 'Names of the evicted tool results, in the order they ran',
    updated_at       DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (session_id, compaction_id)
COMMENT 'One row per applied context compaction. The transcript is never edited - this is the only record that a model saw less than the transcript holds.';
