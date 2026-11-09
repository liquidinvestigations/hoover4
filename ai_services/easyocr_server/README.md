# EasyOCR server

GPU OCR over HTTP, the GPU half of the OCR tier, and the counterpart of
[`main_services/ocr_tesseract`](../../main_services/ocr_tesseract/Readme.md).

## Contract

```
POST /ocr    {"image_b64": ..., "languages": "en+ro"}
             -> {"text", "confidence", "engine", "languages", "run_time_ms", "words": [...]}
GET  /health -> {"status", "engine", "languages_available", "languages_supported",
                 "failed_downloads", "gpu", ...}
```

This is the same request and response shape the Tesseract twin serves, because
[`tasks/ocr_client.py`](../../main_services/processing/tasks/ocr_client.py) builds one
payload and posts it to the engine that the automatic OCR plan chose. `psm` is accepted and
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

`words` carries one entry per recognised **line**, not per word (that is EasyOCR's
detection granularity) with its free quadrilateral reduced to a bounding rectangle.

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

[`language_groups.py`](language_groups.py) lists the installed language groups. One group
is one Reader, because EasyOCR cannot mix scripts in one Reader. The image build loads a
Reader of each group and a Reader of `en` alone, which uses the English model. The
weights of all of them are in the image, the way the Tesseract twin bakes its
traineddata, so they work without internet access. No setting changes the groups.

easyocr 1.7.2 lists `sa`, `bgc`, `mni` and `ta`, but a Reader with one of them cannot load
(`UNLOADABLE`). The package has no character file for the first three, and the published
Tamil model does not match the Tamil character file. The build leaves them out of each
group, and `/ocr` refuses a request that names one of them, or a code outside the groups,
with status 400.

The compose overlay bind-mounts the host folder `easyocr_models_cache` over
`/root/.EasyOCR`, and that mount hides what the image has there. The image therefore
keeps a second copy of the weights at `EASYOCR_BAKED_DIR`. At start, before it serves,
the server copies each file from there into `EASYOCR_MODEL_DIR` when that file is absent,
and it logs the count. It never overwrites a file, so a second start copies 0 files. A
copy error stops the start, and the health check does not pass.

`/health` reports two sorted lists. `languages_supported` is every code of the installed
groups that the `easyocr` package lists. `languages_available` is the same list without
the unloadable codes. The automatic OCR planner reads `languages_supported` as the
installed capability. That list is part of the identity of each automatic OCR plan, so a
change to it selects every applied file for the OCR processing update again. The
unloadable codes stay in it for this reason. `failed_downloads` holds
the last Reader build error of each language set whose models could not load, for example
a model file that is absent from the cache folder on a host without internet access. A
later successful build removes the entry.

The worker keeps the same groups in `EASY_SCRIPT_GROUPS` of
[`tasks/automatic_ocr.py`](../../main_services/processing/tasks/automatic_ocr.py). The
image build context is this folder only, so the two files are copies, and
`tests/test_language_groups.py` fails when they differ.

## Image

There is no CUDA base image. The torch wheels from the CUDA 13 index carry their own
runtime libraries as `nvidia-*-cu13` packages, and the only piece that has to come from
outside is `libcuda.so.1`, which nvidia-container-toolkit injects from the host driver.
A CUDA base image on top of that adds a second, unused copy of the toolkit and pins the
image to one CUDA minor. This way one Dockerfile builds on x86_64 and aarch64 and
follows whatever driver the host has. See
[CUDA and GPU architecture](../README.md#cuda-and-gpu-architecture).

`/health` reads `gpu` from torch rather than from the environment: a container that lost
its device injection still starts and still OCRs, only far slower, and this is the one
place that shows it before a dataset takes a day.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `EASYOCR_MODEL_DIR` | `/root/.EasyOCR` | Where weights live. The cache folder is bind-mounted here |
| `EASYOCR_BAKED_DIR` | `/opt/easyocr-baked` in the image | The baked weights, copied into `EASYOCR_MODEL_DIR` at start. Empty or absent means no copy |
| `OCR_CONCURRENCY` | `1` | See above, a correctness bound |
| `OCR_QUEUE_DEPTH` | `8` | Requests that may wait before the service sheds load |
| `OCR_READER_CACHE_SIZE` | `3` | Warm `Reader`s kept; each holds GPU memory, and the key is caller-supplied |
| `OCR_MAX_IMAGE_BYTES` | `67108864` | Ceiling on one decoded image |

## Tests

The tests run in a throwaway container of the worker image, which has the same `easyocr`
version, with the checkout mounted read-only. Set `EASYOCR_TEST_MODEL_DIR` to a folder
with the baked weights to run the load test too.

```sh
docker run --rm -v "$PWD:/repo:ro" -e PYTHONDONTWRITEBYTECODE=1 -e REPO_ROOT=/repo \
    --entrypoint sh localhost/hoover4_hoover4-worker:latest -c \
    'uv pip install -q --python /opt/pysetup/.venv/bin/python fastapi &&
     cd /repo/ai_services/easyocr_server &&
     PYTHONPATH=. /opt/pysetup/.venv/bin/python -m pytest tests -q -p no:cacheprovider'
```
