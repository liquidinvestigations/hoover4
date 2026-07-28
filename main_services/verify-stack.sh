#!/bin/bash
# End-to-end verification of the collections architecture.
#
# Usage: ./verify-stack.sh [--reset]
#
#   --reset   wipe all containers and volumes first (destructive, dev only)
#
# Steps: migrate, create the two canonical collections (testdata + other),
# ingest the two canonical datasets, wait for the pipeline, then assert the
# epic's invariants (see plans/2-collections/2-plan-0-overview.md §6) one by
# one. Prints OK/FAIL per check and exits non-zero on the first failure
# category with failures.
#
# Environment knobs:
#   WEBSITE_URL   default http://localhost:12345 (containerized website)
#   SEARCH_WORD   default easychair (present in the disk-files fixture data)
#   POLL_TIMEOUT  seconds to wait for ingestion, default 3600
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";
cd "$SCRIPT_DIR"

WEBSITE_URL="${WEBSITE_URL:-http://localhost:12345}"
SEARCH_WORD="${SEARCH_WORD:-easychair}"
POLL_TIMEOUT="${POLL_TIMEOUT:-3600}"
MAX_SHARD_TEXT_BYTES=1000000000

CH() { docker exec clickhouse clickhouse-client -u hoover4 --password hoover4 -q "$1"; }
MC() { docker exec manticore mysql -h0 -P9306 -N -B -e "$1" 2>/dev/null; }

FAILURES=0
ok()   { echo "OK   - $1"; }
fail() { echo "FAIL - $1"; FAILURES=$((FAILURES+1)); }

wait_for_clickhouse() {
    for _ in $(seq 1 60); do
        if CH "SELECT 1" >/dev/null 2>&1; then return 0; fi
        sleep 5
    done
    echo "ClickHouse did not become healthy in time" >&2; exit 1
}

wait_for_manticore() {
    for _ in $(seq 1 60); do
        if MC "show tables" >/dev/null 2>&1; then return 0; fi
        sleep 5
    done
    echo "Manticore did not become healthy in time" >&2; exit 1
}

ensure_collection_row() {
    # The admin UI is the normal way to create a collection row; for a scripted
    # reset the row is inserted directly (same columns the UI writes).
    local name="$1" fullname="$2"
    CH "INSERT INTO Hoover4_Processing.collections (collectionname, fullname)
        SELECT '$name', '$fullname'
        WHERE NOT EXISTS (SELECT 1 FROM Hoover4_Processing.collections FINAL
                          WHERE collectionname = '$name' AND is_deleted = 0)"
}

if [ "${1:-}" = "--reset" ]; then
    ./reset-docker.sh
fi

echo "== waiting for ClickHouse and Manticore =="
wait_for_clickhouse
wait_for_manticore

echo "== migrate =="
./run.sh migrate >/dev/null

echo "== ensure collections =="
ensure_collection_row testdata "Test Data"
ensure_collection_row other "Other Collection"
./run.sh ensure-collection testdata >/dev/null
./run.sh ensure-collection other >/dev/null

echo "== ingest canonical datasets =="
if [ -z "$(CH "SELECT collection_dataset FROM Hoover4_Processing.dataset FINAL WHERE collection_dataset = 'testdata_testfiles' AND is_deleted = 0")" ]; then
    ./run.sh add-disk-dataset testdata testfiles /testdata/hoover-testdata/data/disk-files >/dev/null
else
    echo "testdata_testfiles already registered, skipping ingest"
fi
if [ -z "$(CH "SELECT collection_dataset FROM Hoover4_Processing.dataset FINAL WHERE collection_dataset = 'other_emails' AND is_deleted = 0")" ]; then
    ./run.sh add-disk-dataset other emails /testdata/hoover-testdata/data/eml-2-attachment >/dev/null
else
    echo "other_emails already registered, skipping ingest"
fi

