# P3 - Parse Files

This stage parses downloaded files by type and writes structured content and metadata to ClickHouse. The group workflow `ProcessItemsBatched` of P2 routes the files of a group to stage activities, and each stage activity calls the per-file function of its stage for each of its files.

## Key Responsibilities

- Detect MIME types with GNU `file`, Magika, filename extensions, and content sniffs.
- Parse archives, emails, PDFs, images, audio, video, and raw text.
- Read tabular documents (CSV/TSV/PSV, XLSX/XLSM/XLTX, XLS/XLSB, ODS) into individual
  cells (`parse_table.py`), alongside the text extraction of the same file.
- Run OCR for images and extract text for indexing.
- Assemble a searchable PDF per engine for every PDF (`parse_ocr_pdf.py`), through the
  `hoover4-ocr-pdf` service.
- Create temporary directories for extracted content and scan them as containers.

## Entry Points

- Stage activities: one `*_batch` activity for each stage, in the module of its per-file
  function (see "Stage activities" below), and `scan_container_folders` in `member_scan.py`
- Runner: `batch_runner.py`, the shared loop of every stage activity
- Routing and error names: the pure functions of `workflows.py`
- Activities: `parse_*` modules (e.g., `parse_pdf.py`, `parse_email.py`, `parse_image.py`)
- OCR: `parse_ocr.py` (images -> `raw_ocr_results` + text) and `parse_ocr_pdf.py`
  (PDFs -> a derived searchable PDF + a `pdf_ocr_results` row)
- Tables: `parse_table.py` (cells -> `table_cells` + `table_documents`/`table_sheets`/
  `table_columns`), with the format list in `table_formats.py`, the readers in
  `table_readers.py` and the delimited-text sniff in `sniff_table.py`
- Helpers: `parse_common.py` for text page/segment writing and error recording

The workflow Error helper requires one source execution id for each result. It builds the
id from the workflow run, call site and source schedule ordinal. Replay uses the same id.
A later source schedule gets another id.
Direct OCR, OCR-PDF, table and Office XML writers identify Errors by workflow run,
activity id, attempt, task name and document hash. Recorder retries keep that identity.

## How text is stored: `page_id` is a page number

`text_content.page_id` is a **1-based page number** for paged formats and a **1-based
~256 KB segment ordinal** for everything else. It is never 0.

- `insert_text_pages(...)` is the paged path. Callers pass the real page numbers.
  **Call it once per `(file, extracted_by)` with the complete page list**. A successful
  call replaces that source's page identities. It removes prior pages absent from the
  result, including blank pages inside the retained range. Each stored row carries
  `text_bytes` (`len(body.encode("utf-8"))`) so size queries never scan `text`.
- `insert_text_chunks(...)` is the unpaged path: it segments a blob at
  `DEFAULT_TEXT_SEGMENT_BYTES` and numbers the segments from 1. Successful empty text
  clears prior segments.
- `split_text_segments(...)` segments without inserting, for callers assembling one page
  sequence from several sources (`parse_email.py` and its MIME parts).

Most extractors omit text shorter than two characters. Email bodies retain one-character
text. The email parser selects plain text, HTML, RTF, or legacy rich text as its body.
It stores the selected body as `email_parser`. It stores converted alternatives as
`email_html`, `email_rtf`, and `email_richtext`.
Opaque CMS signed messages supply their encapsulated MIME body when OpenSSL can read it.
The parser also reads clear-signed PGP bodies and removes their signature block.
It does not verify signatures or decrypt encrypted messages.
Signed decoding has a 16 MiB input limit, a 10-second process limit, and a four-layer limit.
A successful empty extraction clears old pages for each key.
An extraction failure leaves previously stored text in place. Every reader treats the
body variant as optional. The viewer can still show the headers and other sources.
Replacement inserts wait for ClickHouse visibility before obsolete pages are deleted.
The deletion waits for completion. The first insertion stays asynchronous.
Date resolution flushes pending parse inserts after all parse groups finish.
P4 and P6 read text after this stage boundary.
The ClickHouse flush acts on the server's whole async insert queue.
If it fails, date resolution fails before it reads parser output.

PDF text comes from a single `pdftotext` call split on the form feed it writes after
every page, so per-page storage costs no extra subprocesses. The label is
`extracted_by = 'pdftotext'` (it was `'qpdf'`, which named the wrong tool).

Binary Word files with a `WordDocument` OLE stream get a `binary_word` text source.
LibreOffice converts at most 32 MiB of input to DOCX in a separate process.
The Office XML reader then reads at most 128 MiB of output and maps declared Symbol font codes.
The conversion has a 45-second limit and stops with its worker.
Tika still runs and keeps the `extractous` source identity.

