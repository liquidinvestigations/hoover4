# P3 - Parse Files

This stage parses downloaded files by type and writes structured content and metadata to ClickHouse. It uses Temporal workflows to route files to specialized handlers.

## Key Responsibilities

- Detect MIME types using GNU `file`, Tika/Extractous, and Magika.
- Parse archives, emails, PDFs, images, audio, video, and raw text.
- Read tabular documents (CSV/TSV/PSV, XLSX/XLSM/XLTX, XLS/XLSB, ODS) into individual
  cells (`parse_table.py`), alongside the text extraction of the same file.
- Run OCR for images and extract text for indexing.
- Assemble a searchable PDF per engine for every PDF (`parse_ocr_pdf.py`), through the
  `hoover4-ocr-pdf` service.
- Create temporary directories for extracted content and scan them as containers.

## Entry Points

- Workflow: `ParseSingleFile` in `workflows.py`
- Activities: `parse_*` modules (e.g., `parse_pdf.py`, `parse_email.py`, `parse_image.py`)
- OCR: `parse_ocr.py` (images -> `raw_ocr_results` + text) and `parse_ocr_pdf.py`
  (PDFs -> a derived searchable PDF + a `pdf_ocr_results` row)
- Tables: `parse_table.py` (cells -> `table_cells` + `table_documents`/`table_sheets`/
  `table_columns`), with the format list in `table_formats.py`, the readers in
  `table_readers.py` and the delimited-text sniff in `sniff_table.py`
- Helpers: `parse_common.py` for text page/segment writing and error recording

## How text is stored — `page_id` is a page number

`text_content.page_id` is a **1-based page number** for paged formats and a **1-based
~256 KB segment ordinal** for everything else. It is never 0.

- `insert_text_pages(...)` is the paged path. Callers pass the real page numbers.
  **Call it once per `(file, extracted_by)` with the complete page list** — it deletes
  rows above the highest page it writes, which is what stops a shorter re-OCR from
  leaving the previous run's tail behind, and which also means a second call for the
  same variant would delete the first call's pages. Each stored row carries
  `text_bytes` (`len(body.encode("utf-8"))`) so size queries never scan `text`.
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

`email_headers.raw_headers_json` stores a **list of `[name, value]` pairs in header order**,
not an object. A message repeats headers — `Received:` five to ten times on a normal
message, and it is the delivery path — and a name-keyed object keeps only the last of them.
Readers go through `parse_email.header_pairs_from_json`, which also accepts the older
object shape, because a document only gets the list shape when it is re-parsed.

Parsing uses type-based routing derived from detector results. Archives, PDFs, emails, and videos can spawn child scans by writing extracted content to temp directories and invoking P0 workflows with container hashes. OCR runs on a dedicated queue (`processing-ocr-queue`) and Tika runs on `processing-tika-queue` to isolate heavy dependencies.

