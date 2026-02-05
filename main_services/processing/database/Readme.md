Datasets and ClickHouse tables (from diagram-3.xml)

- dataset: Registry of datasets. Referenced by all tables via `collection_dataset`.
- temp_user_uploads: Raw uploads before deduplication. Feeds `unique_uploads`.
- unique_uploads: Canonical files keyed by hash. Joined by `file_types`, `vfs_files`, processing pipelines.
- file_types: MIME and coarse type per file. Routes files to pipelines like PDFs, emails, images, archives, text.
- vfs_directories: Virtual directory tree for browsing; pairs with `vfs_files`.
- vfs_files: Logical files in the VFS, including extracted children; references `unique_uploads` and `archives`.
- archives: Archive containers (zip/rar/7z). Parent of `archive_children`.
- archive_children: Files extracted from archives; link to `unique_uploads`.
- emails: Email containers; referenced by `email_headers` and `text_content`.
- email_headers: Parsed email headers (subject, addresses, dates); child of `emails`.
- pdfs: PDF documents with global stats and metadata.
- pdfs_image: Images rendered from PDF pages; joins `pdfs` and `image`.
- image: Image metadata (dimensions, exif); used by OCR and PDFs.
- raw_ocr_results: Raw OCR outputs for images; prior to interpretation.
- text_content: Extracted text segments/pages for search and embeddings.
- entity_hit: Per-occurrence extracted entities with provenance; powers highlighting and stats.
- entity_values: De-duplicated canonical entities for discovery and analytics.
- document_labels: User-applied labels on documents for tagging and filters.
- processing_errors: Centralized processing error logs across tasks.


