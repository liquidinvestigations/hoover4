FROM python:3.13
RUN pip install uv
# poppler-utils provides `pdftotext`, which parse_pdf.py has always shelled out to and
# which was never installed -- so PDF text extraction silently produced nothing for
# every PDF ever ingested (`_maybe_pdftotext` swallows FileNotFoundError and returns
# None). Extractous picked up some of it under its own label, which is why the gap
# looked like "PDFs have little text" rather than a missing binary.
#
# tesseract-ocr-eng is deliberately NOT installed (plans/1-part-2.md 3.1). With the
# binary present, native Tika OCRs scanned PDFs implicitly and attributes the text to
# `extractous`, where no per-dataset language setting can reach it. OCR is an HTTP
# service now (main_services/ocr_tesseract, ai_services/easyocr_server) and every OCR
# variant is attributed to the engine and languages that produced it.
RUN  apt-get update -yy && apt-get install -yy sed &&  sed -i 's/^Components: main$/& contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources && apt-get update -yy &&  apt-get install -yy p7zip-full p7zip-rar qpdf poppler-utils ffmpeg curl wget file build-essential
WORKDIR /app
ADD . .
RUN uv run main.py version