qpdf exit status 3 returns usable output with warnings. Page-count parsing accepts it and
logs the warning with the file hash. Metadata JSON parsing accepts it. A page-count error
records after one attempt.

## Searchable PDFs are a derived object, not a document

`parse_ocr_pdf.py` produces a *file*, not rows of text: a PDF with the page images and an
invisible OCR text layer, written to Garage under `derived/ocr-pdf/…` by the
`hoover4-ocr-pdf` service. It gets **no `blobs` row and no `vfs_files` row**, the only
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
not an object. A message repeats headers: `Received:` five to ten times on a normal
message, and it is the delivery path, and a name-keyed object keeps only the last of them.
Readers go through `parse_email.header_pairs_from_json`, which also accepts the older
object shape, because a document only gets the list shape when it is re-parsed.

Parsing uses type-based routing derived from detector results. Archives, PDFs, emails, and videos can spawn child scans by writing extracted content to temp directories and invoking P0 workflows with container hashes. OCR runs on a dedicated queue (`processing-ocr-queue`) and Tika runs on `processing-tika-queue` to isolate heavy dependencies.

## Mail containers

PST, OST, MSG, mbox, and TNEF files use the archive extraction stage.
The member scanner assigns VFS paths and blob identities to the extracted files.
PST, OST, and mbox files receive no Tika request.
Other mail containers receive metadata requests only.
The extracted members carry their text.

`mail_containers.py` reads PST and OST with pypff, MSG with extract-msg, and TNEF with tnefparse.
It reads mbox separators with support for `Content-Length` and escaped `From` lines.
A child message keeps its `>From ` lines as stored, so its body is not read as a mailbox.
When pypff cannot expose an embedded PST message, `readpst` exports that child message.
The adapter writes mail items as EML and non-mail MAPI items as typed JSON.
It includes stable folder identifiers and folder names in member paths.
Generated MIME boundaries and child paths remain stable across retries.
Binary attachments retain their bytes, names, MIME types, and content IDs when the reader provides them.
The adapter marks RTF body parts as inline `text/rtf` with `X-Hoover-Body-Alternative: rtf`.

The mail reader runs in a child process group.
Cancellation and timeout stop that group and remove the partial directory.
The stage scans readable members before it records a `MailPartialFailure` for damaged members.
An unreadable container with no members records an Error.

Apple `.emlx` parsing uses the declared byte count and excludes the trailing property list.
Detached `.emlxpart` files remain separate source files.
The current VFS member contract does not link a detached part to its `.emlx` placeholder.
The email parser does not create a child for a detached Apple attachment with no inline bytes.
Nested `message/rfc822` parts become child EML files. MIME part paths keep duplicate names
distinct. Named text attachments and detached signatures do not enter the parent body.

Magika is constructed once for each worker process.
The local detectors select routes before Tika runs.
The detectors receive up to four stored basenames with distinct extensions.
Each name list occupies at most 120 serialized JSON bytes.
The names retain extensions within that limit.

Content sniffs identify cards, SQLite files, SpreadsheetML, and spreadsheet markup before the email and delimited-text sniffs.
An authoritative card takes only the text route.
Other authoritative types take only the table route.
Filename and detector aliases cannot supply an authoritative type.
A spreadsheet filename does not select a binary reader when the primary file type is text.
A delimited type from Magika alone cannot select the table route.

## Tika server parsing

`tika_text_batch` runs in stage 2 on the Tika queue.
The Tika server parses the outer document only.
Embedded document text needs a separate reader.
The text source identity remains `extractous`.

Mail containers, email routes, archive routes, cards, calendars, and raster images receive metadata requests only.
PST, OST, and mbox files receive no Tika request.
Other files receive one text and metadata request.
The client streams the input file.
A stored filename provides a detection hint when available.

The client reads the document type from the JSON metadata and removes MIME parameters.
It writes this type under the `tika` detector identity after parsing.
This result contributes to canonical type resolution.
It does not change the selected routes.

A parse failure permits one additional request with the first local `file` type when the types differ.
An HTTP 500 response permits one additional request.
An HTTP 429 response requests a busy delay.
An HTTP 503 response reports a service failure.
The client read timeout includes parser time, queue time, and transfer time below the file try budget.

The server output limit is 20,000,000 characters.
A write-limit exception keeps the truncated text and its metadata flag.
Other Java exceptions remain in metadata and produce a document failure.
The binary Word reader stores its independent text before the Tika request.

Stage 3 removes a Tika document failure when another content reader succeeded for the same file.
The covering readers include archive extraction and image OCR.
Busy and connection failures remain visible.
The Tika task outcome and stored Java exception remain available.

