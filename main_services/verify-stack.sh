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
WORKER="${WORKER:-hoover4-worker}"
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

wait_for_worker() {
    # Every step below runs through `docker exec hoover4-worker`, and the worker starts
    # late: it waits on Temporal, which waits on Cassandra. Straight after a
    # `./deploy --reset && ./deploy` the databases answer while the worker container
    # does not exist yet, so migrate/ensure-collection/add-disk-dataset all fail
    # instantly and the run looks like a stack failure rather than a race.
    for _ in $(seq 1 60); do
        if docker exec "$WORKER" uv run main.py version >/dev/null 2>&1; then return 0; fi
        sleep 5
    done
    echo "$WORKER did not become usable in time" >&2; exit 1
}

wait_for_temporal() {
    # The gap that defeated three earlier runs. wait_for_worker only proves the
    # worker container answers `main.py version`, which touches neither Temporal
    # nor the queues -- so the worker looks ready while Temporal is still doing
    # its schema setup behind Cassandra. add-disk-dataset then fails on
    # TemporalClient.connect within a second, and because its output used to go
    # to /dev/null the whole run looked like an instant unexplained exit 1.
    #
    # Connecting is not enough either: starting a workflow needs the
    # CollectionDataset search attribute to be registered AND pushed to
    # Elasticsearch, or the start is rejected with "search attribute
    # CollectionDataset is not defined". Wait for the thing we actually need.
    for _ in $(seq 1 60); do
        if docker exec "$WORKER" uv run python -c "
import asyncio, sys
from temporalio.client import Client
from tasks.visibility import ensure_search_attributes_ready
async def main():
    client = await Client.connect('temporal:7233')
    sys.exit(0 if await ensure_search_attributes_ready(client, 10) else 1)
asyncio.run(main())
" >/dev/null 2>&1; then return 0; fi
        sleep 5
    done
    echo "Temporal did not become usable (search attribute never registered)" >&2; exit 1
}

