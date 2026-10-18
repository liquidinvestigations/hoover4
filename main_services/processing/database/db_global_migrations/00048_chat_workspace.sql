-- The workspace files of chat sessions: the reports and other text files that an agent writes.
--
-- One writer: the session workflow WorkspaceWriter (tasks/P_workspace/workflows.py). The
-- session tool server forwards each write and patch of the agent to it, and it handles the
-- commands of one session in order. It prepares each command against the current file,
-- validates the candidate, and then commits the version row and the receipt. A retry of the
-- commit writes the same rows again, so one operation never allocates a second version.
--
-- chat_workspace_files      one immutable row per file version. Readers use FINAL, skip
--                           rows with is_deleted = 1, and take the highest version of a
--                           file. When a session is deleted, each of its versions gets a
--                           tombstone row with is_deleted = 1 and a later created_at.
-- chat_workspace_receipts   the result of each operation, keyed by the operation id that the
--                           worker gives the tool call. A repeated operation returns it.
--
-- The website reads both tables for the workspace view and for the pinned report of an
-- answer, and writes the tombstones when a session is deleted. Neither table expires.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS chat_workspace_files
(
    username String COMMENT 'Owner of the session',
    session_id String COMMENT 'Chat session id',
    name String COMMENT 'File name, see database/chat_workspace.py valid_name',
    version UInt32 COMMENT 'Version of the file, from 1. A version is never written twice with other content',
    parent_version UInt32 COMMENT 'The version that the operation changed, 0 for a new file',
    run_id String COMMENT 'The agent run of the operation. One chat turn is one run',
    operation_id String COMMENT 'Idempotency key of the tool call that wrote the version',
    operation LowCardinality(String) COMMENT 'write or patch',
    content String COMMENT 'The whole text of the version',
    citations_json String COMMENT 'The resolved citation handles of the content, as a JSON list',
    patch_json String COMMENT 'The patch arguments and the matching strategy, empty for a write',
    created_at DateTime64(3) COMMENT 'Time of the commit',
    is_deleted UInt8 DEFAULT 0 COMMENT '1 on the tombstone of a deleted session'
)
ENGINE = ReplacingMergeTree(created_at, is_deleted)
ORDER BY (username, session_id, name, version)
COMMENT 'Workspace file versions. Writer: WorkspaceWriter, and the website for tombstones';

CREATE TABLE IF NOT EXISTS chat_workspace_receipts
(
    username String COMMENT 'Owner of the session',
    session_id String COMMENT 'Chat session id',
    operation_id String COMMENT 'Idempotency key of the tool call',
    name String COMMENT 'The file that the operation named',
    version UInt32 COMMENT 'The version that the operation stored or found, 0 when it stored none',
    ok UInt8 COMMENT '1 when the operation succeeded',
    result_json String COMMENT 'The tool result that the agent reads',
    created_at DateTime64(3) COMMENT 'Write time'
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY (username, session_id, operation_id)
COMMENT 'Workspace operation receipts. Writer: WorkspaceWriter';
