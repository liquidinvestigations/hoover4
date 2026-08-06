# Tesseract OCR over HTTP. CPU only, deliberately: this is the twin that keeps working
# when the GPU tier is unreachable, so it must not depend on it in any way.
FROM python:3.13-slim

# Language data is chosen at build time, not at runtime: traineddata files are ~15 MB
# each and a dataset configured for a language that is not installed fails per file.
# /health lists what is actually present so that mismatch is visible before it bites.
# Add languages here and rebuild -- there is no download-on-demand path on purpose.
ARG TESSERACT_LANGS="tesseract-ocr-eng tesseract-ocr-ron tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-spa tesseract-ocr-rus"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr ${TESSERACT_LANGS} \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.34" \
        "pydantic>=2.9"

COPY ocr_tesseract.py /app/ocr_tesseract.py

ENV HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# One uvicorn worker: concurrency is bounded inside the app by a thread pool sized to
# the CPU, and a second uvicorn process would double it behind the app's own back.
CMD ["sh", "-c", "uvicorn ocr_tesseract:app --host ${HOST} --port ${PORT} --workers 1"]
