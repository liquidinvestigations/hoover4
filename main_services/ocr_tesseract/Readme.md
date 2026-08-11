# ocr_tesseract — Tesseract OCR over HTTP (CPU)

The CPU half of the OCR tier. Its GPU twin is `ai_services/easyocr_server`, and both
speak the same contract so `tasks/remote.py` can fall back from one to the other
without the call site branching.

## Why OCR is a service

Two failure modes put it here:

1. **EasyOCR in-process deadlocked the worker.** Two concurrent `readtext` calls parked
   all 91 threads of the worker process in `futex_wait`, with heartbeats still flowing —
   a live thread making no forward progress, which is precisely the case a heartbeat
   pump cannot detect. Nothing would ever have retried it. A bounded pool behind an HTTP
   boundary makes that arrangement impossible.
2. **`tesseract-ocr-eng` in the worker image made Tika OCR scanned PDFs implicitly**,
   producing text attributed to `extractous` that no dataset setting could turn off.
   With the binary gone that parser is inert, and the same text comes back through here
   as its own attributed variant.

## Contract

```
GET  /health  -> {"status", "engine", "languages_available", "concurrency", ...}
POST /ocr     {"image_b64": "...", "languages": "eng+ron", "psm": 3}
              -> {"text", "confidence", "engine", "languages", "run_time_ms", "words": [...]}
```

- **`languages` is one pass.** Tesseract takes `eng+ron` in a single invocation and picks
  per region, so a multi-language dataset costs one pass and produces one variant. This
  is the asymmetry with EasyOCR, which needs one Reader per script and therefore one
  pass, one variant, and one full set of downstream rows *per script group*.
- **Per-word confidence is returned** because storing every language variant is only
  useful if they can be scored against each other and a winner marked for display.
- **`words` carries boxes**, which is what an hOCR/searchable-PDF layer needs later.

## Operational notes

- `languages_available` is read from `tesseract --list-langs`, not from configuration.
  A dataset configured for a language whose traineddata is not in the image fails per
  file, and `/health` is the only place that mismatch is visible beforehand. Languages
  are an image build argument (`TESSERACT_LANGS`); there is no download-on-demand path.
- **Backpressure is explicit.** `OCR_CONCURRENCY` slots plus an `OCR_QUEUE_DEPTH` queue;
  beyond that the service answers `503` with `Retry-After`. The client maps that to a
  *retryable* Temporal error, so a busy OCR tier slows the pipeline rather than filling
  `processing_errors`.
- **The subprocess timeout stays.** An HTTP boundary does not fix a wedged child: the
  request is bounded, the `tesseract` process it spawned is not. Do not remove
  `OCR_SUBPROCESS_TIMEOUT_S` on the grounds that the service is bounded.
- Requests are JSON with base64 rather than multipart so the call goes through
  `tasks/remote.py` and inherits its `(connect, read)` timeouts, CPU fallback and
  circuit breaker. That costs 33% on the wire for a payload capped at
  `OCR_MAX_IMAGE_BYTES`. PDFs never come through here.

## Navigation

- [Go Back](../Readme.md)
- [Processing pipeline](../processing/Readme.md)
