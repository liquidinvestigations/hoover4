-- `dataset_stats.error_count` counts distinct document and task pairs since this
-- migration. A task that failed in several runs wrote one `processing_errors` row for
-- each run, and the administration pages show it once.
ALTER TABLE dataset_stats COMMENT COLUMN error_count 'Distinct document and task pairs in processing_errors FINAL';
