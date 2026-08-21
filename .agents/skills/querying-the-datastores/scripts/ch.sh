#!/usr/bin/env bash
# Run a ClickHouse query. Credentials come from the server container's own environment,
# so nothing here has to be typed, guessed, or kept in a tracked file.
#
#   ch.sh "SELECT count() FROM Hoover4_Processing.collections"
#   ch.sh "SHOW DATABASES"
#   FORMAT=PrettyCompact ch.sh "SELECT ..."     # default is TSVWithNames
set -euo pipefail
q="${1:?usage: ch.sh <query>}"
fmt="${FORMAT:-TSVWithNames}"
docker exec -i "${CH_CONTAINER:-clickhouse}" sh -lc \
  'clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" \
     --format "$1" --query "$2"' _ "$fmt" "$q"
