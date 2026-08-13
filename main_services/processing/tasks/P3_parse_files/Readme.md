# P3 - Parse Files

This stage parses downloaded files by type and writes structured content and metadata to ClickHouse. It uses Temporal workflows to route files to specialized handlers.

## Key Responsibilities

- Detect MIME types using GNU `file`, Tika/Extractous, and Magika.
- Parse archives, emails, PDFs, images, audio, video, and raw text.
- Run OCR for images and extract text for indexing.
- Assemble a searchable PDF per engine for every PDF (`parse_ocr_pdf.py`), through the
  `hoover4-ocr-pdf` service.
- Create temporary directories for extracted content and scan them as containers.

## Entry Points

- Workflow: `ParseSingleFile` in `workflows.py`
- Activities: `parse_*` modules (e.g., `parse_pdf.py`, `parse_email.py`, `parse_image.py`)
- OCR: `parse_ocr.py` (images -> `raw_ocr_results` + text) and `parse_ocr_pdf.py`
  (PDFs -> a derived searchable PDF + a `pdf_ocr_results` row)
- Helpers: `parse_common.py` for text page/segment writing and error recording

## How text is stored — `page_id` is a page number

`text_content.page_id` is a **1-based page number** for paged formats and a **1-based
~256 KB segment ordinal** for everything else. It is never 0.

- `insert_text_pages(...)` is the paged path. Callers pass the real page numbers.
  **Call it once per `(file, extracted_by)` with the complete page list** — it deletes
  rows above the highest page it writes, which is what stops a shorter re-OCR from
  leaving the previous run's tail behind, and which also means a second call for the
  same variant would delete the first call's pages.
- `insert_text_chunks(...)` is the unpaged path: it segments a blob at
  `DEFAULT_TEXT_SEGMENT_BYTES` and numbers the segments from 1.
- `split_text_segments(...)` segments without inserting, for callers assembling one page
  sequence from several sources (`parse_email.py` and its MIME parts).

**A page whose stripped text is under two characters is not stored**, so a variant can be
absent rather than empty. Mail is where that shows: `parse_email.py` writes
`email_headers` whenever the file parses, but writes no `email_parser` row at all when the
message's whole `text/plain` part is a single `,` — which Enron's export produces by the
dozen — or when the only body part is HTML. Every reader must treat the variant as
optional; the document viewer carries an explicit "this email has no parsed body" flag for
exactly this, and NER falls back to the `raw_text` envelope for these files rather than
losing their entities (`tasks/text_sources.ner_reads_variant`).

PDF text comes from a single `pdftotext` call split on the form feed it writes after
every page, so per-page storage costs no extra subprocesses. The label is
`extracted_by = 'pdftotext'` (it was `'qpdf'`, which named the wrong tool).

## Searchable PDFs are a derived object, not a document

`parse_ocr_pdf.py` produces a *file*, not rows of text: a PDF with the page images and an
invisible OCR text layer, written to MinIO under `derived/ocr-pdf/…` by the
`hoover4-ocr-pdf` service. It gets **no `blobs` row and no `vfs_files` row** — the only
index of its existence is `pdf_ocr_results`.

That is not tidiness. If the ingest walker could see the object it would ingest it, OCR
it, and produce another one, forever, billing a full OCR pass per lap. The guards are the
`derived/` prefix (built by `ocr_pdf_client.derived_key`, re-checked by the service, which
refuses anything else), the absence of those two rows, and the `verify-stack.sh` assertion
that no `blobs` row references the prefix.

The object is written before the row, always: an object with no row is found by a prefix
scan, a row with no object is a broken link nothing can repair.

## Technical Details

Parsing uses type-based routing derived from detector results. Archives, PDFs, emails, and videos can spawn child scans by writing extracted content to temp directories and invoking P0 workflows with container hashes. OCR runs on a dedicated queue (`processing-ocr-queue`) and Tika runs on `processing-tika-queue` to isolate heavy dependencies.

## Usage

- Executed as part of P2 plan execution.
- Ensure required external tools are present: `file`, `7z`, `qpdf`, `ffprobe`, `ffmpeg`, and Tika.

## Navigation

- [Go Back](../Readme.md)
- [P2 - Execute Plan](../P2_execute_plan/Readme.md)
- [P4 - Extract Entities](../P4_extract_entities/Readme.md)
- [P6 - Index Data](../P6_index_data/Readme.md)
