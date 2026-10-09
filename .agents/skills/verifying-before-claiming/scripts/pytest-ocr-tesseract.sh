#!/usr/bin/env bash
# Run the Tesseract OCR service's own unit tests in a throwaway container of its image.
#
# The service image carries no pytest, so the container installs it first. The source is
# mounted read-only from this checkout, so the tests read the tree, not the image copy.
# Rebuild the image first when a dependency in its Dockerfile changed.
#
# Optional argument narrows the target, e.g. `tests/test_ocr_tesseract.py::test_name`.
set -uo pipefail
root="$(git rev-parse --show-toplevel)"
target="${1:-tests}"
docker run --rm -v "$root/main_services/ocr_tesseract:/src:ro" -w /src \
    -e PYTHONDONTWRITEBYTECODE=1 --entrypoint sh hoover4-tesseract-cpu:local \
    -c "pip install -q pytest >/dev/null 2>&1 && PYTHONPATH=/src python -m pytest $target -q -p no:cacheprovider" \
    2>&1 | tail -30
exit "${PIPESTATUS[0]}"
