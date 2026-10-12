-- The file count and byte count below each node, written by P6's `build_vfs_nodes` and
-- read by the website's folder listing and file location filter. -1 means not computed:
-- a row written before this migration keeps -1 until the next build of its dataset.
ALTER TABLE vfs_nodes ADD COLUMN IF NOT EXISTS subtree_file_count Int64 DEFAULT -1 COMMENT 'Files below this node, with archive and email members at every level, once per location. -1 until computed';
ALTER TABLE vfs_nodes ADD COLUMN IF NOT EXISTS subtree_size_bytes Int64 DEFAULT -1 COMMENT 'Stored bytes of the files below this node at its own container level. -1 until computed';
