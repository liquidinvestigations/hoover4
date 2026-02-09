# P3 - Parse Files

This stage parses downloaded files by type and writes structured content and metadata to ClickHouse. It uses Temporal workflows to route files to specialized handlers.

## Key Responsibilities

- Detect MIME types using GNU `file`, Tika/Extractous, and Magika.
- Parse archives, emails, PDFs, images, audio, video, and raw text.
- Run OCR for images and extract text for indexing.
- Create temporary directories for extracted content and scan them as containers.

## Entry Points

- Workflow: `ParseSingleFile` in `workflows.py`
- Activities: `parse_*` modules (e.g., `parse_pdf.py`, `parse_email.py`, `parse_image.py`)
- Helpers: `parse_common.py` for text chunking and error recording

## Technical Details

Parsing uses type-based routing derived from detector results. Archives, PDFs, emails, and videos can spawn child scans by writing extracted content to temp directories and invoking P0 workflows with container hashes. OCR runs on a dedicated queue (`processing-easyocr-queue`) and Tika runs on `processing-tika-queue` to isolate heavy dependencies.

## Usage

- Executed as part of P2 plan execution.
- Ensure required external tools are present: `file`, `7z`, `qpdf`, `ffprobe`, `ffmpeg`, and Tika.

## Navigation

- [Go Back](../Readme.md)
- [P2 - Execute Plan](../P2_execute_plan/Readme.md)
- [P4 - Index Data](../P4_index_data/Readme.md)
