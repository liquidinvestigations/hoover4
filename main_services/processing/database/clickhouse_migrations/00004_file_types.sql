CREATE TABLE IF NOT EXISTS file_types
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset id, joins to unique_uploads by (collection_dataset, hash)',
    hash String COMMENT 'File content hash, foreign key to unique_uploads.hash',
    extracted_by LowCardinality(String) COMMENT 'Source program that produced detection (e.g., file, tika)',
    mime_type Array(String) COMMENT 'Detected MIME types',
    mime_encoding Array(String) COMMENT 'Detected content encodings (e.g., gzip)',
    file_type Array(String) COMMENT 'High-level categories: image, pdf, text, email, archive, etc.',
    extensions Array(String) COMMENT 'File extensions observed (e.g., .pdf, .tar.gz)',
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, hash, extracted_by)
COMMENT 'File type detection (mime and coarse type). File content classification for routing to pipelines.';