Magika is constructed once per worker process: building the detector is several times
the cost of `identify_path`, and every file paid that construction when it lived inside
the activity. Extractous still runs in a subprocess — a wedged native call cannot be
interrupted in-process — but the helpers are a pool of long-lived interpreters (sized to
the tika worker's activity slots) that read one JSON path per line and write one JSON
object back. A timeout kills that helper, raises a non-retryable `ApplicationError`, and
the next file gets a fresh one. Stderr is drained so a noisy child cannot fill a pipe
and stall.

`file_types`, `text_content` and `tika_metadata` inserts skip the ClickHouse async-insert
wait: those writers are re-runnable and a lost buffer converges on the next pass.

## Usage

- Executed as part of P2 plan execution.
- Ensure required external tools are present: `file`, `7z`, `qpdf`, `ffprobe`, `ffmpeg`, and Tika.

## Navigation

- [Go Back](../Readme.md)
- [P2 - Execute Plan](../P2_execute_plan/Readme.md)
- [P4 - Extract Entities](../P4_extract_entities/Readme.md)
- [P6 - Index Data](../P6_index_data/Readme.md)

## Detection is parallel, contradictory, and resolved later

Five detectors run on every file and each writes its own `file_types` row: `file`, Tika,
Magika, the filename (`extension`) and the content sniff (`content_sniff`). They are
allowed to disagree — processing is attempted on the union of what they say, which is how
a `.docx` gets its office text extracted out of a file libmagic calls a zip, and how a
mail file gets both its headers parsed and its body extracted as text.

`content_sniff` is the one that reads content nothing else can name. `sniff_table.py`
recognises delimited text the same way, and runs only after `sniff_email` has declined:
an RFC 822 header block is a rectangular two-column table to any sniff that accepts `:`
as a delimiter, so `:` is excluded from the candidate set permanently and a message the
email sniff accepted is never offered to the table sniff at all.
`tests/integration/test_table_sniff_corpus.py` is the measurement that keeps both rules
honest — zero acceptances across the 21 291 messages of `enron-kaminski-v`.

`sniff_email.py`
recognises an RFC 822 message from its header block, which is the only way to classify an
extension-less maildir: every other detector calls those files `text/plain`. It also
strips Apple Mail's `.emlx` byte-count prefix and a leading BOM before the message is
parsed, and it carries two rules libmagic still gets wrong (a PST named only in the
human-readable output, and a legacy Excel workbook reported as a generic OLE container).
The sniff runs behind a cheap gate, so it never touches a file another detector has
confidently named.

The disagreement is resolved once, at the end, by `resolve_canonical_file_type` in
`P6_index_data` — that is where a document gets the single type the search index and the
filter pane use. Nothing here picks a winner.

## A tabular document is read twice: as text, and as a grid

A `.xlsx` gets its office-XML flattening, its Tika text **and** `parse_table_and_store`.
Nothing is replaced: a search for a value inside cell G4713 still finds the file through
the text path. What the table reader adds is structure — which columns exist, what type
each one is, and a grid that can be sorted, filtered and paged without loading the
document.

Cells go into `table_cells`, keyed by **hash alone**, so one parse serves every dataset in
the collection that holds the same file. The per-dataset manifest is `table_documents`,
and it is what authorises a read: a hash with no manifest row for the requesting dataset
is a 404, because permissions here are resolved per `collection_dataset` and a hash is a
lookup key rather than a capability. `table_sheets` and `table_columns` carry the extents,
the headers and the per-column statistics.

The manifest row is written **before** the cells, which is the opposite of
`parse_ocr_pdf.py`'s object-before-row rule and is the mirrored reason: a cell with no
manifest row is invisible to the permission check and to `sweep_orphan_table_cells` alike.

Two rules decide whether something is a table at all, and the asymmetry is the point. A
binary spreadsheet is a table on the strength of its format, so one non-empty cell is
enough. Delimited text has to be at least 2 rows by 2 columns, because its bytes are also
the bytes of prose, of mail and of a log file — a single-column list is a text file and a
single-line file is a text file. Below the threshold no manifest row is written and the
outcome is recorded as `table_not_a_table` in `processing_errors`, which means no
evidence, no `table` canonical type, no glyph and no grid.

Every cap in `table_formats.py` that fires is recorded in three parallel arrays on the
manifest row — the limit's stable name, its maximum and the sheet it fired on — so the
grid can say what was dropped. A cap that is invisible in the UI reads as "this file has
300 columns", which is a lie about the corpus.

`python_calamine` is a Rust extension and fails by **panicking** rather than raising: a
`PanicException` derives from `BaseException` and an ordinary `except Exception` does not
see it. A workbook with one blank sheet — a pivot-table template, entirely ordinary — is
enough to trigger it. `parse_table.py` therefore catches `BaseException` and re-raises
only the interpreter's own, and the calamine reader skips a sheet with no used range.

## PDF images are children, and their text is indexed twice

`pdf_small_extract_text_and_images` extracts page images into a temp directory that is
then scanned as a container with the PDF as its `container_hash`, so every image is a
real member of the PDF: it gets a `vfs_files` row, its own `ParseSingleFile` run, its own
MIME detection and its own OCR. The searchable-PDF assembly (`parse_ocr_pdf.py`) OCRs the
same pages again for its own rendition.

That double-indexing is intended. The image's own OCR text is what makes the image
findable as a document, and the PDF's rendition is what makes the page findable in the
PDF. They are the same characters under two `extracted_by` labels.

Both paths sit behind the same size gate: an image whose shorter edge is under
`MIN_OCR_IMAGE_PX` (`tasks/text_sources.py`) records `ocr_skipped_too_small` and is never
sent to an engine. Icons, bullets, rules and signature scraps are most of the images in a
PDF corpus and none of them carries text.
