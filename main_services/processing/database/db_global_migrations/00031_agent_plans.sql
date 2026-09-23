-- Plan tree storage for the deep-research plan-and-review workflow: a versioned
-- whole-tree snapshot per plan, the run state a section runtime schedules against, the
-- prompts/reports/reviews each plan role writes, and the append-only decision rows the
-- website backend writes for approve/reject/cancel.
--
-- Every table has one writer. A body larger than the inline limit goes to
-- chat_artifacts through write_required with kind agent_plan_document, and a plan
-- document row keeps the id, size and digest and never the object key.
--
-- Every read uses FINAL and the full owner prefix of the sort key:
--   SELECT ... FROM agent_plan_snapshots FINAL WHERE username = ? AND session_id = ? AND plan_id = ? ORDER BY version DESC LIMIT 1
--   SELECT ... FROM agent_plan_runs FINAL WHERE username = ? AND session_id = ? AND run_id = ?
--   SELECT ... FROM agent_plan_documents FINAL WHERE username = ? AND session_id = ? AND run_id = ? AND document_id = ?
--   SELECT ... FROM agent_plan_decisions FINAL WHERE username = ? AND session_id = ? AND run_id = ? ORDER BY created_at, decision_id
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS agent_plan_snapshots
(
    plan_id UUID COMMENT 'Immutable plan id',
    username LowCardinality(String) COMMENT 'Owner',
    session_id String COMMENT 'Owning chat session',
    version UInt64 COMMENT 'Snapshot version, one more than the previous',
    nodes_json String COMMENT 'Canonical whole-tree JSON',
    checksum FixedString(64) COMMENT 'SHA-256 of nodes_json',
    idempotency_key UUID COMMENT 'Mutation retry key',
    created_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (username, session_id, plan_id, version)
COMMENT 'Versioned plan trees. Writer: the plan tools in agent_todo_server';

CREATE TABLE IF NOT EXISTS agent_plan_runs
(
    run_id UUID COMMENT 'Run id, carried in the workflow input and in every plan header',
    plan_id UUID COMMENT 'The plan this run reviews and executes',
    username LowCardinality(String) COMMENT 'Owner',
    session_id String COMMENT 'Owning chat session',
    start_seq UInt32 COMMENT 'Seq of the first segment. The workflow id is plan-{session_id}-{start_seq}',
    state LowCardinality(String) COMMENT 'Run state',
    reviewed_version UInt64 COMMENT 'Version the user reviews, 0 before the first review',
    approved_version UInt64 COMMENT 'Frozen version, 0 before approval',
    review_round UInt64 COMMENT 'Completed user rejections',
    sections_json String COMMENT 'Section phases, attempts and defect classes',
    state_version UInt64 COMMENT 'Monotonic version the workflow assigns',
    updated_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(state_version)
ORDER BY (username, session_id, run_id)
COMMENT 'Plan run state. Writer: PlanReviewWorkflow';

CREATE TABLE IF NOT EXISTS agent_plan_documents
(
    document_id UUID COMMENT 'uuid5 of run, node, role, attempt and kind',
    run_id UUID COMMENT 'Owning run',
    node_id UUID COMMENT 'Section head node. The root node id for a root section and for the final report',
    username LowCardinality(String) COMMENT 'Owner',
    session_id String COMMENT 'Owning chat session',
    role LowCardinality(String) COMMENT 'planner, organizer, executor or reviewer',
    kind LowCardinality(String) COMMENT 'orientation, prompt, report, review or final',
    attempt UInt8 COMMENT 'Section attempt, 0 for the original execution',
    body_inline String COMMENT 'Body when within the inline limit',
    artifact_id String COMMENT 'chat_artifacts id when the body is larger',
    body_bytes UInt64 COMMENT 'Complete body size',
    body_sha256 FixedString(64) COMMENT 'Complete body digest',
    created_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (username, session_id, run_id, document_id)
COMMENT 'Plan prompts, reports and reviews. Writer: the plan workflows';

CREATE TABLE IF NOT EXISTS agent_plan_decisions
(
    decision_id UUID COMMENT 'Browser idempotency key',
    run_id UUID COMMENT 'Target run',
    username LowCardinality(String) COMMENT 'Owner',
    session_id String COMMENT 'Owning chat session',
    action LowCardinality(String) COMMENT 'approve, reject or cancel',
    reviewed_version UInt64 COMMENT 'Version the user saw',
    comment String COMMENT 'Rejection comment, at most 10000 characters',
    outcome LowCardinality(String) COMMENT 'The typed outcome returned to the browser',
    start_seq UInt32 COMMENT 'Transcript seq reserved for the segment this decision opens',
    turn_uuid String COMMENT 'Turn uuid of that segment, empty when none opens',
    created_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (username, session_id, run_id, decision_id)
COMMENT 'Plan decisions. Writer: the website backend';

ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS plan_reference_json String DEFAULT ''
    COMMENT 'Plan card reference, empty for every other row';

-- The two columns a required (non-best-effort) artifact write needs. Empty on every row
-- the existing best-effort artifacts.write produces, so an old reader that does not know
-- these columns still sees the rows it always saw.
ALTER TABLE chat_artifacts ADD COLUMN IF NOT EXISTS body_sha256 String DEFAULT ''
    COMMENT 'SHA-256 of the body for a required write, empty for a best-effort write';
ALTER TABLE chat_artifacts ADD COLUMN IF NOT EXISTS idempotency_key String DEFAULT ''
    COMMENT 'Retry key for a required write, empty for a best-effort write';
