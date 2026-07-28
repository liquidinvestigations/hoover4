CREATE TABLE IF NOT EXISTS pdfs_image
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, joins to pdfs and image table',
    pdf_hash String COMMENT 'Hash of the PDF file, references pdfs.pdf_hash',
    on_page UInt32 COMMENT 'Page number the image comes from',
    image_hash String COMMENT 'Hash of the extracted page image, references image.image_hash'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, pdf_hash, on_page)
COMMENT 'PDFs and associated images. Per-page images generated from PDFs.';
