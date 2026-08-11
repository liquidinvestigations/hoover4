#!/bin/bash
# End-to-end verification of the collections architecture.
#
# Usage: ./verify-stack.sh [--reset]
#
#   --reset   wipe all containers and volumes first (destructive, dev only)
#
# Steps: migrate, create the two canonical collections (testdata + other),
# ingest the three canonical datasets, wait for the pipeline, then assert the
# stack's invariants one by one. Prints OK/FAIL per check and exits non-zero on
# the first failure
# category with failures.
#
# THE INGEST ROOTS ARE DELIBERATELY TINY (~5 MB in total, about a minute of
# pipeline). This script is a gate you run between commits, and a 47-minute run
# is a gate nobody runs. The full 514 MB corpus is one variable away:
#
#     INGEST_ROOT_TESTDATA=/testdata/hoover-testdata/data/disk-files ./verify-stack.sh
#
# which takes roughly 47 minutes. Run it before a release, not between commits.
#
# The four roots are not interchangeable:
#   * INGEST_ROOT_TESTDATA is where check 8's SEARCH_WORD has to live.
#     `pdf-doc-txt` is the default because it is the only folder whose FILENAMES
#     contain `easychair` -- keep that property, or change SEARCH_WORD with it.
#   * INGEST_ROOT_EMAILS carries the email-shaped fixtures (containers with
#     attachments, `Date:` headers, address roles).
#   * INGEST_ROOT_ZIPS is `zip-in-multiple-locations`: two copies of the same
#     archive under different paths. It is the fixture that catches VFS keys
#     that forget which container a path belongs to.
#   * INGEST_ROOT_SHAPES is `many-children`: a 42-level chain (`deep-stuff`) and
#     a folder with 334 sibling directories (`the-directory`). It is the only
#     fixture in the corpus that exercises the tree's ancestor elision, its
#     sibling capping and the breadcrumb's `...` popup. It costs almost nothing
#     to ingest despite its 668 files, because they hold only THREE distinct
#     contents -- the pipeline dedupes by content hash, so it is 3 documents and
#     668 VFS paths. That property is the reason this root is affordable here;
#     if it stops holding, the ingest time is the thing that will say so.
#
# Environment knobs:
#   WEBSITE_URL           default http://localhost:12345 (containerized website)
#   SEARCH_WORD           default easychair (present in the pdf-doc-txt fixture)
#   POLL_TIMEOUT          seconds to wait for ingestion, default 3600
#   INGEST_ROOT_TESTDATA  disk root for testdata/testfiles
#   INGEST_ROOT_EMAILS    disk root for other/emails
#   INGEST_ROOT_ZIPS      disk root for testdata/zips
#   INGEST_ROOT_SHAPES    disk root for testdata/shapes (deep + wide VFS shapes)
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";
cd "$SCRIPT_DIR"

WEBSITE_URL="${WEBSITE_URL:-http://localhost:12345}"
WORKER="${WORKER:-hoover4-worker}"
SEARCH_WORD="${SEARCH_WORD:-easychair}"
POLL_TIMEOUT="${POLL_TIMEOUT:-3600}"
INGEST_ROOT_TESTDATA="${INGEST_ROOT_TESTDATA:-/testdata/hoover-testdata/data/disk-files/pdf-doc-txt}"
INGEST_ROOT_EMAILS="${INGEST_ROOT_EMAILS:-/testdata/hoover-testdata/data/eml-2-attachment}"
INGEST_ROOT_ZIPS="${INGEST_ROOT_ZIPS:-/testdata/hoover-testdata/data/zip-in-multiple-locations}"
# `-` and not `:-`: setting it to the EMPTY string is how the root is switched off,
# which is what the before/after ingest-cost measurement needs.
INGEST_ROOT_SHAPES="${INGEST_ROOT_SHAPES-/testdata/hoover-testdata/data/many-children}"
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
    # `--reset` tears the stack DOWN; it does not bring it back up. Without the deploy
    # that follows, every readiness gate below waits five minutes for a ClickHouse that
    # was never started and the run dies with "ClickHouse did not become healthy in time"
    # -- which reads as a broken database rather than as a missing step.
    ./reset-docker.sh
    ../deploy
fi

echo "== waiting for ClickHouse, Manticore, the worker and Temporal =="
wait_for_clickhouse
wait_for_manticore
wait_for_worker
wait_for_temporal

