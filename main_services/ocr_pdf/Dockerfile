# Searchable-PDF assembly. CPU only, and with no OCR engine of its own: it renders pages
# and calls the existing OCR tier over HTTP, so adding a language here would be a lie —
# the traineddata lives in `main_services/ocr_tesseract`.
FROM python:3.13-slim

WORKDIR /app

# pypdfium2 ships the PDFium binary in its wheel and Pillow ships its own codecs, so
# there is deliberately no apt layer: no poppler, no ghostscript, no tesseract. This
# image renders and assembles, nothing else.
RUN pip install --no-cache-dir \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.34" \
        "pydantic>=2.9" \
        "requests>=2.32" \
        "minio>=7.2" \
        "pypdfium2>=4.30" \
        "pillow>=11.0" \
        "reportlab>=4.2" \
        "pytest>=8.3"

COPY ocr_pdf.py /app/ocr_pdf.py
COPY tests /app/tests

ENV HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# One uvicorn worker: concurrency is bounded inside the app by a thread pool, and a
# second uvicorn process would double it behind the app's own back — which here means
# doubling the load on the OCR tier this service is supposed to be polite to.
CMD ["sh", "-c", "uvicorn ocr_pdf:app --host ${HOST} --port ${PORT} --workers 1"]
