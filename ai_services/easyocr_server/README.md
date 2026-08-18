# EasyOCR server

GPU OCR over HTTP — the GPU half of the OCR tier, and the counterpart of
[`main_services/ocr_tesseract`](../../main_services/ocr_tesseract/Readme.md).

## Contract

```
POST /ocr    {"image_b64": ..., "languages": "en+ro"}
             -> {"text", "confidence", "engine", "languages", "run_time_ms", "words": [...]}
GET  /health -> {"status", "engine", "languages_available", "gpu", ...}
```

This is the same request and response shape the Tesseract twin serves, because
[`tasks/ocr_client.py`](../../main_services/processing/tasks/ocr_client.py) builds one
payload and posts it to whichever engine a dataset asked for. `psm` is accepted and
ignored: page segmentation is a Tesseract concept, and rejecting a field the shared
client always sends would make the two engines un-substitutable at the call site for no
gain.

The engines are **not** fallbacks for each other. The engine is part of the storage key
(`ocr_easyocr_en` vs `ocr_tesseract_eng`), so serving one from the other would file the
same text twice under two labels and quietly defeat the fan-out that exists to let
variants be compared. An engine that is unreachable raises and is retried; it never
substitutes.

`confidence` is reported on Tesseract's **0..100** scale, not EasyOCR's native 0..1, for
the same reason: the stored variants are scored against each other.

`words` carries one entry per recognised **line**, not per word — that is EasyOCR's
detection granularity — with its free quadrilateral reduced to a bounding rectangle.

## Concurrency is one, deliberately

Two concurrent `readtext` calls in one process park every thread in `futex_wait` while
heartbeats keep flowing: a live process making no progress, which is the one failure a
heartbeat pump cannot see. That is why OCR is a service rather than a subprocess in the
worker, and it is equally true inside this service. `OCR_CONCURRENCY` defaults to 1 and
is a correctness bound, not a throughput setting; raising it reintroduces the deadlock.

Backpressure is explicit instead: a bounded pool, a capped queue, and `503` +
`Retry-After` once the queue is full. The client turns that into a *retryable* Temporal
error, so a busy OCR tier slows the pipeline down rather than filling `processing_errors`
with noise.

## Models

Weights for the languages named in the `EASYOCR_LANGUAGES` build arg are baked into the
image, the way the Tesseract twin bakes its traineddata: a service that must reach the
internet before answering its first request fails in a way the health check cannot
report. The compose overlay mounts `easyocr_models_cache` over `/root/.EasyOCR`, and an
empty named volume is seeded from the image, so the baked weights carry into it.

A language that is *not* baked in still works — it is downloaded on first use, and pays
for that on the first page. `/health` advertises only the baked set.

Adding a language in a new script is the main cost lever in the pipeline: it adds a full
OCR pass **and** a complete set of downstream NER, chunk, embed and index rows. See
`easyocr_language_groups` in
[`tasks/text_sources.py`](../../main_services/processing/tasks/text_sources.py) for how a
requested language set is split into script-compatible passes.

## Image

There is no CUDA base image. The torch wheels from the CUDA 13 index carry their own
runtime libraries as `nvidia-*-cu13` packages, and the only piece that has to come from
outside is `libcuda.so.1`, which nvidia-container-toolkit injects from the host driver.
A CUDA base image on top of that adds a second, unused copy of the toolkit and pins the
image to one CUDA minor — this way one Dockerfile builds on x86_64 and aarch64 and
follows whatever driver the host has. See
[CUDA and GPU architecture](../README.md#cuda-and-gpu-architecture).

`/health` reads `gpu` from torch rather than from the environment: a container that lost
its device injection still starts and still OCRs, only far slower, and this is the one
place that shows it before a dataset takes a day.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `EASYOCR_LANGUAGES` | `en` | `+`-joined codes advertised by `/health`; also the build arg that decides what is baked in |
| `EASYOCR_MODEL_DIR` | `/root/.EasyOCR` | Where weights live; the cache volume mounts here |
| `OCR_CONCURRENCY` | `1` | See above — a correctness bound |
| `OCR_QUEUE_DEPTH` | `8` | Requests that may wait before the service sheds load |
| `OCR_READER_CACHE_SIZE` | `3` | Warm `Reader`s kept; each holds GPU memory, and the key is caller-supplied |
| `OCR_MAX_IMAGE_BYTES` | `67108864` | Ceiling on one decoded image |
