#!/usr/bin/env bash
# Run a Manticore SQL statement over its MySQL protocol port inside the container.
#
#   manticore.sh "SHOW TABLES"
#   manticore.sh "SELECT count(*) FROM testdata_1_pages"
#
# Structure queries against a <collection>_vfs table are read uncached on purpose: that
# tree changes while ingestion runs, and a stale tree is worse than a slow one.
set -euo pipefail
q="${1:?usage: manticore.sh <sql>}"
docker exec -i "${MANTICORE_CONTAINER:-manticore}" sh -lc \
  'mysql -h127.0.0.1 -P9306 --protocol=tcp -e "$1"' _ "$q"
