-- Two columns of the step-level agent loop. model_steps counts the model calls of a run
-- thread, and a continuation copies it. end_reason says why a completed run ended.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS model_steps UInt32 DEFAULT 0
    COMMENT 'Model calls of the run thread so far, copied by a continuation';
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS end_reason LowCardinality(String) DEFAULT ''
    COMMENT 'Empty for an answer, step_budget or repeated_call for a forced final answer';
