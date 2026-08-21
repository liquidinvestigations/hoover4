#!/usr/bin/env bash
# Run the pipeline unit tests inside the worker. Optional argument narrows the target.
set -uo pipefail
target="${1:-tests/unit}"
docker exec hoover4-worker sh -lc "cd /app && uv run pytest ${target} -q 2>&1" | tail -30
exit "${PIPESTATUS[0]}"
