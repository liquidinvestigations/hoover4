# ocr_tesseract: Tesseract OCR over HTTP (CPU)

This service runs Tesseract on the CPU.
Its GPU counterpart, `ai_services/easyocr_server`, runs EasyOCR through the same request contract.
The client preserves each engine's source identity and does not substitute one engine for the other.

## OCR runs in a separate service.

Two failure modes put it here:

1. **EasyOCR in-process deadlocked the worker.** Two concurrent `readtext` calls parked
   all 91 threads of the worker process in `futex_wait`, with heartbeats still flowing.
   A live thread making no forward progress, which is precisely the case a heartbeat
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
POST /detect  {"image_b64": "..."}
              -> {"has_text", "box_count", "confident_boxes", "script", "model", "text", "run_time_ms"}
```

- **`languages` is one pass.** Tesseract takes `eng+ron` in a single invocation and picks
  per region, so a multi-language dataset costs one pass and produces one variant. This
  is the asymmetry with EasyOCR, which needs one Reader per script and therefore one
  pass, one variant, and one full set of downstream rows *per script group*.
- **Per-word confidence is returned** because storing every language variant is only
  useful if they can be scored against each other and a winner marked for display.
- **`words` carries boxes**, which is what an hOCR/searchable-PDF layer needs later.

When Leptonica rejects a JPEG scan header, Pillow attempts to decode the complete image.
A successful decode produces a lossless PNG for one Tesseract retry within the original subprocess timeout.
The retry preserves the image dimensions and pixel orientation.
An undecodable image keeps its original failure.

## Text detection

`/detect` describes one image on the CPU in [text_detection.py](text_detection.py).
A PP-OCRv6 tiny detector finds text boxes. An image has text with at least 3 boxes of a score of 0.6 or more.
A line model names the script of the 6 longest lines, and the most frequent label decides.
A line that stands on end turns to the side where the labels agree most. A line with light text is inverted.
One Tesseract call reads up to 4 lines with the script model of that name, and the output goes back as `text`.
The worker identifies the language from that text. The route shares the OCR slots and the `503` rule.
An image without text returns after the detector.
The models are local files, listed in [models/Readme.md](models/Readme.md).

## Operational notes

- `languages_available` is read from `tesseract --list-langs`, not from configuration.
  A dataset configured for a language whose traineddata is not in the image fails per
  file, and `/health` is the only place that mismatch is visible beforehand. Languages
  are an image build argument (`TESSERACT_LANGS`). There is no download-on-demand path.
  The default `tesseract-ocr-all` installs every Debian language package, so the list holds
  more than 100 languages, the orientation model `osd` and script models with capitalised
  names such as `Latin`. The admin form offers the languages and `osd`, and leaves out the
  script models, because a dataset setting becomes part of a storage key and accepts
  lowercase codes only.
- **Backpressure is explicit.** `OCR_CONCURRENCY` slots plus an `OCR_QUEUE_DEPTH` queue;
  beyond that the service answers `503` with `Retry-After`. The client maps that to a
  *retryable* Temporal error, so a busy OCR tier slows the pipeline rather than filling
  `processing_errors`.
- The thread limit of the `def` handlers is `OCR_CONCURRENCY + OCR_QUEUE_DEPTH + 4`, so
  an admitted request never waits for a handler thread. `/health` runs on the event loop,
  so it answers while every thread is busy. It reports the limit as `http_threads`.
- **The subprocess timeout stays.** An HTTP boundary does not fix a wedged child: the
  request is bounded, the `tesseract` process it spawned is not. Do not remove
  `OCR_SUBPROCESS_TIMEOUT_S` on the grounds that the service is bounded.
- Requests are JSON with base64 rather than multipart so the call goes through
  [tasks/remote.py](../processing/tasks/remote.py) and inherits its `(connect, read)` timeouts, CPU fallback and
  circuit breaker. That costs 33% on the wire for a payload capped at
  `OCR_MAX_IMAGE_BYTES`. PDFs never come through here.

## Navigation

- [Go Back](../Readme.md)
- [Processing pipeline](../processing/Readme.md)
