FROM python:3.13
RUN pip install uv
# poppler-utils provides `pdftotext`, which parse_pdf.py has always shelled out to and
# which was never installed -- so PDF text extraction silently produced nothing for
# every PDF ever ingested (`_maybe_pdftotext` swallows FileNotFoundError and returns
# None). Extractous picked up some of it under its own label, which is why the gap
# looked like "PDFs have little text" rather than a missing binary.
#
# tesseract-ocr-eng is deliberately NOT installed. With the
# binary present, native Tika OCRs scanned PDFs implicitly and attributes the text to
# `extractous`, where no per-dataset language setting can reach it. OCR is an HTTP
# service (main_services/ocr_tesseract, ai_services/easyocr_server) and every OCR
# variant is attributed to the engine and languages that produced it.
RUN  apt-get update -yy && apt-get install -yy sed &&  sed -i 's/^Components: main$/& contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources && apt-get update -yy &&  apt-get install -yy p7zip-full p7zip-rar qpdf poppler-utils ffmpeg curl wget file build-essential
WORKDIR /app
# The dependency layer stays separate from the source layer, so a source-only change
# rebuilds nothing above this line: `uv.lock` and `pyproject.toml` change far less often
# than the code, and `--no-install-project` installs every dependency without needing
# the source tree that names the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
ADD . .
RUN uv run main.py version
