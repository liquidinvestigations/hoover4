CREATE TABLE IF NOT EXISTS temp_chat_json_objects
(
    task_id String COMMENT 'Primary key for this temporary object',
    context_id String COMMENT 'Optional grouping/correlation id',
    json_data_string String COMMENT 'Raw JSON payload as string',
    date_created DateTime COMMENT 'Creation time (UTC)'
)
ENGINE = ReplacingMergeTree
ORDER BY (task_id)
COMMENT 'Temporary JSON storage for workflow scratch data.';


