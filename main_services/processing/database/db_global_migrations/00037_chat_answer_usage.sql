-- Answer metadata stores citation status and the tool scope used by its run.
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS usage_json String DEFAULT '{}';