# The fixture paths below are pinned to an upstream revision that nothing in this
# repository otherwise records, because testdata/ is gitignored. Say so before ingesting
# rather than after a check fails for a reason that is not in any diff.
echo "== testdata =="
./fetch-testdata.sh --check || fail "testdata fixtures are missing — run ./fetch-testdata.sh"

echo "== migrate =="
run_step migrate

echo "== ensure collections =="
ensure_collection_row testdata "Test Data"
ensure_collection_row other "Other Collection"
run_step ensure-collection testdata
run_step ensure-collection other

ingest_dataset() {
    local coll="$1" ds="$2" root="$3"
    # An empty root means "not this run" -- how the shapes fixture is switched off to
    # measure what it costs, and how any root can be dropped without editing the script.
    if [ -z "$root" ]; then
        echo "${coll}_${ds}: no root configured, skipping"
        return 0
    fi
    if [ -n "$(CH "SELECT collection_dataset FROM Hoover4_Processing.dataset FINAL
                   WHERE collection_dataset = '${coll}_${ds}' AND is_deleted = 0")" ]; then
        echo "${coll}_${ds} already registered, skipping ingest"
        return 0
    fi
    echo "     ${coll}_${ds} <- $root"
    run_step add-disk-dataset "$coll" "$ds" "$root"
}

# These block until each dataset is fully ingested, which is correct: the three
# stages (scan, compute plans, execute plans) must run in order, and only the
# CLI sequences them today. It does mean the ingest is tied to this script --
# the 47-minute run that died at EXIT=137 was a redeploy SIGKILLing exactly this
# docker exec while the workflows carried on server-side. DO NOT redeploy while
# this is running; the poll loop below is the safety net if you do.
echo "== ingest canonical datasets =="
ingest_dataset testdata testfiles "$INGEST_ROOT_TESTDATA"
ingest_dataset other    emails    "$INGEST_ROOT_EMAILS"
ingest_dataset testdata zips      "$INGEST_ROOT_ZIPS"
ingest_dataset testdata shapes    "$INGEST_ROOT_SHAPES"

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
#    There are FOUR table families, not two. `<shard>_vectors` is the third: a check
#    that expects exactly pages+meta fails on every live stack, and a gate that is red
#    for a known reason stops being read at all. Whether `_vectors` is expected follows
#    the probe, above.
#    The fourth is `<collectionname>_vfs` — one table per collection
#    rather than per shard (it holds one small row per VFS node and is never sharded). It
#    has no ledger row to derive from, so it is expected for every collection that has
#    any shard at all: the same indexing run that opens a shard also creates it.
manticore_tables=$(MC "show tables" | awk -F'|' 'NF>2 {gsub(/ /,"",$2); if ($2 != "") print $2}' | sort)
ledger_tables=""
for coll in $COLLECTIONS; do
    shards=$(CH "SELECT shard_name FROM Hoover4_Collection_$coll.manticore_shards FINAL ORDER BY shard_index")
    for shard in $shards; do
        ledger_tables="$ledger_tables${shard}_pages\n${shard}_meta\n"
        [ "$EXPECT_VECTOR_SHARDS" = "1" ] && ledger_tables="$ledger_tables${shard}_vectors\n"
    done
    [ -n "$shards" ] && ledger_tables="$ledger_tables${coll}_vfs\n"
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

