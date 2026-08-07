-- `container_hash` is part of the sort key. Without it, two containers that hold the
-- same inner path (the `zip-in-multiple-locations` fixture is exactly this: two copies
-- of `parent.zip`, each with the same members) collapse into one ReplacingMergeTree row
-- and the second container loses its children. The dedupe read in P0's
-- `ingest_files_batch` must filter on `container_hash` for the same reason.
--
-- `mtime` is the historical modification time of the file as recorded by whatever
-- produced it, and `mtime_source` says how much that is worth:
--   'archive'     -- restored by the archive extractor (7z keeps stored timestamps),
--                    trusted as a historical date and indexed as one.
--   'untrusted'   -- an email attachment written to a temp file, so the mtime is the
--                    worker's clock. Recorded, but never indexed as a date.
--   'filesystem'  -- a top-level disk file, so clone/save time, not a document date.
--   ''            -- unknown.
CREATE TABLE IF NOT EXISTS vfs_files
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset that owns the file, joins to unique_uploads and file_types',
    container_hash String COMMENT 'Archive/email container hash if nested, references archives.archive_hash',
    path String COMMENT 'File path within the logical VFS (display + navigation)',
    hash String COMMENT 'Content hash for the file, references unique_uploads.hash',
    user_id String COMMENT 'Uploader or last modifier user id',
    file_size_bytes UInt64 COMMENT 'File size in bytes',
    mtime DateTime COMMENT 'Modification time as reported by the producer of this entry, 0 when unknown',
    mtime_source LowCardinality(String) COMMENT 'How mtime was obtained and how far it is trusted: archive, untrusted, filesystem, or empty for unknown'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, container_hash, path, hash)
COMMENT 'Virtual file system: files and directories. Logical VFS files (includes extracted files from archives/emails).';
