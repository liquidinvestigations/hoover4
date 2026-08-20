#!/bin/bash
# Repeatable ingest benchmark. Sibling of verify-stack.sh.
#
# Usage: ./bench-ingest.sh <fixture> [--label NAME] [--keep]
#                            [--expected-plans N] [--expected-files N]
#                            [--search-word WORD] [--parse-only]
#
#   fixture   smoke | medium | large   (or an explicit path under the testdata mount)
#   --label   tag written into Hoover4_Processing.bench_runs; defaults to git sha
#   --keep    do not purge the dataset afterwards
#
# Collection `bench`, dataset `bench_<fixture>` (custom path: slug of the basename).
# Idempotent: purges the dataset first -- rows AND the `dataset` registry row, which
# `purge-dataset` leaves behind -- and asserts the tables are empty.
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )"
cd "$SCRIPT_DIR"

WORKER="${WORKER:-hoover4-worker}"
TESTDATA_ROOT="/testdata/enron-kaminski-v"
COLLECTION="bench"
SEARCH_WORD="${SEARCH_WORD:-enron}"
POLL_TIMEOUT="${POLL_TIMEOUT:-3600}"

website_url_default() {
    local env_file="ops/docker/.env" bind
    bind=$(grep -E '^WEBSITE_BIND_IP=' "$env_file" 2>/dev/null | cut -d= -f2- || true)
    case "$bind" in
        ""|0.0.0.0) echo "http://localhost:12345" ;;
        *)          echo "http://$bind:12345" ;;
    esac
}
WEBSITE_URL="${WEBSITE_URL:-$(website_url_default)}"
WEB() { curl -s --max-time 30 "$@" || true; }

CH() { docker exec clickhouse clickhouse-client -u hoover4 --password hoover4 -q "$1"; }
MC() { docker exec manticore mysql -h0 -P9306 -N -B -e "$1" 2>/dev/null; }

ok()   { echo "OK   - $1"; }
fail() { echo "FAIL - $1"; exit 1; }

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

usage() { sed -n '2,13p' "$0"; }

FIXTURE=""
LABEL=""
KEEP=0
PARSE_ONLY=0
EXPECTED_PLANS=""
EXPECTED_FILES=""

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --label) LABEL="$2"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --parse-only) PARSE_ONLY=1; shift ;;
        --expected-plans) EXPECTED_PLANS="$2"; shift 2 ;;
        --expected-files) EXPECTED_FILES="$2"; shift 2 ;;
        --search-word) SEARCH_WORD="$2"; shift 2 ;;
        --*) echo "unknown flag: $1" >&2; usage >&2; exit 2 ;;
        *)
            if [ -n "$FIXTURE" ]; then echo "unexpected extra arg: $1" >&2; exit 2; fi
            FIXTURE="$1"; shift ;;
    esac
done

if [ -z "$FIXTURE" ]; then usage >&2; exit 2; fi

case "$FIXTURE" in
    smoke)
        SUB="inbox"
        DEFAULT_PLANS=1
        DEFAULT_FILES=560
        SLUG="smoke"
        ;;
    medium)
        SUB="discussion_threads"
        DEFAULT_PLANS=6
        DEFAULT_FILES=5550
        SLUG="medium"
        ;;
    large)
        SUB=""
        DEFAULT_PLANS=22
        DEFAULT_FILES=21291
        SLUG="large"
        ;;
    *)
        # Explicit path under the testdata mount (absolute in the worker, or relative
        # to TESTDATA_ROOT). Dataset name is the slug of the basename.
        SUB="${FIXTURE#/testdata/enron-kaminski-v/}"
        SUB="${SUB#/testdata/}"
        base=$(basename "$FIXTURE")
        SLUG=$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]\+/_/g' | sed 's/^_\|_$//g')
        [ -n "$SLUG" ] || SLUG="custom"
        DEFAULT_PLANS=""
        DEFAULT_FILES=""
        ;;
esac

if [ -n "$SUB" ]; then
    ROOT="$TESTDATA_ROOT/$SUB"
else
    ROOT="$TESTDATA_ROOT"
