-- Folder disclosure uses the number of immediate folder and container children.
ALTER TABLE vfs_nodes ADD COLUMN IF NOT EXISTS subfolder_count UInt32 DEFAULT 0;