# Run a ./run.sh subcommand, showing its output only if it FAILS. The previous
# `>/dev/null` hid the failure reason on the one path where it mattered.
run_step() {
    local log
    log=$(mktemp)
    if ! ./run.sh "$@" >"$log" 2>&1; then
        echo "FAILED: ./run.sh $*" >&2
        cat "$log" >&2
        rm -f "$log"
        return 1
    fi
    rm -f "$log"
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

echo "== waiting for ClickHouse, Manticore, the worker and Temporal =="
wait_for_clickhouse
wait_for_manticore
wait_for_worker
wait_for_temporal

echo "== migrate =="
run_step migrate

echo "== ensure collections =="
ensure_collection_row testdata "Test Data"
ensure_collection_row other "Other Collection"
run_step ensure-collection testdata
run_step ensure-collection other

# These block until each dataset is fully ingested, which is correct: the three
# stages (scan, compute plans, execute plans) must run in order, and only the
# CLI sequences them today. It does mean the ingest is tied to this script --
# the 47-minute run that died at EXIT=137 was a redeploy SIGKILLing exactly this
# docker exec while the workflows carried on server-side. DO NOT redeploy while
# this is running; the poll loop below is the safety net if you do.
echo "== ingest canonical datasets =="
if [ -z "$(CH "SELECT collection_dataset FROM Hoover4_Processing.dataset FINAL WHERE collection_dataset = 'testdata_testfiles' AND is_deleted = 0")" ]; then
    run_step add-disk-dataset testdata testfiles /testdata/hoover-testdata/data/disk-files
else
    echo "testdata_testfiles already registered, skipping ingest"
fi
if [ -z "$(CH "SELECT collection_dataset FROM Hoover4_Processing.dataset FINAL WHERE collection_dataset = 'other_emails' AND is_deleted = 0")" ]; then
    run_step add-disk-dataset other emails /testdata/hoover-testdata/data/eml-2-attachment
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

# The collections the invariants below are checked against. Derived from the ledger, not
# hardcoded: this script creates `testdata` and `other`, but the stack accumulates others
# (a `vectortest` shell outlived its experiment), and every check that iterated a literal
# `for coll in testdata other` silently exempted them — including the Manticore/ledger
# equality check, which is precisely the one that should have noticed.
COLLECTIONS=$(CH "SELECT collectionname FROM Hoover4_Processing.collections FINAL
                  WHERE is_deleted = 0 ORDER BY collectionname")
if [ -z "$COLLECTIONS" ]; then
    fail "no collections registered — nothing to verify"
fi
with_db=""
for coll in $COLLECTIONS; do
    if [ -z "$(CH "SELECT name FROM system.databases WHERE name = 'Hoover4_Collection_$coll'")" ]; then
        fail "collection '$coll' is registered but has no Hoover4_Collection_$coll database"
    else
        with_db="$with_db$coll
"
    fi
done
COLLECTIONS="$with_db"
echo "     collections under test: $(echo $COLLECTIONS)"

# Whether a `_vectors` shard table is expected. `create_shard_tables` builds one only
# when the embedding dimension has been probed (`knn_dims` is fixed at creation and
# cannot be altered, so it is never guessed) — so the expectation has to follow the same
# switch rather than assume either answer.
serving_dim=$(CH "SELECT argMax(value, updated_at) FROM Hoover4_Processing.server_settings
                  WHERE key = 'embeddings_serving_dim'" 2>/dev/null || true)
case "$serving_dim" in
    ""|0) EXPECT_VECTOR_SHARDS=0 ;;
    *)    EXPECT_VECTOR_SHARDS=1 ;;
esac

# 1. The global database holds only global tables (no per-collection tables).
#    The expected set is parsed from the migration files (CREATEs minus DROPs,
#    plus schema_versions) so the check does not drift from the schema.
tables_expected() {
    local dir="$1"
    comm -23 \
        <(grep -hoiE 'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?[a-z_]+`?' "$dir"/*.sql \
            | awk '{print $NF}' | tr -d '`' | { cat -; echo schema_versions; } | sort -u) \
        <(grep -hoiE 'DROP\s+TABLE\s+(IF\s+EXISTS\s+)?`?[a-z_]+`?' "$dir"/*.sql \
            | awk '{print $NF}' | tr -d '`' | sort -u) \
        | tr '\n' ' '
}
expected_global=$(tables_expected processing/database/db_global_migrations)
global_tables=$(CH "SHOW TABLES FROM Hoover4_Processing" | sort | tr '\n' ' ')
if [ "$global_tables" = "$expected_global" ]; then
    ok "global DB has exactly the global table set"
else
    fail "global DB table set drifted: got [$global_tables], want [$expected_global]"
fi

# 2. Every collection DB has the full collection table set (parsed from the
#    migration files, plus schema_versions, minus tables later migrations drop).
expected_collection=$(tables_expected processing/database/db_collection_migrations)
for coll in $COLLECTIONS; do
    coll_db="Hoover4_Collection_$coll"
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
#
#    Phase 4 added a third table family, `<shard>_vectors`, and this check was not told:
#    it expected exactly pages+meta, so it has been failing on the live stack ever since
#    — and because §12 requires it green per phase, that made every later phase's
#    verification meaningless. Whether `_vectors` is expected follows the probe, above.
manticore_tables=$(MC "show tables" | awk -F'|' 'NF>2 {gsub(/ /,"",$2); if ($2 != "") print $2}' | sort)
ledger_tables=""
for coll in $COLLECTIONS; do
    shards=$(CH "SELECT shard_name FROM Hoover4_Collection_$coll.manticore_shards FINAL ORDER BY shard_index")
    for shard in $shards; do
        ledger_tables="$ledger_tables${shard}_pages\n${shard}_meta\n"
        [ "$EXPECT_VECTOR_SHARDS" = "1" ] && ledger_tables="$ledger_tables${shard}_vectors\n"
    done
done
ledger_tables=$(printf "%b" "$ledger_tables" | sort)
if [ "$manticore_tables" = "$ledger_tables" ]; then
    ok "Manticore tables exactly match the shard ledgers"
else
    fail "Manticore/ledger mismatch: manticore=[$(echo $manticore_tables)], ledger=[$(echo $ledger_tables)]"
fi

# 5. No shard over the 1 GB text budget (single-document shards may exceed it).
shard_union=""
for coll in $COLLECTIONS; do
    [ -n "$shard_union" ] && shard_union="$shard_union UNION ALL "
    shard_union="$shard_union SELECT shard_name, text_bytes, doc_count
                 FROM Hoover4_Collection_$coll.manticore_shards FINAL"
done
over_budget=$(CH "
    SELECT count() FROM ( $shard_union )
    WHERE text_bytes > $MAX_SHARD_TEXT_BYTES AND doc_count > 1")
if [ "$over_budget" = "0" ]; then
    ok "no shard over the 1 GB text budget"
else
    fail "$over_budget shard(s) over the text budget"
fi

# 6. Every (collection_dataset, file_hash) pair lives in exactly one shard, and the
#    index_state rows (what the writers actually committed) match the actual
#    Manticore row counts. Document identity is the PAIR, not file_hash alone: the
#    same content in two datasets of one collection is indexed twice.
for coll in $COLLECTIONS; do
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
        # `|| true`: an empty shard makes `grep -c` exit 1, which under `set -e` killed
        # the whole run *silently* — no FAIL line, just a script that stopped early and an
        # exit code nobody read as "checks 7 and 8 never ran". Only visible once the
        # collection list stopped being hardcoded and an empty collection entered it.
        n=$(MC "SELECT collection_dataset, file_hash FROM $table
                GROUP BY collection_dataset, file_hash
                LIMIT 100000 OPTION max_matches=100000" | grep -c '^|' || true)
        indexed=$((indexed + n))
    done
    [ "$recorded" = "$indexed" ] && ok "$coll: $indexed indexed docs == $recorded index_state rows" \
        || fail "$coll: $indexed indexed docs != $recorded index_state rows"
done

# 7. The website serves.
code=$(curl -s -o /dev/null -w '%{http_code}' "$WEBSITE_URL/")
[ "$code" = "200" ] && ok "website / returns 200" || fail "website / returned $code"

# 7b. Config-drift guard between the two hosts (hoover4.ini is copied by hand, so it
#     WILL drift). Compare the fingerprint deploy.py rendered on this host against
#     what the ai-services host reports from /health. A mismatch PRINTS both — it
#     does not fail the stack, because a deliberate difference is legal.
main_env="ops/docker/.env"
expected_fp=$(grep -E '^HOOVER4_CONFIG_FINGERPRINT=' "$main_env" 2>/dev/null | cut -d= -f2 || true)
ner_url=$(grep -E '^NER_URL=' "$main_env" 2>/dev/null | cut -d= -f2- || true)
if [ -n "$expected_fp" ] && [ -n "$ner_url" ]; then
    # Probe from INSIDE the worker, not from the host. NER_URL is written in container
    # terms -- on a single-box setup deploy.py rewrites it to
    # `host.containers.internal`, which does not resolve on the host at all. Curling it
    # from here reported "unreachable" against a service that was healthy the whole
    # time, which is a worse answer than no answer.
    health=$(docker exec hoover4-worker curl -s --max-time 5 "${ner_url%/v1}/health" 2>/dev/null || true)
    reported_fp=$(printf '%s' "$health" | { grep -oE '"config_fingerprint":\s*"[a-f0-9]*"' || true; } | grep -oE '[a-f0-9]{8,}' | head -1 || true)
    if [ -z "$health" ]; then
        echo "NOTE - ai-services /health unreachable from the worker ($ner_url); skipping drift check"
    elif [ -z "$reported_fp" ]; then
        echo "NOTE - ai-services /health answers but reports no config_fingerprint; skipping drift check"
    elif [ "$reported_fp" = "$expected_fp" ]; then
        ok "config fingerprint matches on both hosts ($expected_fp)"
    else
        echo "NOTE - hoover4.ini drift: this host rendered $expected_fp, ai-services reports $reported_fp"
    fi
fi

# 7c. The OCR tier answers, and reports the languages it can actually serve.
#     `languages_available` comes from `tesseract --list-langs`, not from config: a
#     dataset configured for a language whose traineddata is not in the image fails per
#     file, and this is the only place that mismatch is visible before it does.
ocr_url=$(grep -E '^OCR_TESSERACT_URL=' "$main_env" 2>/dev/null | cut -d= -f2- || true)
if [ -n "$ocr_url" ]; then
    ocr_health=$(docker exec hoover4-worker curl -s --max-time 5 "${ocr_url%/ocr}/health" 2>/dev/null || true)
    case "$ocr_health" in
        *'"status":"healthy"'*)
            langs=$(printf '%s' "$ocr_health" | grep -oE '"languages_available":\[[^]]*\]' || true)
            ok "tesseract-cpu /health is healthy (${langs:-no languages reported})"
            ;;
        "")  fail "tesseract-cpu /health unreachable from the worker ($ocr_url)" ;;
        *)   fail "tesseract-cpu /health is not healthy: $(printf '%s' "$ocr_health" | head -c 200)" ;;
    esac
else
    echo "NOTE - no OCR_TESSERACT_URL rendered (tesseract_cpu_enabled = false); skipping OCR check"
fi

# 7d. The AI server serves the embedding model the ini asks for, at the ini's
#     dimension, and the reranker answers when enabled. The probe writes
#     embeddings_serving_model/_dim into server_settings — P5/P6 build _vectors tables
#     from that probed dimension, never from the ini, because a Manticore knn_dims
#     cannot be altered after creation.
emb_url=$(grep -E '^EMBEDDINGS_URL=' "$main_env" 2>/dev/null | cut -d= -f2- || true)
rerank_url=$(grep -E '^RERANK_URL=' "$main_env" 2>/dev/null | cut -d= -f2- || true)
if [ -n "$emb_url" ]; then
    if run_step probe-embeddings; then
        ok "embeddings probe wrote server_settings"
    else
        fail "embeddings probe failed"
    fi
    expected_dim=$(grep -E '^EMBEDDINGS_DIM=' "$SCRIPT_DIR/../ai_services/.env" 2>/dev/null | cut -d= -f2 || true)
    served_dim=$(CH "SELECT argMax(value, updated_at) FROM Hoover4_Processing.server_settings WHERE key = 'embeddings_serving_dim'" 2>/dev/null || true)
    if [ -n "$expected_dim" ] && [ "$served_dim" = "$expected_dim" ]; then
        ok "serving embedding dim ($served_dim) matches the ini"
    elif [ -n "$expected_dim" ]; then
        fail "serving embedding dim ($served_dim) != ini embeddings_dim ($expected_dim)"
    fi
else
    echo "NOTE - no EMBEDDINGS_URL rendered (embeddings_provider = none); skipping embeddings probe"
fi
if [ -n "$rerank_url" ]; then
    rerank_out=$(docker exec "$WORKER" curl -s --max-time 60 -X POST "$rerank_url/rerank" \
        -H 'Content-Type: application/json' \
        -d '{"query":"water","documents":["the danube water level","unrelated text"]}' 2>/dev/null || true)
    case "$rerank_out" in
        *'"relevance_score"'*) ok "reranker answers /v1/rerank" ;;
        *) fail "reranker /v1/rerank did not answer: $(printf '%s' "$rerank_out" | head -c 200)" ;;
    esac
else
    echo "NOTE - no RERANK_URL rendered (reranker_enabled = false); skipping rerank probe"
fi

# 7d-bis. The two MCP servers the chat depends on answer their own /health.
#     Both endpoints have existed since phase 2 and nothing probed them, so the only way
#     to learn that metasearch or the browser router was down was a chat answering badly.
#     Probed from the worker, not the host: container-to-container is the path that
#     matters, and "it answers on localhost" proves nothing about it (AGENTS.md).
#
#     Metasearch's /health also reports its configured source list and whether the rerank
#     breaker is open — a source list that has silently shrunk is worth seeing here.
for probe in "metasearch:hoover4-mcp-metasearch:8086" "browser router:hoover4-mcp-browser:8087"; do
    label=${probe%%:*}
    rest=${probe#*:}
    host=${rest%%:*}
    port=${rest##*:}
    out=$(docker exec "$WORKER" curl -s --max-time 10 "http://$host:$port/health" 2>/dev/null || true)
    case "$out" in
        *'"status":"ok"'*) ok "$label /health is ok" ;;
        "")  fail "$label /health unreachable from the worker (http://$host:$port/health)" ;;
        *)   fail "$label /health did not report ok: $(printf '%s' "$out" | head -c 200)" ;;
    esac
done
# The source list is a NOTE rather than a check: which sources are configured is a
# deployment choice, but seeing it next to the other checks is how a shrunk list gets
# noticed at all.
ms_health=$(docker exec "$WORKER" curl -s --max-time 10 "http://hoover4-mcp-metasearch:8086/health" 2>/dev/null || true)
ms_sources=$(printf '%s' "$ms_health" | grep -oE '"sources":\[[^]]*\]' || true)
[ -n "$ms_sources" ] && echo "NOTE - metasearch $ms_sources"

# 7e. Chat artifacts (captured pages, search detail) live under `derived/` in MinIO, and
#     P0_scan_disk must never walk that prefix. If it ever does, each artifact becomes a
#     vfs_files row, is ingested, is captured again by the next chat that opens it, and
#     produces another artifact — forever. `chat_artifacts` is the sole index of those
#     objects, and a `blobs` row pointing into `derived/` is the signature of the loop
#     having started.
derived_blobs=0
for db in $(CH "SELECT name FROM system.databases WHERE name LIKE 'Hoover4\\_Collection\\_%'" 2>/dev/null || true); do
    count=$(CH "SELECT count() FROM ${db}.blobs WHERE s3_path LIKE '%derived/%'" 2>/dev/null || echo 0)
    derived_blobs=$((derived_blobs + count))
done
if [ "$derived_blobs" -eq 0 ]; then
    ok "no blobs row references derived/ (the ingest walker is not seeing chat artifacts)"
else
    fail "$derived_blobs blobs row(s) reference derived/ — P0_scan_disk is walking the artifact prefix"
fi

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