fi
# A path that already starts at /testdata wins.
case "$FIXTURE" in
    /testdata/*) ROOT="$FIXTURE" ;;
esac

DS="${COLLECTION}_${SLUG}"
DB="Hoover4_Collection_${COLLECTION}"
[ -n "$LABEL" ] || LABEL="$(git -C "$SCRIPT_DIR/.." rev-parse --short HEAD 2>/dev/null || echo unknown)"
GIT_SHA="$(git -C "$SCRIPT_DIR/.." rev-parse --short HEAD 2>/dev/null || echo unknown)"
PLANS_EXPECT="${EXPECTED_PLANS:-$DEFAULT_PLANS}"
FILES_EXPECT="${EXPECTED_FILES:-$DEFAULT_FILES}"

if [ "$PARSE_ONLY" -eq 1 ]; then
    printf 'fixture=%s slug=%s root=%s dataset=%s label=%s keep=%s expected_plans=%s expected_files=%s search_word=%s\n' \
        "$FIXTURE" "$SLUG" "$ROOT" "$DS" "$LABEL" "$KEEP" "${PLANS_EXPECT:-unset}" "${FILES_EXPECT:-unset}" "$SEARCH_WORD"
    exit 0
fi

if ! printf '%s' "$COLLECTION" | grep -qE '^[a-z0-9_]{1,48}$'; then
    echo "refusing collectionname: $COLLECTION" >&2; exit 2
fi
if ! printf '%s' "$DS" | grep -qE '^[a-z0-9_]{1,96}$'; then
    echo "refusing dataset id: $DS" >&2; exit 2
fi

if ! docker exec "$WORKER" uv run main.py version >/dev/null 2>&1; then
    fail "worker $WORKER is not usable"
fi

if [ -z "$EXPECTED_FILES" ]; then
    disk_n=$(docker exec "$WORKER" sh -c "find '$ROOT' -type f | wc -l" | tr -d ' ')
    FILES_EXPECT="${disk_n:-$FILES_EXPECT}"
fi

echo "== refuse if another dataset is processing =="
other=""
while IFS= read -r dbname; do
    [ -n "$dbname" ] || continue
    hit=$(CH "SELECT distinct collection_dataset FROM ${dbname}.processing_task_inflight
              WHERE sampled_at > now() - INTERVAL 15 SECOND
                AND collection_dataset != '${DS}'" 2>/dev/null || true)
    if [ -n "$hit" ]; then
        other="$other $hit"
    fi
done < <(CH "SELECT name FROM system.databases WHERE name LIKE 'Hoover4\\_Collection\\_%'")
if [ -n "${other// /}" ]; then
    fail "another dataset is processing (inflight < 15s):$other"
fi
ok "no other dataset has a fresh inflight sample"

echo "== ensure collection $COLLECTION =="
run_step create-collection "$COLLECTION" --fullname "Bench"

echo "== purge $DS =="
run_step purge-dataset "$COLLECTION" "$DS" --apply --registered || true
# purge-dataset deletes rows and deliberately leaves the `dataset` registry row --
# removing one belongs to the admin UI. A benchmark needs the whole dataset gone or
# the next `add-disk-dataset` refuses the name, so drop the registry row here. Safe
# because both ids above are validated and the collection is this harness's own.
CH "ALTER TABLE Hoover4_Processing.dataset DELETE WHERE collection_dataset = '${DS}'"
for _ in $(seq 1 30); do
    left=$(CH "SELECT count() FROM Hoover4_Processing.dataset FINAL WHERE collection_dataset = '${DS}' AND is_deleted = 0")
    [ "$left" = "0" ] && break
    sleep 1
done
[ "$left" = "0" ] || fail "dataset registry row for $DS survived the purge"
ok "dataset registry row for $DS is gone"

# `add-disk-dataset` starts ingest-disk-<ds> with ALLOW_DUPLICATE_FAILED_ONLY, so a
# COMPLETED run of the same fixture reserves that id for the whole Temporal retention
# window and the next benchmark is refused. Production wants that refusal; a benchmark
# wants the id back. Deleting the closed execution frees it. Children are started with
# the default reuse policy and need no help.
docker exec temporal temporal workflow delete --address temporal:7233 \
    --workflow-id "ingest-disk-${DS}" >/dev/null 2>&1 || true
for _ in $(seq 1 30); do
    docker exec temporal temporal workflow describe --address temporal:7233 \
        --workflow-id "ingest-disk-${DS}" >/dev/null 2>&1 || break
    sleep 1
done
ok "ingest-disk-${DS} is free to start again"

empty_or_fail() {
    local table="$1"
    local n
    n=$(CH "SELECT count() FROM ${DB}.${table} FINAL WHERE collection_dataset = '${DS}'" 2>/dev/null || echo 0)
    [ "$n" = "0" ] || fail "$table still has $n rows for $DS after purge"
    ok "$table is empty for $DS"
}
empty_or_fail blobs
empty_or_fail vfs_files
empty_or_fail text_content
empty_or_fail index_state

echo "== record start =="
STARTED_AT=$(date -u +"%Y-%m-%d %H:%M:%S")
START_EPOCH=$(date +%s)
START_EVENTS=$(CH "SELECT event, value FROM system.events WHERE event IN ('Query','SelectQuery','InsertQuery','AsyncInsertQuery','InsertedRows','MergedRows') FORMAT TSV")
echo "$START_EVENTS"

echo "== ingest $DS <- $ROOT =="
run_step add-disk-dataset "$COLLECTION" "$SLUG" "$ROOT" --wait

echo "== wait for quiescence =="
deadline=$(( $(date +%s) + POLL_TIMEOUT ))
while true; do
    plans=$(CH "SELECT uniqExact(plan_hash) FROM ${DB}.processing_plans FINAL WHERE collection_dataset = '${DS}'" 2>/dev/null || echo 0)
    finished=$(CH "SELECT uniqExact(plan_hash) FROM ${DB}.processing_plan_finished FINAL WHERE collection_dataset = '${DS}'" 2>/dev/null || echo 0)
    inflight=$(CH "SELECT count() FROM ${DB}.processing_task_inflight
                   WHERE collection_dataset = '${DS}'
                     AND sampled_at > now() - INTERVAL 15 SECOND" 2>/dev/null || echo 0)
    if [ "$plans" -gt 0 ] && [ "$plans" = "$finished" ] && [ "$inflight" = "0" ]; then
        ok "quiescent: $finished/$plans plans, no fresh inflight"
        break
    fi
    if [ "$(date +%s)" -gt "$deadline" ]; then
        fail "not quiescent after ${POLL_TIMEOUT}s (finished=$finished plans=$plans inflight=$inflight)"
    fi
    sleep 5
done

END_EPOCH=$(date +%s)
WALL_MS=$(( (END_EPOCH - START_EPOCH) * 1000 ))
END_EVENTS=$(CH "SELECT event, value FROM system.events WHERE event IN ('Query','SelectQuery','InsertQuery','AsyncInsertQuery','InsertedRows','MergedRows') FORMAT TSV")
echo "wall_clock_ms=$WALL_MS"
echo "$END_EVENTS"

echo "== task-time-report =="
./task-time-report.sh "$COLLECTION" --dataset "$DS" --since "$STARTED_AT" || true

summed=$(CH "SELECT ifNull(sum(run_time_ms), 0) FROM ${DB}.processing_task_runs WHERE collection_dataset = '${DS}' AND started_at >= toDateTime64('${STARTED_AT}', 3)")
overhead=$(CH "SELECT ifNull(round(quantileExact(0.5)(run_time_ms)), 0) FROM ${DB}.processing_task_runs WHERE collection_dataset = '${DS}' AND task_name = 'detect_mime_from_name' AND started_at >= toDateTime64('${STARTED_AT}', 3)")
busy=$(CH "SELECT ifNull(round(avg(busy_ms)), 0) FROM (
    SELECT hash, sum(run_time_ms) AS busy_ms
    FROM ${DB}.processing_task_runs
    WHERE collection_dataset = '${DS}' AND hash != '' AND started_at >= toDateTime64('${STARTED_AT}', 3)
    GROUP BY hash)")
wallf=$(CH "SELECT ifNull(round(avg(wall_ms)), 0) FROM (
    SELECT hash,
           max(toUnixTimestamp64Milli(started_at) + toInt64(run_time_ms))
             - min(toUnixTimestamp64Milli(started_at)) AS wall_ms
    FROM ${DB}.processing_task_runs
    WHERE collection_dataset = '${DS}' AND hash != '' AND started_at >= toDateTime64('${STARTED_AT}', 3)
    GROUP BY hash)")
p6=$(CH "SELECT count() FROM ${DB}.processing_task_runs WHERE collection_dataset = '${DS}' AND task_name = 'index_vfs_structure' AND started_at >= toDateTime64('${STARTED_AT}', 3)")
errn=$(CH "SELECT count() FROM ${DB}.processing_errors WHERE collection_dataset = '${DS}'")
files_got=$(CH "SELECT count() FROM ${DB}.vfs_files FINAL WHERE collection_dataset = '${DS}'")
plans_got=$(CH "SELECT uniqExact(plan_hash) FROM ${DB}.processing_plans FINAL WHERE collection_dataset = '${DS}'")
parallelism="0"
if [ "$WALL_MS" -gt 0 ]; then
    parallelism=$(CH "SELECT round(${summed} / ${WALL_MS}, 2)")
fi

echo "== assertions =="
if [ -z "$PLANS_EXPECT" ]; then
    fail "no expected plan count (pass --expected-plans N for a custom fixture)"
fi
[ "$plans_got" = "$PLANS_EXPECT" ] \
    && ok "uniqExact(plan_hash)=$plans_got matches expected $PLANS_EXPECT" \
    || fail "uniqExact(plan_hash)=$plans_got, expected $PLANS_EXPECT"

finished=$(CH "SELECT uniqExact(plan_hash) FROM ${DB}.processing_plan_finished FINAL WHERE collection_dataset = '${DS}'")
[ "$finished" = "$plans_got" ] \
    && ok "processing_plan_finished=$finished equals processing_plans" \
    || fail "processing_plan_finished=$finished but processing_plans=$plans_got"

[ "$errn" = "0" ] && ok "processing_errors=0" || fail "processing_errors=$errn"

if [ -z "$FILES_EXPECT" ]; then
    fail "no expected file count (pass --expected-files N for a custom fixture)"
fi
[ "$files_got" = "$FILES_EXPECT" ] \
    && ok "vfs_files=$files_got matches expected $FILES_EXPECT" \
    || fail "vfs_files=$files_got, expected $FILES_EXPECT"

missing_text=$(CH "SELECT count() FROM ${DB}.blobs b FINAL
    LEFT ANTI JOIN ${DB}.text_content t FINAL ON t.collection_dataset = b.collection_dataset AND t.file_hash = b.blob_hash
    WHERE b.collection_dataset = '${DS}'")
[ "$missing_text" = "0" ] \
    && ok "every blobs row has >=1 text_content row" \
    || fail "$missing_text blobs row(s) have no text_content"

provider=$(docker exec "$WORKER" printenv NER_PROVIDER 2>/dev/null || true)
provider="${provider:-gpu}"
[ "$provider" = "both" ] && provider="gpu"
case "$provider" in
    gpu) NLP_MODEL="ner-gpu-xlmr" ;;
    spacy) NLP_MODEL="ner-spacy-xx" ;;
    *) NLP_MODEL="ner-${provider}" ;;
esac
missing_nlp=$(CH "SELECT count() FROM ${DB}.text_content t FINAL
    LEFT ANTI JOIN ${DB}.nlp_processed n FINAL
      ON n.collection_dataset = t.collection_dataset AND n.file_hash = t.file_hash
     AND n.extracted_by = t.extracted_by AND n.page_id = t.page_id
     AND n.nlp_model = '${NLP_MODEL}'
    WHERE t.collection_dataset = '${DS}'")
[ "$missing_nlp" = "0" ] \
    && ok "nlp_processed covers every text_content segment for $NLP_MODEL" \
    || fail "$missing_nlp text_content segment(s) missing nlp_processed for $NLP_MODEL"

chunks=$(CH "SELECT count() FROM ${DB}.text_chunks FINAL WHERE collection_dataset = '${DS}'")
vectors=$(CH "SELECT count() FROM ${DB}.text_chunk_vectors FINAL WHERE collection_dataset = '${DS}'")
[ "$chunks" -gt 0 ] && [ "$vectors" -gt 0 ] \
    && ok "text_chunks=$chunks text_chunk_vectors=$vectors" \
    || fail "text_chunks=$chunks text_chunk_vectors=$vectors (both must be non-empty)"

missing_chunks=$(CH "SELECT uniqExact(file_hash) FROM ${DB}.text_content FINAL WHERE collection_dataset = '${DS}'
    AND file_hash NOT IN (SELECT file_hash FROM ${DB}.text_chunks FINAL WHERE collection_dataset = '${DS}')")
missing_vecs=$(CH "SELECT uniqExact(file_hash) FROM ${DB}.text_content FINAL WHERE collection_dataset = '${DS}'
    AND file_hash NOT IN (SELECT file_hash FROM ${DB}.text_chunk_vectors FINAL WHERE collection_dataset = '${DS}')")
[ "$missing_chunks" = "0" ] && [ "$missing_vecs" = "0" ] \
    && ok "text_chunks and text_chunk_vectors cover every file with text" \
    || fail "files missing chunks=$missing_chunks vectors=$missing_vecs"

missing_index=$(CH "SELECT uniqExact(blob_hash) FROM ${DB}.blobs FINAL WHERE collection_dataset = '${DS}'
    AND blob_hash NOT IN (SELECT file_hash FROM ${DB}.index_state FINAL WHERE collection_dataset = '${DS}')")
[ "$missing_index" = "0" ] \
    && ok "index_state covers every file" \
    || fail "$missing_index file(s) missing from index_state"

vfs_ch=$(CH "SELECT count() FROM ${DB}.vfs_nodes FINAL WHERE collection_dataset = '${DS}'")
vfs_mc=$(MC "SELECT count(*) FROM ${COLLECTION}_vfs WHERE collection_dataset='${DS}'" | grep -oE '[0-9]+' | head -1)
[ "$vfs_ch" = "$vfs_mc" ] && [ -n "$vfs_mc" ] \
    && ok "${COLLECTION}_vfs count=$vfs_mc equals vfs_nodes" \
    || fail "${COLLECTION}_vfs count=${vfs_mc:-missing} but vfs_nodes=$vfs_ch"

grep_first() {
    local matches
    matches=$(grep -a -oE "$1" || true)
    { printf '%s\n' "$matches" | grep '/' || printf '%s\n' "$matches"; } | head -1
}
resolve_url() {
    local href="${1#.}"; href="${href#/}"; href="${href#./}"; printf '/%s' "$href"
}
api_path=""
whoami_path=""
js_href=$(WEB "$WEBSITE_URL/" | grep_first '[a-zA-Z0-9_./-]*frontend[a-zA-Z0-9_-]*\.js')
if [ -n "$js_href" ]; then
    wasm_href=$(WEB "$WEBSITE_URL$(resolve_url "$js_href")" \
        | grep_first '[a-zA-Z0-9_./-]*frontend_bg[a-zA-Z0-9_-]*\.wasm')
    if [ -n "$wasm_href" ]; then
        wasm_tmp=$(mktemp)
        WEB -o "$wasm_tmp" "$WEBSITE_URL$(resolve_url "$wasm_href")"
        if [ "$(head -c 4 "$wasm_tmp" | tr -d '\0')" = "asm" ]; then
            api_path=$(grep_first '/api/search_for_results_hit_count[0-9]+' < "$wasm_tmp")
            whoami_path=$(grep_first '/api/whoami[0-9]+' < "$wasm_tmp")
        fi
        rm -f "$wasm_tmp"
    fi
fi
if [ -z "$api_path" ] || [ -z "$whoami_path" ]; then
    fail "could not discover search/whoami URLs from the WASM bundle at $WEBSITE_URL"
fi
cookie_jar=$(mktemp)
WEB -c "$cookie_jar" -X POST "$WEBSITE_URL$whoami_path" \
    -H 'Content-Type: application/json' -d '[]' >/dev/null
body='[{"collection_datasets":["'"$DS"'"],"query_string":"'"$SEARCH_WORD"'","facet_filters":{}}]'
response=$(WEB -b "$cookie_jar" -X POST "$WEBSITE_URL$api_path" -H 'Content-Type: application/json' -d "$body")
rm -f "$cookie_jar"
hits=$(printf '%s' "$response" | grep -oE '"total":[0-9]+' | grep -oE '[0-9]+' | head -1)
if [ -n "$hits" ] && [ "$hits" -gt 0 ]; then
    ok "search for '$SEARCH_WORD' returned $hits hits"
else
    fail "search for '$SEARCH_WORD' returned: $response"
fi

echo "== record bench_runs =="
CH "INSERT INTO Hoover4_Processing.bench_runs
    (label, fixture, started_at, wall_clock_ms, summed_task_ms, achieved_parallelism,
     files, plans, overhead_floor_p50_ms, per_file_busy_ms, per_file_wall_ms,
     p6_vfs_runs, errors, git_sha)
    VALUES
    ('${LABEL}', '${SLUG}', toDateTime64('${STARTED_AT}', 3), ${WALL_MS}, ${summed}, ${parallelism},
     ${files_got}, ${plans_got}, ${overhead}, ${busy}, ${wallf},
     ${p6}, ${errn}, '${GIT_SHA}')"
ok "wrote Hoover4_Processing.bench_runs label=$LABEL fixture=$SLUG wall_ms=$WALL_MS"

if [ "$KEEP" -eq 0 ]; then
    echo "== purge $DS =="
    run_step purge-dataset "$COLLECTION" "$DS" --apply --registered
    ok "purged $DS"
else
    echo "keeping $DS (--keep)"
fi
