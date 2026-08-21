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
--
-- A path has exactly one current row. `hash` is deliberately NOT in the sort key: with
-- it, a file whose content changed at the same path inserts a second row beside the old
-- one rather than replacing it, and the VFS then holds two versions of one path with no
-- way to say which is current. A path is unique within its container — including for
-- email attachments, which are written to a temp directory by filename, so a duplicate
-- name has already overwritten on disk before any row exists.
--
-- `is_deleted` is the deletion mark rather than a separate tombstone table, so a rescan
-- that finds a path gone writes one row and the reader needs no anti-join. The rescan is
-- authoritative for the paths under its root, which is what makes deletion detectable at
-- all.
CREATE TABLE IF NOT EXISTS vfs_files
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset that owns the file, joins to unique_uploads and file_types',
    container_hash String COMMENT 'Archive/email container hash if nested, references archives.archive_hash',
    path String COMMENT 'File path within the logical VFS (display + navigation)',
    hash String COMMENT 'Content hash for the file, references unique_uploads.hash',
    user_id String COMMENT 'Uploader or last modifier user id',
    file_size_bytes UInt64 COMMENT 'File size in bytes',
    mtime DateTime COMMENT 'Modification time as reported by the producer of this entry, 0 when unknown',
    mtime_source LowCardinality(String) COMMENT 'How mtime was obtained and how far it is trusted: archive, untrusted, filesystem, or empty for unknown',
    updated_at DateTime DEFAULT now() COMMENT 'Version column: the newest row for a path wins',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Deletion mark: the path was absent from the source on the last authoritative scan'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (collection_dataset, container_hash, path)
COMMENT 'Virtual file system: files and directories. Logical VFS files (includes extracted files from archives/emails).';
