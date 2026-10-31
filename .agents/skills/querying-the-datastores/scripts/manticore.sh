#!/usr/bin/env bash
# Run SQL with the processing service's Manticore connection helper.
set -euo pipefail
q="${1:?usage: manticore.sh <sql>}"
endpoint=text
if [[ "${MANTICORE_CONTAINER:-manticore}" == manticore-vectors ]]; then
  endpoint=vectors
fi
docker exec -i hoover4-worker sh -lc 'cd /app && uv run python - "$@"' _ "$endpoint" "$q" <<'PY'
import sys
from database.manticore import get_manticore_client
with get_manticore_client(sys.argv[1]) as client:
    with client.cursor() as cursor:
        cursor.execute(sys.argv[2])
        if cursor.description:
            print("\t".join(column[0] for column in cursor.description))
            for row in cursor.fetchall():
                print("\t".join(str(value) for value in row))
PY
