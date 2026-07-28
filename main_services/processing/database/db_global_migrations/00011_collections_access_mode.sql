-- Collection-level access mode.
--
-- `restricted` (the default, and what every pre-existing collection keeps): only users
-- in a group that holds a `collection_group_permissions` row may read it.
-- `public`: every authenticated user may read it, no group grant needed.
--
-- Stored as a UInt8 flag rather than an enum string so the ReplacingMergeTree row stays
-- cheap and the website can read it without a mapping table. 0 = restricted, 1 = public.
ALTER TABLE collections
    ADD COLUMN IF NOT EXISTS is_public UInt8 DEFAULT 0
    COMMENT 'Access mode: 0 = restricted (group grants only), 1 = public (all users)';