New parser output skips the ClickHouse async-insert wait
(`insert_arrow_idempotent`). Source replacement waits for the text insert and its
scoped deletion. Date resolution flushes pending parse output before dependent reads.
The scan tables P0 writes stay durable. Nothing rescans a disk, so a lost `blobs` row
is a file that is never planned. See
[`../../database/Readme.md`](../../database/Readme.md).

## Usage

- Executed as part of P2 plan execution.
- Ensure required external tools are present: `file`, `7z`, `qpdf`, `ffprobe`, `ffmpeg`, and Tika.

## Navigation

- [Go Back](../Readme.md)
- [P2 - Execute Plan](../P2_execute_plan/Readme.md)
- [P4 - Extract Entities](../P4_extract_entities/Readme.md)
- [P6 - Index Data](../P6_index_data/Readme.md)

## Detection is parallel, contradictory, and resolved later

Four local detectors run in `detect_mime_all` and write their distinct `file_types` rows in one insert.
They can disagree.
The group selects routes from their combined results.
Each failed detector reports its own error.

Tika runs after route selection on its separate queue.
Its document type adds a fifth detector row when metadata contains a type.
Canonical type resolution runs after all parsers finish.

`content_sniff` is the one that reads content nothing else can name. `sniff_table.py`
recognises delimited text the same way, and runs only after `sniff_email` has declined:
an RFC 822 header block is a rectangular two-column table to any sniff that accepts `:`
as a delimiter, so `:` is excluded from the candidate set permanently and a message the
email sniff accepted is never offered to the table sniff at all.
`tests/integration/test_table_sniff_corpus.py` is the measurement that keeps both rules
accurate. Zero acceptances across the 21 291 messages of `enron-kaminski-v`.

`sniff_email.py`
recognises an RFC 822 message from its header block, which is the only way to classify an
extension-less maildir: every other detector calls those files `text/plain`. It also
strips Apple Mail's `.emlx` byte-count prefix and a leading BOM before the message is
parsed, and it carries two rules libmagic still gets wrong (a PST named only in the
human-readable output, and a legacy Excel workbook reported as a generic OLE container).
The sniff runs behind a cheap gate, so it never touches a file another detector has
confidently named.

The disagreement is resolved once, at the end, by `resolve_canonical_file_type` in
`P6_index_data`. That is where a document gets the single type the search index and the
filter pane use. Nothing here picks a winner.

## Stage activities and the batch runner

The group workflow runs one activity for each stage over the files of that stage. Each
stage activity calls `run_batch` in `batch_runner.py`, with a step that calls the existing
per-file function for one file. `run_batch` returns one `FileResult` for each file, in
input order. The rows of each file carry the per-file function name.

| stage activity | per-file function | queue | Error name of a failed file |
|---|---|---|---|
| `detect_mime_batch` | `detect_mime_all` | common | `detector_error_<name>` for each detector |
| `tika_text_batch` | `run_tika_and_store` | Tika | `tika_text_batch` |
| `extract_plaintext_batch` | `extract_plaintext_chunks` | common | the same |
| `parse_office_xml_batch` | `parse_office_xml_and_store` | common | the same |
| `parse_table_batch` | `parse_table_and_store` | common | the same |
| `parse_image_metadata_batch` | `parse_image_metadata_and_store` | common | the same |
| `run_ocr_batch` | `run_ocr_and_store`, once for each engine | OCR | `run_ocr_and_store[<engine>]` |
| `parse_audio_metadata_batch` | `parse_audio_metadata_and_store` | common | the same |
| `parse_email_headers_batch` | `parse_email_extract_text_headers` | common | `email_scan` |
| `extract_email_attachments_batch` | `extract_email_attachments_to_temp` | common | `email_scan` |
| `extract_archive_batch` | `extract_archive_to_temp`, then `record_archive_container` | common | `archive_scan` |
| `pdf_metadata_batch` | `pdf_get_metadata_and_store` | common | `pdf_process` |
| `run_ocr_pdf_batch` | `run_ocr_pdf_and_store`, once for each engine | OCR | `run_ocr_pdf_and_store[<engine>]` |
| `pdf_extract_batch` | `pdf_small_extract_text_and_images` or `pdf_large_split_to_chunks`, then `record_archive_container` | common | `pdf_process` |
| `video_batch` | `video_ffprobe_and_store`, `video_extract_frames_and_subtitles`, then `record_archive_container` | common | `video_process` |
| `scan_container_folders` | `scan_folder_tree` for each folder, then `cleanup_temp_dir` | common | the Error name of the chain that extracted the folder |

