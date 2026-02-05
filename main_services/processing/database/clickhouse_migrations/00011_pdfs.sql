CREATE TABLE IF NOT EXISTS pdfs
(
    collection_dataset LowCardinality(String) COMMENT 'Dataset, references unique_uploads via pdf_hash',
    pdf_hash String COMMENT 'Hash of the PDF file',
    page_count UInt32 COMMENT 'Total number of pages',
    word_count UInt32 COMMENT 'Estimated word count for entire document',
    author_metadata String COMMENT 'Author and related metadata as string',
    date_created DateTime COMMENT 'ISO creation date from metadata if present'
)
ENGINE = ReplacingMergeTree
ORDER BY (collection_dataset, pdf_hash)
COMMENT 'PDFs and associated images. PDF documents and their global metadata.';
