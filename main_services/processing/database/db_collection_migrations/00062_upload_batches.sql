-- Upload batches and their files.
--
-- A batch is one upload by one person into one folder of the upload dataset of this
-- collection. Only the upload routes of the website and the ingest_upload operation may
-- write these tables. After dispatch the operation owns the processing states, and the
-- website must not overwrite them.
--
-- Both tables are ReplacingMergeTree tables versioned by row_version. The writer of a
-- record holds its lock, reads the stored version, and writes a version above it, so the
-- wall clock does not decide which write is current. Readers use FINAL.
--
-- History stays readable when the dataset stops accepting uploads, when its mount goes,
-- and when the dataset is deleted. A dataset purge deletes the rows of every collection
-- table that has a collection_dataset column, so the dataset column here is upload_dataset.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
CREATE TABLE IF NOT EXISTS upload_batches
(
    batch_id String COMMENT 'Random 32-character hex id, a lookup key only',
    upload_dataset LowCardinality(String) COMMENT 'The collection_dataset id of the upload dataset',
    folder String COMMENT 'Destination folder, in the path form of vfs_directories',
    username LowCardinality(String) COMMENT 'The uploader who created the batch',
    manifest_digest String COMMENT 'Digest of the immutable destination and ordered manifest',
    request_id String COMMENT 'The client request id of begin, so a repeated begin names the same batch',
    state LowCardinality(String) COMMENT 'uploading, committing, queued, ingesting, processing, completed, completed_with_errors, failed, cancelled',
    file_count UInt32 COMMENT 'Number of files in the manifest',
    byte_count UInt64 COMMENT 'Sum of the declared file sizes in bytes',
    op_id String DEFAULT '' COMMENT 'The ingest_upload operation that took the batch',
    error String DEFAULT '' COMMENT 'At most 2000 characters',
    created_at DateTime64(3) COMMENT 'Time of begin',
    last_write_at DateTime64(3) COMMENT 'Durable transfer activity time for the abandon sweep, mirrored from the journal at a bounded interval',
    committed_at DateTime64(3) DEFAULT 0 COMMENT '0 until commit',
    finished_at DateTime64(3) DEFAULT 0 COMMENT '0 until a terminal state',
    row_version UInt64 COMMENT 'Version of the record, above the version of the row it replaces. The writer assigns it under the batch lock'
)
ENGINE = ReplacingMergeTree(row_version)
ORDER BY (upload_dataset, batch_id)
COMMENT 'One row for each upload batch, the highest row_version wins';

CREATE TABLE IF NOT EXISTS upload_files
(
    batch_id String COMMENT 'The batch of the file',
    file_no UInt32 COMMENT '0-based position in the manifest',
    path String COMMENT 'Destination path, in the path form of vfs_files, for example /press/2026/a.pdf',
    size_bytes UInt64 COMMENT 'Size that the manifest declared',
    content_digest String DEFAULT '' COMMENT 'Expected file digest when resume verification requires it',
    placement_token String DEFAULT '' COMMENT 'Identity of the placement journal record',
    client_mtime DateTime COMMENT 'lastModified of the browser File, or the begin time when absent',
    state LowCardinality(String) COMMENT 'pending, staged, placed, ingested, rejected, not_sent',
    file_hash String DEFAULT '' COMMENT 'Blob hash after ingestion',
    error String DEFAULT '' COMMENT 'At most 2000 characters',
    row_version UInt64 COMMENT 'Version of the record, above the version of the row it replaces. The writer assigns it under the batch lock'
)
ENGINE = ReplacingMergeTree(row_version)
ORDER BY (batch_id, file_no)
COMMENT 'The files of an upload batch, the highest row_version wins'
