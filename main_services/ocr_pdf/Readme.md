# ocr_pdf: searchable PDFs over HTTP

Takes a PDF, renders every page, sends each render to the **existing** OCR tier, and
writes back a PDF that looks identical and selects, copies and searches like text. It
owns no OCR engine and no language data: `main_services/ocr_tesseract` does, and adding a
language here would be false about what the stack can read.

## Contract

```
GET  /health   -> {"status", "engines": {"tesseract": true, "easyocr": false},
                   "renderer", "bucket", "derived_prefix", "max_pages", ...}
POST /ocr-pdf  {"source_key"|"pdf_b64", "dest_key", "engine", "languages", "dpi"}
               -> {"page_count", "pages_with_text", "size_bytes", "blob_hash",
                   "engine", "languages", "dest_key", "run_time_ms"}
```

* **`source_key` or `pdf_b64`.** Blobs above the small-file threshold live in the object store and
  are read by key; the ones below it live in `blob_values` in ClickHouse and have no
  object at all, so the caller sends those inline. Exactly one is required.
* **`dest_key` must start with `derived/`**. See below. The service writes the object and
  returns its hash; it writes **no** database row. `pdf_ocr_results` is the caller's, and
  the ordering is deliberate: bytes before row.
* **`languages` is part of the storage key**, not a hint. An empty value is a 400.
* **`engine` not configured is a 501, not a 503.** "This deployment has no EasyOCR" is a
  fact the caller must not retry; "the OCR tier did not answer" is one it must. Collapsing
  them into one status is how a disabled engine turns into an infinite retry loop.

## The derived-PDF trap

The output is a new PDF. If the ingest walker could see it, it would be ingested, OCR'd
and produce another PDF without end, burning OCR time on each lap. Three guards:

1. **`validate_dest_key`** refuses any key not under `derived/`, plus traversal and
   directory-shaped keys, *before* any work happens. Pinned by tests.
2. **No `blobs` row and no `vfs_files` row** are ever written here. `pdf_ocr_results` is
   the sole index of a derived PDF's existence, which also means deleting a row without
   deleting the object orphans it permanently, and the purge order in the apply job
   (`change_ocr_languages`) is objects-then-rows for that reason.
3. **`verify-stack.sh`** asserts that no `blobs` row references `derived/`, which covers
   this writer and the chat-artifact one with the same query.

## Why it is a service

* **Rasterising is a native-library job.** The worker deliberately shells out to `qpdf`
  and `pdftotext` rather than linking a PDF library into the process that also runs
  Temporal activities, archive extraction and ClickHouse writes. pypdfium2 and Pillow
  would undo that.
* **The page loop is unbounded work over one input.** A 500-page scan is 500 OCR calls.
  The bounded pool and the load shedding belong on the thing making them, not on each
  caller.

## The text layer

Each page becomes a JPEG at `dpi` (default 200) placed at the page's original size in
points, with the OCR words drawn over it in **text render mode 3**, laid out, measured,
selectable, and painting nothing.

Two details that commonly go wrong in a way that is impossible to see afterwards:

* **The origin flips.** The raster's boxes are top-left, the PDF's are bottom-left, so
  the baseline is `page_height - top - height`, scaled.
* **Each word is horizontally scaled to its own box.** Helvetica's metrics have nothing
  to do with the scanned glyphs, so without `setHorizScale` a selection drifts further
  from the ink with every word on the line.

Page size in points is carried through unchanged. The viewer's page jump and the stored
`text_content.page_id` rows are matched against this file, so a page that changes size or
order is a defect even though the PDF still opens.

## Operational notes

* **Backpressure is passed up, not absorbed.** A `503` from the OCR tier becomes a `503`
  here, with the tier's own `Retry-After`. The caller maps it to a retryable Temporal
  error, so a busy OCR tier slows the pipeline instead of filling `processing_errors`.
* `OCR_PDF_MAX_PAGES` (2000) and `OCR_PDF_MAX_INPUT_BYTES` (512 MB) bound one request. A
  bomb-shaped PDF is a real corpus artefact, not a hypothetical.
* `/health` reports which engines are **configured**, not which are reachable: an
  unreachable tier changes between two health checks, and reporting it here would make
  this service's health flap with someone else's.
* Run the tests with `.agents/skills/verifying-before-claiming/scripts/pytest-ocr-pdf.sh`, which
  runs `docker exec hoover4-ocr-pdf python -m pytest tests/ -q`.
