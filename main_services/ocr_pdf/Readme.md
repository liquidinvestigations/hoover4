# The PDF builder adds searchable text to source pages.

The service runs PDFium in a child process for each admitted request.
It adds invisible OCR words to selected PDF pages and preserves their original content, geometry, and order.
It saves the complete output once.
The worker records the uploaded object after the response succeeds.
The service does not write source, document, or text rows.

## The request selects a source and local pages.

`POST /ocr-pdf` accepts these fields.

| Field | Contract |
|---|---|
| `bucket` | The destination key uses this bucket. Empty uses the configured default. |
| `source_bucket` | The source key uses this bucket. Empty uses the destination bucket. |
| `source_key` | The source PDF or image uses this object key. |
| `source_b64` | Small sources can use base64 input instead of an object key. |
| `pdf_b64` | Legacy callers can still send inline PDF input with this field. |
| `dest_key` | The destination must start with `derived/`. Parent-directory traversal is refused. |
| `mode` | `pdf` is the default. `image` uses stored OCR words without an OCR request. |
| `engine` | `tesseract` or `easyocr` identifies the stored variant. |
| `languages` | Nonempty, plus-separated language codes identify the stored variant. |
| `dpi` | PDF render resolution defaults to 200. The accepted range starts at 72 and ends at `OCR_PDF_MAX_DPI`. |
| `ocr_pages` | Local page numbers start at one. Omitted or null selects all pages. An empty list selects no pages. |
| `words` | Image mode accepts stored word boxes with `text`, `left`, `top`, `width`, and `height`. Coordinates use source-image pixels. |

`source_b64` takes precedence over `pdf_b64`, which takes precedence over `source_key`.
Selected page numbers must be unique integers within the source page range.
The builder processes them in source order.

```json
{
  "bucket": "collection-example",
  "source_key": "derived/pdf-parts/example/source/original/s1/101-200.pdf",
  "dest_key": "derived/ocr-pdf/example/source/tesseract+eng/s1/101-200.pdf",
  "engine": "tesseract",
  "languages": "eng",
  "mode": "pdf",
  "ocr_pages": [2, 7]
}
```

The response retains `page_count`, `pages_with_text`, `size_bytes`, `blob_hash`, `engine`, `languages`, `dest_key`, and `run_time_ms`.
`blob_hash` uses SHA3-256 over the uploaded PDF.
`pages_with_text` counts pages with at least one valid overlay word.
The response adds `pages`, with one entry per selected page, including successful empty OCR.

```json
{
  "page_count": 100,
  "pages_with_text": 1,
  "pages": [
    {"page": 2, "text": "Recognised", "words": [
      {"text": "Recognised", "left": 10, "top": 20, "width": 100, "height": 25}
    ], "confidence": 0.9},
    {"page": 7, "text": "", "words": [], "confidence": null}
  ]
}
```

The example shows the page fields. The complete response also contains the retained fields above.
`text` is the OCR engine's page text. It excludes native source text.
`words` retains the engine's complete word list. `confidence` retains its page confidence or null.
Image mode returns the stored word text joined with spaces and null confidence.
It works when the selected engine has no configured OCR endpoint.

## The overlay preserves source content and geometry.

The builder opens a PDF twice.
It removes Unicode text from the temporary render by deactivating text objects through every nested form.
Text objects without extractable Unicode stay active for OCR.
Rendering disables interactive forms and annotations.
Each selected page produces one temporary raster.

`FPDF_DeviceToPage` maps word boxes through CropBox offsets, page rotation, and MediaBox origins.
A ReportLab page supplies invisible text in render mode 3.
The builder inserts that page as a form into the unchanged output page.
It uses a full save with PDFium flags zero.
Unselected pages receive no overlay.

Image mode preserves the original JPEG data.
Other image formats use the smaller encoding from PNG and JPEG at quality 85.
The page uses the stored image resolution, or 150 dpi when no resolution exists.
The text layer uses Helvetica. Its PDF character coverage has the existing Windows-1252 limit.
Returned page text preserves the OCR engine's Unicode text.

## Resource budgets remain independent.

Object input uses `stat_object` and `fget_object` into temporary storage.
Object output uses `fput_object`. Output hashing reads bounded blocks.
Inline input decodes in bounded blocks.
Stored word options use a temporary JSON file, without a command argument size cutoff.
Temporary storage is removed after success or failure.

`OCR_PDF_MAX_INPUT_BYTES` defaults to 512 MiB. `OCR_PDF_MAX_PAGES` defaults to 2,000.
`OCR_PDF_MAX_PAGE_PIXELS` defaults to 40,000,000 pixels for one render.
The source segmentation size target adds no builder byte cutoff.
The thread pool limits renderer children to `OCR_PDF_CONCURRENCY`.
Admission includes `OCR_PDF_QUEUE_DEPTH` waiting requests.
Handler threads cover admission plus four additional handlers.

A full queue returns 503 with `Retry-After`.
An OCR-tier connection failure returns 503. OCR-tier 503 responses preserve `Retry-After`.
A renderer timeout kills and waits for its child, then returns 504.
A native renderer signal fails one request and leaves the service process running.
The synchronous handler has no HTTP disconnect cancellation hook.

`GET /health` verifies the renderer import and reports configured engines and admission limits.
Run builder tests inside the builder image with the current source loaded.
The repository verification script targets the running builder container.
A controlled source mount in an isolated container can verify changes without restarting active ingestion.
