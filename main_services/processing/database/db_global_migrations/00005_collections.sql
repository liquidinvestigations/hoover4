CREATE TABLE IF NOT EXISTS collections
(
    collectionname LowCardinality(String) COMMENT 'Unique collection identifier (slug)',
    fullname String DEFAULT '' COMMENT 'Human-readable collection display name',
    -- Access mode, stored as a UInt8 flag rather than an enum string so the
    -- ReplacingMergeTree row stays cheap and the website can read it without a mapping
    -- table. `restricted` means only users in a group holding a
    -- `collection_group_permissions` row may read it. `public` means every
    -- authenticated user may, with no group grant needed.
    is_public UInt8 DEFAULT 0 COMMENT 'Access mode: 0 = restricted (group grants only), 1 = public (all users)',
    created_at DateTime DEFAULT now(),
    updated_at DateTime DEFAULT now() COMMENT 'Version column for ReplacingMergeTree',
    is_deleted UInt8 DEFAULT 0 COMMENT 'Soft-delete tombstone'
)
ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (collectionname)
COMMENT 'Collections group datasets for permissioning and admin.';
