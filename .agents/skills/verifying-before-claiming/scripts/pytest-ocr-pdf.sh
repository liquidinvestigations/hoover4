#!/usr/bin/env bash
# Run the searchable-PDF service's own unit tests, inside its own image.
#
# hoover4-ocr-pdf carries pytest and its tests (see main_services/ocr_pdf/Dockerfile).
# Nothing else reached this directory before this script existed. It is not part of the
# pipeline's own suite (pytest-unit.sh runs in hoover4-worker, a different image), and it
# is not one of the MCP servers pytest-agents.sh loops over.
#
# Optional argument narrows the target, e.g. `tests/test_ocr_pdf.py::test_name`.
set -uo pipefail
target="${1:-tests/}"
docker exec hoover4-ocr-pdf python -m pytest "${target}" -q 2>&1 | tail -30
exit "${PIPESTATUS[0]}"
