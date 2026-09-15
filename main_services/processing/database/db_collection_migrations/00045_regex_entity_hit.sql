-- One row per (file, variant, segment, rule set, entity type), holding the segment's
-- deduplicated values rather than one row per occurrence. A row per occurrence scales
-- with corpus size times entity density, and density is unbounded per segment: a single
-- 165 KB segment produced 1 588 entities on real data.
--
-- The four value arrays are parallel and always the same length. Nothing in ClickHouse
-- enforces that, so the writer is the only place it can be true and a unit test asserts
-- it there.
--
-- rule_set_version is in the sort key for the same reason nlp_model is in entity_hit's:
-- two rule sets' results must coexist rather than replace one another, so that a bump
-- makes every segment eligible for a rescan without destroying what the previous version
-- found before the rescan runs.
CREATE TABLE IF NOT EXISTS regex_entity_hit
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, links hits to source files',
    file_hash String COMMENT 'Source file hash, references blobs.hash',
    extracted_by String COMMENT 'Text variant the scan read, the same storage key text_content uses',
    page_id UInt32 COMMENT 'Page number for paged formats, segment ordinal otherwise, never 0',
    rule_set_version UInt32 COMMENT 'Scanner rule set that produced these values',
    entity_type LowCardinality(String) COMMENT 'Scanner entity type: email, date, money, phone, bank_account, ...',
    entity_values Array(String) COMMENT 'Normalised deduplicated values, the facet key',
    entity_rule_ids Array(String) COMMENT 'Parallel to entity_values: the rule behind each value',
    entity_value_json Array(String) COMMENT 'Parallel to entity_values: the canonical value object the explainer is posted back',
    entity_counts Array(UInt32) COMMENT 'Parallel to entity_values: occurrences in this segment, orders the viewer',
    entity_texts Array(String) COMMENT 'Parallel to entity_values: surface form, which a normalised value frequently is not',
    updated_at DateTime DEFAULT now() COMMENT 'Version column'
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (collection_dataset, file_hash, extracted_by, page_id, rule_set_version, entity_type)
COMMENT 'Regex entity scanner output, aggregated per segment.';
