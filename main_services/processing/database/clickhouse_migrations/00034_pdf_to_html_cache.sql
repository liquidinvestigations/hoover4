CREATE TABLE IF NOT EXISTS pdf_to_html_cache
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, references unique_uploads via pdf_hash',
    pdf_hash String COMMENT 'Hash of the PDF file',
    page_count UInt32 COMMENT 'Total number of pages',
    styles Array(String) COMMENT 'Styles of the PDF to HTML conversion',
    pages Array(String) COMMENT 'Pages of the PDF to HTML conversion',
    date_created DateTime DEFAULT now() COMMENT 'ISO creation date from metadata if present'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, pdf_hash)
COMMENT 'PDFs and associated images. PDF documents and their global metadata.';