echo "== waiting for plans to finish (timeout ${POLL_TIMEOUT}s per collection) =="
for coll_db in Hoover4_Collection_testdata Hoover4_Collection_other; do
    deadline=$(( $(date +%s) + POLL_TIMEOUT ))
    while true; do
        plans=$(CH "SELECT count() FROM $coll_db.processing_plans FINAL")
        finished=$(CH "SELECT count() FROM $coll_db.processing_plan_finished FINAL")
        if [ "$plans" -gt 0 ] && [ "$plans" = "$finished" ]; then
            echo "$coll_db: $finished/$plans plans finished"
            break
        fi
        if [ "$(date +%s)" -gt "$deadline" ]; then
            fail "$coll_db: plans not finished after ${POLL_TIMEOUT}s ($finished/$plans)"
            break
        fi
        sleep 10
    done
done

echo "== invariants =="

# 1. The global database holds only global tables (no per-collection tables).
global_tables=$(CH "SHOW TABLES FROM Hoover4_Processing" | sort | tr '\n' ' ')
expected_global="collection_group_permissions collections dataset schema_versions search_manticore_cache server_settings temp_chat_json_objects user_group_membership user_groups users web_sessions "
if [ "$global_tables" = "$expected_global" ]; then
    ok "global DB has exactly the global table set"
else
    fail "global DB table set drifted: got [$global_tables], want [$expected_global]"
fi

