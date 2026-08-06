# P3 - Parse Files

This stage parses downloaded files by type and writes structured content and metadata to ClickHouse. It uses Temporal workflows to route files to specialized handlers.

## Key Responsibilities

- Detect MIME types using GNU `file`, Tika/Extractous, and Magika.
- Parse archives, emails, PDFs, images, audio, video, and raw text.
- Run OCR for images and extract text for indexing.
- Create temporary directories for extracted content and scan them as containers.

## Entry Points

- Workflow: `ParseSingleFile` in `workflows.py`
- Activities: `parse_*` modules (e.g., `parse_pdf.py`, `parse_email.py`, `parse_image.py`)
- Helpers: `parse_common.py` for text page/segment writing and error recording

## How text is stored — `page_id` is a page number

`text_content.page_id` is a **1-based page number** for paged formats and a **1-based
~256 KB segment ordinal** for everything else. It is never 0. This changed in Part 2
Phase 0; before it, everything was a 32 MB segment ordinal and a whole PDF was usually
one row.

- `insert_text_pages(...)` is the paged path. Callers pass the real page numbers.
  **Call it once per `(file, extracted_by)` with the complete page list** — it deletes
  rows above the highest page it writes, which is what stops a shorter re-OCR from
  leaving the previous run's tail behind, and which also means a second call for the
  same variant would delete the first call's pages.
- `insert_text_chunks(...)` is the unpaged path: it segments a blob at
  `DEFAULT_TEXT_SEGMENT_BYTES` and numbers the segments from 1.
- `split_text_segments(...)` segments without inserting, for callers assembling one page
  sequence from several sources (`parse_email.py` and its MIME parts).

PDF text comes from a single `pdftotext` call split on the form feed it writes after
every page, so per-page storage costs no extra subprocesses. The label is
`extracted_by = 'pdftotext'` (it was `'qpdf'`, which named the wrong tool).

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
