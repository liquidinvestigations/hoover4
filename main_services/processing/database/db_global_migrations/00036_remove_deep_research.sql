-- Chat runs store one conversation turn.
-- Artifact hashes and write keys support durable tool results.
DROP TABLE IF EXISTS agent_plan_snapshots;
DROP TABLE IF EXISTS agent_plan_runs;
DROP TABLE IF EXISTS agent_plan_documents;
DROP TABLE IF EXISTS agent_plan_decisions;

ALTER TABLE chat_messages DROP COLUMN IF EXISTS plan_reference_json;

ALTER TABLE chat_sessions DROP COLUMN IF EXISTS deep_research;

ALTER TABLE agent_runs
    DROP COLUMN IF EXISTS parent_run_id,
    DROP COLUMN IF EXISTS batch_id,
    DROP COLUMN IF EXISTS continues_run_id,
    DROP COLUMN IF EXISTS depth,
    DROP COLUMN IF EXISTS kind,
    DROP COLUMN IF EXISTS plan_run_id,
    DROP COLUMN IF EXISTS plan_node_id,
    DROP COLUMN IF EXISTS purpose,
    DROP COLUMN IF EXISTS briefing,
    DROP COLUMN IF EXISTS tool_call_id,
    DROP COLUMN IF EXISTS delegated_batch_id,
    DROP COLUMN IF EXISTS delegate_seq,
    DROP COLUMN IF EXISTS refused_json,
    DROP COLUMN IF EXISTS subagent_share,
    DROP COLUMN IF EXISTS tool_turns_used,
    DROP COLUMN IF EXISTS extra_tool_turns,
    DROP COLUMN IF EXISTS nags_this_turn,
    DROP COLUMN IF EXISTS nags_without_progress;