# 6b. Every indexed document has exactly one `filename_index` pages row.
#     That row is what makes a query for a FILENAME find the document. It is written by a
#     writer of its own, so a failure there is invisible: search still works, filenames
#     just stop matching, and nothing says so. Comparing against `index_state` (what the
#     writers actually committed) is the only check that notices.
for coll in $COLLECTIONS; do
    recorded=$(CH "SELECT count() FROM Hoover4_Collection_$coll.index_state FINAL")
    filename_rows=0
    for table in $(MC "show tables" | grep -oE "${coll}_[0-9]+_pages"); do
        n=$(MC "SELECT collection_dataset, file_hash FROM $table
                WHERE extracted_by = 'filename_index'
                GROUP BY collection_dataset, file_hash
                LIMIT 100000 OPTION max_matches=100000" | grep -c '^|' || true)
        filename_rows=$((filename_rows + n))
    done
    [ "$recorded" = "$filename_rows" ] && ok "$coll: $filename_rows filename rows == $recorded index_state rows" \
        || fail "$coll: $filename_rows filename rows != $recorded index_state rows"
done

# 6c. The structure index matches the materialised tree it is built from. A mismatch
#     means the tree sidebar is showing a different corpus from the one the filters use.
for coll in $COLLECTIONS; do
    ch_nodes=$(CH "SELECT count() FROM (SELECT DISTINCT collection_dataset, node_key
                   FROM Hoover4_Collection_$coll.vfs_nodes FINAL)")
    mc_nodes=$(MC "SELECT count(*) FROM ${coll}_vfs" 2>/dev/null | awk -F'|' 'NF>2 {gsub(/ /,"",$2); print $2}' | tail -1)
    mc_nodes=${mc_nodes:-0}
    [ "$ch_nodes" = "$mc_nodes" ] && ok "$coll: ${coll}_vfs has $mc_nodes rows == $ch_nodes vfs_nodes" \
        || fail "$coll: ${coll}_vfs has $mc_nodes rows but vfs_nodes has $ch_nodes"
done

# 6d. No meta row carries a size below the "unknown" sentinel. -1 means "this document
#     exists in file_types but in no vfs_files row"; anything below it is a writer bug,
#     and it would silently join the "under 1 MB" bucket.
bad_sizes=0
for coll in $COLLECTIONS; do
    for table in $(MC "show tables" | grep -oE "${coll}_[0-9]+_meta"); do
        n=$(MC "SELECT file_hash FROM $table WHERE file_size_bytes < -1 LIMIT 1000" | grep -c '^|' || true)
        bad_sizes=$((bad_sizes + n))
    done
done
[ "$bad_sizes" = "0" ] && ok "no meta row has file_size_bytes < -1" \
    || fail "$bad_sizes meta row(s) have file_size_bytes < -1"

# 6e. `zip-in-multiple-locations` is TWO copies of one archive. Because containers are
#     content-addressed they share a container_hash, so a VFS model with a single parent
#     picks one location and makes the other one's folder filter return nothing.
#     Filtering on each location's folder node must find the archive's
#     child under BOTH.
if [ -n "$(CH "SELECT collection_dataset FROM Hoover4_Processing.dataset FINAL
               WHERE collection_dataset = 'testdata_zips' AND is_deleted = 0")" ]; then
    for location in location-1 location-2; do
        node_key=$(printf 'testdata_zips\037\037/%s' "$location")
        term_id=$(CH "SELECT term_id FROM Hoover4_Collection_testdata.string_term_text_to_id FINAL
                      WHERE collection_dataset = 'testdata_zips' AND term_field = 'vfs_node'
                      AND term_value = '$node_key' LIMIT 1")
        if [ -z "$term_id" ]; then
            fail "zip fixture: no vfs_node term for /$location"
            continue
        fi
        found=0
        for table in $(MC "show tables" | grep -oE "testdata_[0-9]+_meta"); do
            n=$(MC "SELECT file_hash FROM $table
                    WHERE collection_dataset = 'testdata_zips' AND file_paths = $term_id
                    LIMIT 1000" | grep -c '^|' || true)
            found=$((found + n))
        done
        # The archive itself plus the child.txt inside it: at least 2 documents are
        # reachable through each location.
        [ "$found" -ge 2 ] && ok "zip fixture: /$location reaches $found documents" \
            || fail "zip fixture: /$location reaches only $found documents (expected >= 2)"
    done
fi

# 6f. The `shapes` fixture is the only deep/wide tree in the corpus, and the tree UI's
#     ancestor elision (MAX_VISIBLE_ANCESTORS=8), sibling capping (10 each side) and the
#     breadcrumb `...` popup (MAX_CRUMBS_SHOWN=3) are all invisible without it. Assert the
#     SHAPE, not the row count: the point is that one path is deeper than the elision
#     threshold and one folder is wider than the sibling cap.
if [ -n "$(CH "SELECT collection_dataset FROM Hoover4_Processing.dataset FINAL
               WHERE collection_dataset = 'testdata_shapes' AND is_deleted = 0")" ]; then
    deepest=$(CH "SELECT max(depth) FROM Hoover4_Collection_testdata.vfs_nodes FINAL
                  WHERE collection_dataset = 'testdata_shapes'")
    [ "${deepest:-0}" -ge 20 ] && ok "shapes fixture: deepest VFS node is at depth $deepest" \
        || fail "shapes fixture: deepest VFS node is at depth ${deepest:-0} (expected >= 20)"

    widest=$(CH "SELECT max(n) FROM (
                    SELECT count() AS n FROM Hoover4_Collection_testdata.vfs_nodes FINAL
                    WHERE collection_dataset = 'testdata_shapes' AND kind = 'dir'
                    GROUP BY parent_key)")
    [ "${widest:-0}" -ge 100 ] && ok "shapes fixture: widest folder has $widest sibling directories" \
        || fail "shapes fixture: widest folder has ${widest:-0} sibling directories (expected >= 100)"

    # The reason this root is cheap: 668 files, 3 distinct contents. If dedupe regresses
    # this becomes 668 documents and the ~1 minute gate becomes something nobody runs.
    docs=$(CH "SELECT count() FROM Hoover4_Collection_testdata.index_state FINAL
               WHERE collection_dataset = 'testdata_shapes'")
    [ "${docs:-0}" -le 20 ] && ok "shapes fixture: $docs documents from 668 deduped files" \
        || fail "shapes fixture: $docs documents (expected <= 20 — content dedupe regressed?)"
fi

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

# 7c-bis. The searchable-PDF assembler. It owns no engine — it renders pages and calls the
#     tier above — so the interesting half of its /health is `engines`, which reports which
#     engines it has an ENDPOINT for. A dataset configured for an engine with no endpoint
#     produces no OCR'd PDF at all, and this is where that mismatch is visible.
ocrpdf_url=$(grep -E '^OCR_PDF_URL=' "$main_env" 2>/dev/null | cut -d= -f2- || true)
if [ -n "$ocrpdf_url" ]; then
    ocrpdf_health=$(docker exec "$WORKER" curl -s --max-time 5 "${ocrpdf_url%/ocr-pdf}/health" 2>/dev/null || true)
    case "$ocrpdf_health" in
        *'"status":"healthy"'*)
            engines=$(printf '%s' "$ocrpdf_health" | grep -oE '"engines":\{[^}]*\}' || true)
            ok "ocr-pdf /health is healthy (${engines:-no engines reported})"
            ;;
        "")  fail "ocr-pdf /health unreachable from the worker ($ocrpdf_url)" ;;
        *)   fail "ocr-pdf /health is not healthy: $(printf '%s' "$ocrpdf_health" | head -c 200)" ;;
    esac
else
    echo "NOTE - no OCR_PDF_URL rendered (ocr_pdf_enabled = false); skipping ocr-pdf check"
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
#     Without these probes the only way to learn that metasearch or the browser router
#     is down is a chat answering badly, which nobody attributes to a dead sidecar.
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

# 7e. Everything derived lives under `derived/` in MinIO, and P0_scan_disk must never walk
#     that prefix. Two writers are covered by this one `%derived/%` pattern:
#       * chat artifacts (captured pages, search detail) under `derived/chat/…`
#       * OCR'd PDFs under `derived/ocr-pdf/<dataset>/<pdf_hash>/<engine>+<langs>.pdf`
#     If the walker ever sees either, the object becomes a vfs_files row, is ingested, is
#     re-derived by the stage that produced it, and produces another object — forever, and
#     for the OCR'd PDFs that loop bills OCR time on every lap. `chat_artifacts` and
#     `pdf_ocr_results` are the sole indexes of those objects, and a `blobs` row pointing
#     into `derived/` is the signature of the loop having started.
derived_blobs=0
for db in $(CH "SELECT name FROM system.databases WHERE name LIKE 'Hoover4\\_Collection\\_%'" 2>/dev/null || true); do
    count=$(CH "SELECT count() FROM ${db}.blobs WHERE s3_path LIKE '%derived/%'" 2>/dev/null || echo 0)
    derived_blobs=$((derived_blobs + count))
done
if [ "$derived_blobs" -eq 0 ]; then
    ok "no blobs row references derived/ (the walker sees neither chat artifacts nor OCR'd PDFs)"
else
    fail "$derived_blobs blobs row(s) reference derived/ — P0_scan_disk is walking the derived prefix"
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