# 2. Every collection DB has the full collection table set (parsed from the
#    migration files, plus schema_versions).
expected_collection=$(grep -hoiE 'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?[a-z_]+`?' \
    processing/database/db_collection_migrations/*.sql \
    | awk '{print $NF}' | tr -d '`' | { cat -; echo schema_versions; } | sort | tr '\n' ' ')
for coll_db in Hoover4_Collection_testdata Hoover4_Collection_other; do
    actual=$(CH "SHOW TABLES FROM $coll_db" | sort | tr '\n' ' ')
    if [ "$actual" = "$expected_collection" ]; then
        ok "$coll_db has the full collection table set"
    else
        fail "$coll_db table set mismatch: got [$actual], want [$expected_collection]"
    fi
done

# 3. No collection data in the global DB and vice versa: the per-collection
#    sentinel table must not exist globally.
if CH "SHOW TABLES FROM Hoover4_Processing" | grep -q '^vfs_files$'; then
    fail "vfs_files found in the global database"
else
    ok "no per-collection tables in the global database"
fi

# 4. Shard ledger matches Manticore's SHOW TABLES, and Manticore holds no
#    non-shard tables (in particular no global doc_text_pages / doc_metadata).
#    Manticore's mysql protocol always emits bordered output (it ignores -N -B),
#    so the table names are the second |-delimited column. Take ALL of them, not
#    just *_pages/_meta matches: a leftover non-shard table must fail this check.
manticore_tables=$(MC "show tables" | awk -F'|' 'NF>2 {gsub(/ /,"",$2); if ($2 != "") print $2}' | sort)
ledger_tables=""
for coll in testdata other; do
    shards=$(CH "SELECT shard_name FROM Hoover4_Collection_$coll.manticore_shards FINAL ORDER BY shard_index")
    for shard in $shards; do
        ledger_tables="$ledger_tables${shard}_pages\n${shard}_meta\n"
    done
done
ledger_tables=$(printf "%b" "$ledger_tables" | sort)
if [ "$manticore_tables" = "$ledger_tables" ]; then
    ok "Manticore tables exactly match the shard ledgers"
else
    fail "Manticore/ledger mismatch: manticore=[$(echo $manticore_tables)], ledger=[$(echo $ledger_tables)]"
fi

# 5. No shard over the 1 GB text budget (single-document shards may exceed it).
over_budget=$(CH "
    SELECT count() FROM (
        SELECT shard_name, text_bytes, doc_count
        FROM Hoover4_Collection_testdata.manticore_shards FINAL
        UNION ALL
        SELECT shard_name, text_bytes, doc_count
        FROM Hoover4_Collection_other.manticore_shards FINAL
    ) WHERE text_bytes > $MAX_SHARD_TEXT_BYTES AND doc_count > 1")
if [ "$over_budget" = "0" ]; then
    ok "no shard over the 1 GB text budget"
else
    fail "$over_budget shard(s) over the text budget"
fi

# 6. Every (collection_dataset, file_hash) pair lives in exactly one shard, and the
#    index_state rows (what the writers actually committed) match the actual
#    Manticore row counts. Document identity is the PAIR, not file_hash alone: the
#    same content in two datasets of one collection is indexed twice.
for coll in testdata other; do
    db="Hoover4_Collection_$coll"
    multi=$(CH "SELECT count() FROM (SELECT collection_dataset, file_hash, uniqExact(shard_name) AS n
                FROM $db.manticore_shard_assignments FINAL
                GROUP BY collection_dataset, file_hash) WHERE n != 1")
    [ "$multi" = "0" ] && ok "$coll: every (dataset, file_hash) pair in exactly one shard" \
        || fail "$coll: $multi (dataset, file_hash) pair(s) assigned to != 1 shard"
    recorded=$(CH "SELECT count() FROM $db.index_state FINAL")
    indexed=0
    for table in $(MC "show tables" | grep -oE "${coll}_[0-9]+_meta"); do
        # Manticore has no count(distinct concat(...)): GROUP BY the pair and
        # count the bordered result rows (each data line starts with '|').
        n=$(MC "SELECT collection_dataset, file_hash FROM $table
                GROUP BY collection_dataset, file_hash
                LIMIT 100000 OPTION max_matches=100000" | grep -c '^|')
        indexed=$((indexed + n))
    done
    [ "$recorded" = "$indexed" ] && ok "$coll: $indexed indexed docs == $recorded index_state rows" \
        || fail "$coll: $indexed indexed docs != $recorded index_state rows"
done

# 7. The website serves.
code=$(curl -s -o /dev/null -w '%{http_code}' "$WEBSITE_URL/")
[ "$code" = "200" ] && ok "website / returns 200" || fail "website / returned $code"

# 8. A search through the site's HTTP API returns >0 hits for a word known to
#    be in the fixture data. The server-function URL contains a build hash, so
#    it is discovered from the served WASM bundle.
wasm_path=$(curl -s "$WEBSITE_URL/" | grep -oE 'wasm/[a-zA-Z0-9_-]+\.js' | head -1)
api_path=""
if [ -n "$wasm_path" ]; then
    wasm_file=$(curl -s "$WEBSITE_URL/$wasm_path" | grep -oE '[a-zA-Z0-9_./-]*frontend_bg[a-zA-Z0-9_-]*\.wasm' | head -1)
    if [ -n "$wasm_file" ]; then
        wasm_url="${wasm_file#/}"
        case "$wasm_url" in wasm/*) ;; *) wasm_url="wasm/$wasm_url";; esac
        api_path=$(curl -s "$WEBSITE_URL/$wasm_url" | strings \
            | grep -oE '/api/search_for_results_hit_count[0-9]+' | head -1)
    fi
fi
if [ -z "$api_path" ]; then
    fail "could not discover the search server-function URL from the WASM bundle"
else
    body='[{"collection_datasets":[],"query_string":"'"$SEARCH_WORD"'","facet_filters":{}}]'
    response=$(curl -s -X POST "$WEBSITE_URL$api_path" -H 'Content-Type: application/json' -d "$body")
    # SearchResultHitCount serialises as {"total":N,"partial":bool}.
    hits=$(printf '%s' "$response" | grep -oE '"total":[0-9]+' | grep -oE '[0-9]+' | head -1)
    if [ -n "$hits" ] && [ "$hits" -gt 0 ]; then
        ok "search for '$SEARCH_WORD' returned $hits hits through the HTTP API"
    else
        fail "search for '$SEARCH_WORD' through the HTTP API returned: $response"
    fi
fi

echo
if [ "$FAILURES" -gt 0 ]; then
    echo "verify-stack: $FAILURES check(s) FAILED"
    exit 1
fi
echo "verify-stack: all checks passed"
