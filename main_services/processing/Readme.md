# Processing Module

This module implements ingestion (P0), plan computation (P1), plan execution (P2), and file parsing (P3).

## P3 Parse Files

The `ParseSingleFile` workflow receives a single file (already downloaded locally by P2) and:
- Computes a dynamic timeout based on file size
- Logs input arguments for traceability
- Fans out to activities based on coarse file type:
  - `archive`: `extract_archive_and_ingest` uses `7z` to extract into a temp dir under the system temp with prefix `hoover4_extract_<HASH>`, then ingests the extracted files into VFS using P0 batch ingestion and records archive metadata and children
  - `email`: `parse_email_extract_text_headers` parses `.eml` files, stores rows in `emails` and `email_headers`, and pushes plaintext parts into `text_content`
  - `text`: `extract_plaintext_chunks` reads the file in 16MB chunks and inserts into `text_content`
- Runs Tika for all files via the local server, stores cleaned metadata in `tika_metadata` and text content (if any) in `text_content`

## DB Tables

We currently populate:
- `archives`, `archive_children`
- `emails`, `email_headers`
- `text_content` (extracted_by indicates the text_source)
- `tika_metadata`

# TODO

- OCR pipeline for images and PDFs without extractable text (e.g. Tesseract or OCRmyPDF)
- PDF page image extraction and text: per-page parsing with word/char positions; store per-page images in `pdfs_image`
- Structured entity extraction (NER) and indexing into `entity_values` and `entity_hit`
- Rich document parsers for Office formats beyond Tika defaults (docx/xlsx/pptx-specific fallbacks)
- HTML sanitization and text extraction (selector-based, readability)
- Deduplication and re-processing policies (skip already processed hashes unless force)
- Throttling and backpressure for Tika requests; retries and circuit-breakers
- Content language detection and normalization
- Archive recursion policy (nested archives) with safeguards
- Error capture for all activities into `processing_errors`, including partial failures
- Metrics and tracing across workflows and activities

