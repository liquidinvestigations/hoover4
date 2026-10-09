-- Per-dataset settings with a version of microsecond precision.
--
-- `setting_version_us` orders the rows of one key. A reader takes the complete row with
-- the largest version, so a value, its deletion flag and its version always come from one
-- write. A writer gives a new or changed value a version above the version of the row it
-- replaces, and writes nothing for an unchanged value, so an unchanged setting keeps its
-- version.
--
-- `updated_at` keeps its whole-second type, because existing writers send it in that
-- format. It is the write time and orders nothing.
--
-- `version_is_precise` is 0 for a row whose version was copied from the whole-second
-- `updated_at` of an earlier write. Such a version cannot order two events in one second.
-- An OCR error in the same second as such a setting therefore counts as written under it.
-- A backup restore keeps the flag, and fills it with 0 for a row of an older backup.
CREATE TABLE IF NOT EXISTS dataset_settings_versions
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset the setting belongs to',
    key                LowCardinality(String) COMMENT 'Setting name',
    value              String                 COMMENT 'Setting value, stored as string',
    updated_at         DateTime DEFAULT now() COMMENT 'Write time in whole seconds',
    is_deleted         UInt8 DEFAULT 0        COMMENT 'Soft-delete tombstone',
    setting_version_us UInt64 DEFAULT toUInt64(toUnixTimestamp64Micro(now64(6))) COMMENT 'Version in microseconds since the epoch, the ReplacingMergeTree version',
    version_is_precise UInt8 DEFAULT 1        COMMENT '0 when the version was copied from a whole-second updated_at'
)
ENGINE = ReplacingMergeTree(setting_version_us, is_deleted)
ORDER BY (collection_dataset, key)
COMMENT 'Per-dataset configuration editable from the dataset admin page.';

-- Every stored row is copied, tombstones included, with its whole-second time as its
-- version.
INSERT INTO dataset_settings_versions
    (collection_dataset, key, value, updated_at, is_deleted, setting_version_us, version_is_precise)
SELECT collection_dataset, key, value, updated_at, is_deleted,
       toUInt64(toUnixTimestamp(updated_at)) * 1000000, 0
FROM dataset_settings;

RENAME TABLE dataset_settings TO dataset_settings_whole_seconds,
             dataset_settings_versions TO dataset_settings;

DROP TABLE dataset_settings_whole_seconds