The value of each extraction stage (`extract_email_attachments_batch`,
`extract_archive_batch`, `pdf_extract_batch` and `video_batch`) is the dictionary of the
per-file call, with `member_count` added. `member_count` is the number of files that the
extraction wrote into `out_dir`, at all levels. `scan_container_folders` uses it only for
time limits. `member_scan_seconds` gives one try of a folder the budget of the source
file plus 6 h for each started block of 500 members, and at least 6 h.
`plan_folder_ranges` divides the scan of a folder into ranges, and it reads the folder
listing. `pdf_extract_batch` takes the small path when the PDF is below
`PDF_SMALL_BYTES` (64 MiB) or below `PDF_SMALL_PAGES` (1,000 pages). It takes the large
path only when the PDF reaches both limits.

The runner catches the failure of each file. A try that raises puts the file on a wait
list with the backoff of the default Temporal retry policy (1, 2, 4 and 8 s), and the
runner goes on with the next file. A non-retryable error, or the fifth try, gives the file
a failed result. A try has a time limit equal to the file's budget. After that limit,
`send_heartbeat` drops every heartbeat of the attempt, and the server ends the attempt.

Every heartbeat of a stage activity carries the batch detail first. The next attempt
restores the finished files from it and does not run them again. A file that is in
progress when 2 attempts end gets a failed result of type `StageAttemptLost`. A stage
activity has no attempt limit, and the runner fails it with `StageNoProgress` after 5
consecutive attempts that finish no new file.

## A container that extracted nothing is not scanned

`extract_email_attachments_to_temp` and `extract_archive_to_temp` both return how many
files they actually wrote, and both remove the temp directory themselves when that count
is zero. The group then gives the member scan no folder for that file.

Most messages in a mail corpus carry no attachment, so most email extractions write
nothing. The member scan of a folder costs one `plan_folder_ranges` call and one
`scan_folder_range` call, also when the folder is empty. The group skips these calls for
each email or archive extraction that wrote no file.

## A tabular document is read twice: as text, and as a grid

A `.xlsx` gets its office-XML flattening, its Tika text **and** `parse_table_and_store`.
Nothing is replaced: a search for a value inside cell G4713 still finds the file through
the text path. What the table reader adds is structure, which columns exist, what type
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
the bytes of prose, of mail and of a log file. A single-column list is a text file and a
single-line file is a text file. Below the threshold, no manifest row is written. The
activity returns a skipped outcome and writes no `processing_errors` row.

The collector keeps cells in memory until the minimum table shape is met.
A below-threshold input writes no cells or manifest.
A parsing manifest uses a waited insert before the first published cell batch.
Readers with a fallback write accepted batches to a temporary Arrow file with LZ4 compression.
A failed reader removes that file before the fallback runs.
A successful reader publishes the manifest and spooled batches.
The input and spool files stay in the plan directory.

HTML exports with spreadsheet names, Excel MHTML workbooks, and SpreadsheetML 2003 files use their own table readers.
The SpreadsheetML reader refuses document type declarations.
SQLite tables and views use a read-only connection with size, row, and time limits.
BLOB cells show a size marker in the grid.
SQLite also stores the `table_text` source, which omits binary cell values.
That source uses sheet and source row labels in segments of at most 256 KiB.
Its 20,000,000-character limit appears in the manifest.
The text and cells come from the same accepted read.

Every cap in `table_formats.py` that fires is recorded in three parallel arrays on the
manifest row (the limit's stable name, its maximum and the sheet it fired on), so the
grid can say what was dropped. A cap that is invisible in the UI reads as "this file has
300 columns", which is false about the corpus.

`python_calamine` is a Rust extension and fails by **panicking** rather than raising: a
`PanicException` derives from `BaseException` and an ordinary `except Exception` does not
see it. A workbook with one blank sheet (a pivot-table template, entirely ordinary) is
enough to trigger it. `parse_table.py` therefore catches `BaseException` and re-raises
only the interpreter's own, and the calamine reader skips a sheet with no used range.

## PDF images are children, and their text is indexed twice

`pdf_small_extract_text_and_images` extracts page images into a temp directory that is
then scanned as a container with the PDF as its `container_hash`, so every image is a
real member of the PDF: it gets a `vfs_files` row, its own parse in a later group, its own
MIME detection and its own OCR. The searchable-PDF assembly (`parse_ocr_pdf.py`) OCRs the
same pages again for its own rendition.

That double-indexing is intended. The image's own OCR text is what makes the image
findable as a document, and the PDF's rendition is what makes the page findable in the
PDF. They are the same characters under two `extracted_by` labels.

Both paths sit behind the same size gate: an image whose shorter edge is under
`MIN_OCR_IMAGE_PX` (`tasks/text_sources.py`) records `ocr_skipped_too_small` and is never
sent to an engine. Icons, bullets, rules and signature scraps are most of the images in a
PDF corpus and none of them carries text.
