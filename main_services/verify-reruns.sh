#!/usr/bin/env bash
# Verify retry selection and recovery on the local development stack.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR"
SELF="$SCRIPT_DIR/$(basename -- "${BASH_SOURCE[0]:-$0}")"

if [ "${1:-}" != "--case" ]; then
    trap 'docker start hoover4-regex-entity-scanner >/dev/null 2>&1 || true' EXIT
fi

STATE_FILE="${VERIFY_RERUNS_STATE_FILE:-${TMPDIR:-/tmp}/hoover4-verify-reruns-$$.state}"
DEADLINE_EPOCH="${VERIFY_RERUNS_DEADLINE_EPOCH:-0}"
CH_SCRIPT="../.agents/skills/querying-the-datastores/scripts/ch.sh"
COLLECTION_DB="Hoover4_Collection_reruns"
DATASET="reruns_probe"
SCANNER="hoover4-regex-entity-scanner"
FIRST_OP=""
REPEAT_OP=""
THIRD_OP=""
RECOVERY_OP=""
IMAGES_OP=""
FAILURE_OP=""
PROBE_HASH=""
OP_ID=""

url_host() {
    local url="$1" rest host
    rest="${url#*://}"
    rest="${rest%%/*}"
    if [ "${rest#\[}" != "$rest" ]; then
        host="${rest#\[}"
        host="${host%%]*}"
        printf '%s' "$host"
        return
    fi
    printf '%s' "${rest%%:*}"
}

website_url_default() {
    local bind
    bind="$(grep -E '^WEBSITE_BIND_IP=' ../ops/docker/.env 2>/dev/null | cut -d= -f2- || true)"
    case "$bind" in
        ""|0.0.0.0) printf '%s' 'http://localhost:12345' ;;
        *) printf '%s' "http://$bind:12345" ;;
    esac
}

website_url_is_local() {
    local host bind
    host="$(url_host "$1")"
    case "$host" in
        localhost|127.0.0.1|0.0.0.0|::1) return 0 ;;
    esac
    bind="$(grep -E '^WEBSITE_BIND_IP=' ../ops/docker/.env 2>/dev/null | cut -d= -f2- || true)"
    [ -n "$bind" ] && [ "$host" = "$bind" ] && return 0
    case "$host" in
        hoover4-*.*) ;;
        hoover4-*) return 0 ;;
    esac
    return 1
}

WEBSITE_URL="${WEBSITE_URL:-$(website_url_default)}"
if ! website_url_is_local "$WEBSITE_URL"; then
    printf '%s\n' 'error: verify-reruns.sh refuses a non-local target.' >&2
    printf '%s\n' '       It writes fixture data to the stack it verifies.' >&2
    printf '%s\n' '       Use a loopback URL or the local WEBSITE_BIND_IP.' >&2
    exit 2
fi

ch_global() {
    FORMAT=TSV "$CH_SCRIPT" "$1"
}

ch_collection() {
    FORMAT=TSV "$CH_SCRIPT" "$1"
}

save_state() {
    {
        printf 'FIRST_OP=%q\n' "$FIRST_OP"
        printf 'REPEAT_OP=%q\n' "$REPEAT_OP"
        printf 'THIRD_OP=%q\n' "$THIRD_OP"
        printf 'RECOVERY_OP=%q\n' "$RECOVERY_OP"
        printf 'IMAGES_OP=%q\n' "$IMAGES_OP"
        printf 'FAILURE_OP=%q\n' "$FAILURE_OP"
        printf 'PROBE_HASH=%q\n' "$PROBE_HASH"
    } >"$STATE_FILE"
}

load_state() {
    if [ -f "$STATE_FILE" ]; then
        # The parent process writes this file with printf %q only.
        # shellcheck disable=SC1090
        source "$STATE_FILE"
    fi
}

fail() {
    printf '%s\n' "$*" >&2
    return 1
}

expect_equal() {
    local actual="$1" expected="$2" description="$3"
    [ "$actual" = "$expected" ] || fail "$description: expected $expected, got ${actual:-empty}"
}

expect_count() {
    local query="$1" expected="$2" description="$3" actual
    actual="$(ch_collection "$query")"
    expect_equal "$actual" "$expected" "$description"
}

operation_state() {
    ch_global "SELECT state FROM Hoover4_Processing.operations FINAL WHERE op_id = '$1' LIMIT 1"
}

wait_terminal() {
    local op_id="$1" expected="$2" deadline state
    deadline=$((SECONDS + 600))
    while [ "$SECONDS" -lt "$deadline" ]; do
        if [ "$DEADLINE_EPOCH" -gt 0 ] && [ "$(date +%s)" -ge "$DEADLINE_EPOCH" ]; then
            fail 'rerun acceptance reached its 30-minute deadline'
        fi
        state="$(operation_state "$op_id")"
        case "$state" in
            finished|errored|cancelled)
                expect_equal "$state" "$expected" "operation $op_id state"
                return
                ;;
            pending|running) ;;
            *) fail "operation $op_id has no terminal row" ;;
        esac
        sleep 2
    done
    fail "operation $op_id did not finish within 10 minutes"
}

run_new_operation() {
    local output
    output="$("$@")"
    printf '%s\n' "$output" >&2
    OP_ID="$(awk '$1 == "operation" { print $2; exit }' <<<"$output")"
    [ -n "$OP_ID" ] || fail "command did not print an operation id"
    printf 'op_id %s\n' "$OP_ID"
}

run_failing_operation() {
    local output status
    set +e
    output="$("$@" 2>&1)"
    status=$?
    set -e
    printf '%s\n' "$output" >&2
    [ "$status" -ne 0 ] || fail "command succeeded when failure was required"
    OP_ID="$(awk '$1 == "operation" { print $2; exit }' <<<"$output")"
    [ -n "$OP_ID" ] || fail "failing command did not print an operation id"
    printf 'op_id %s\n' "$OP_ID"
}

detail_number() {
    local op_id="$1" key="$2"
    ch_global "SELECT JSONExtractUInt(detail, '$key') FROM Hoover4_Processing.operations FINAL WHERE op_id = '$op_id'"
}

check_detail_number() {
    local op_id="$1" key="$2" expected="$3" actual
    actual="$(detail_number "$op_id" "$key")"
    expect_equal "$actual" "$expected" "operation $op_id detail $key"
}

drop_reruns() {
    docker exec -i hoover4-worker sh -lc 'cd /app && uv run python -c "$1"' _ \
        'from database.clickhouse import drop_collection_db, get_global_client
from database.manticore import drop_collection_tables
from database.s3 import collection_bucket, get_s3_client

name = "reruns"
drop_collection_tables(name)
drop_collection_db(name)
client = get_s3_client()
bucket = collection_bucket(name)
if client.bucket_exists(bucket):
    for item in client.list_objects(bucket, recursive=True):
        client.remove_object(bucket, item.object_name)
    client.remove_bucket(bucket)
with get_global_client() as global_client:
    global_client.command("DELETE FROM operations WHERE collectionname = {name:String} SETTINGS mutations_sync = 1", parameters={"name": name})
    global_client.command("DELETE FROM dataset WHERE collectionname = {name:String}", parameters={"name": name})
    global_client.command("DELETE FROM collections WHERE collectionname = {name:String}", parameters={"name": name})'
}

case_first_run() {
    ../main_services/run.sh create-collection reruns --fullname Rerun-acceptance
    docker stop "$SCANNER"
    run_new_operation ../main_services/run.sh add-disk-dataset reruns probe \
        /testdata/hoover-testdata/qa/filenames --no-wait
    FIRST_OP="$OP_ID"
    wait_terminal "$FIRST_OP" finished
    PROBE_HASH="$(ch_collection "SELECT hash FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = '$DATASET' AND task_name = 'P4_ScanRegexEntities' AND op_id = '$FIRST_OP' LIMIT 1")"
    [ -n "$PROBE_HASH" ] || fail 'first run did not write the regex Error'
    expect_count "SELECT count() FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = '$DATASET' AND hash = '$PROBE_HASH' AND task_name = 'P4_ScanRegexEntities' AND op_id = '$FIRST_OP'" 1 'first-run Error row'
    expect_count "SELECT count() FROM $COLLECTION_DB.operation_error_events FINAL WHERE op_id = '$FIRST_OP' AND event = 'error'" 1 'first-run error event'
    expect_count "SELECT count() FROM $COLLECTION_DB.operation_plans WHERE op_id = '$FIRST_OP'" 1 'first-run operation plan'
    check_detail_number "$FIRST_OP" failed_documents 1
    check_detail_number "$FIRST_OP" failed_tasks 1
    save_state
}

case_inject_history() {
    load_state
    [ -n "$PROBE_HASH" ] || fail 'first-run state is unavailable'
    ch_collection "INSERT INTO $COLLECTION_DB.processing_errors (collection_dataset, hash, task_name, run_time_ms, error_logs, timestamp, op_id) VALUES ('$DATASET', '$PROBE_HASH', 'P4_ExtractEntities', 0, 'acceptance history', now(), 'acceptance-history'), ('$DATASET', '', 'P3_ParseSingleFile', 0, 'acceptance history', now(), 'acceptance-history'), ('$DATASET', 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', 'extract_plaintext_chunks', 0, 'acceptance history', now(), 'acceptance-history'), ('$DATASET', '$PROBE_HASH', 'acceptance_unknown_task', 0, 'acceptance history', now(), 'acceptance-history')"
    expect_count "SELECT count() FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = '$DATASET'" 5 'injected Error rows'
}

case_dispatch_is_clean() {
    load_state
    run_new_operation ../main_services/run.sh operations rerun "$FIRST_OP" --no-wait
    REPEAT_OP="$OP_ID"
    python3 - "$REPEAT_OP" <<'PY'
import json
import subprocess
import sys

op_id = sys.argv[1]
query = (
    "SELECT detail FROM Hoover4_Processing.operations FINAL "
    f"WHERE op_id = '{op_id}'"
)
detail = subprocess.check_output(
    ["../.agents/skills/querying-the-datastores/scripts/ch.sh", query],
    env={"FORMAT": "TSV"},
    text=True,
).strip()
allowed = {
    "dataset_path", "errors_before_run", "selected_errors",
    "removed_stage_off_errors", "without_plan_errors", "recovered_errors",
    "still_failing_errors", "failed_documents", "failed_tasks",
}
keys = set(json.loads(detail))
unexpected = keys - allowed
if unexpected or "dataset_name" in keys:
    raise SystemExit(f"operation detail has disallowed keys: {sorted(unexpected)}")
PY
    save_state
}

case_repeat_failure() {
    load_state
    wait_terminal "$REPEAT_OP" finished
    check_detail_number "$REPEAT_OP" errors_before_run 5
    check_detail_number "$REPEAT_OP" removed_stage_off_errors 1
    check_detail_number "$REPEAT_OP" without_plan_errors 2
    check_detail_number "$REPEAT_OP" selected_errors 2
    check_detail_number "$REPEAT_OP" still_failing_errors 1
    check_detail_number "$REPEAT_OP" recovered_errors 1
    expect_count "SELECT count() FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = '$DATASET' AND hash = '$PROBE_HASH' AND task_name = 'P4_ScanRegexEntities' AND op_id = '$REPEAT_OP'" 1 'repeat-failure current regex Error'
    expect_count "SELECT count() FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = '$DATASET' AND task_name = 'P4_ExtractEntities'" 0 'repeat-failure extracted Error removal'
    expect_count "SELECT count() FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = '$DATASET' AND task_name = 'acceptance_unknown_task'" 0 'repeat-failure unknown Error removal'
    expect_count "SELECT count() FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = '$DATASET' AND task_name = 'P3_ParseSingleFile'" 1 'repeat-failure empty-hash Error retention'
    expect_count "SELECT count() FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = '$DATASET' AND hash = 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff' AND task_name = 'extract_plaintext_chunks'" 1 'repeat-failure unmappable Error retention'
    check_detail_number "$REPEAT_OP" failed_documents 1
    save_state
}

case_lock() {
    load_state
    run_new_operation ../main_services/run.sh operations rerun "$REPEAT_OP" --no-wait
    THIRD_OP="$OP_ID"
    local deadline state output status
    deadline=$((SECONDS + 30))
    while [ "$SECONDS" -lt "$deadline" ]; do
        state="$(operation_state "$THIRD_OP")"
        case "$state" in
            pending|running) break ;;
            finished|errored|cancelled) fail "operation $THIRD_OP ended before the lock check" ;;
            *) sleep 1 ;;
        esac
    done
    case "$state" in
        pending|running) ;;
        *) fail "operation $THIRD_OP did not become live for the lock check" ;;
    esac
    set +e
    output="$(../main_services/run.sh retry-failed-files reruns --dataset "$DATASET" --task P4_ScanRegexEntities --apply 2>&1)"
    status=$?
    set -e
    printf '%s\n' "$output" >&2
    [ "$status" -ne 0 ] || fail 'lock check dispatched a concurrent operation'
    case "$output" in
        *"$THIRD_OP"*) ;;
        *) fail "lock refusal did not name $THIRD_OP" ;;
    esac
    wait_terminal "$THIRD_OP" finished
    save_state
}

case_recovery() {
    load_state
    docker start "$SCANNER"
    run_new_operation ../main_services/run.sh operations rerun "$THIRD_OP" --no-wait
    RECOVERY_OP="$OP_ID"
    wait_terminal "$RECOVERY_OP" finished
    check_detail_number "$RECOVERY_OP" errors_before_run 3
    check_detail_number "$RECOVERY_OP" selected_errors 1
    check_detail_number "$RECOVERY_OP" without_plan_errors 2
    check_detail_number "$RECOVERY_OP" recovered_errors 1
    check_detail_number "$RECOVERY_OP" still_failing_errors 0
    expect_count "SELECT count() FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = '$DATASET' AND task_name = 'P4_ScanRegexEntities'" 0 'recovery regex Error removal'
    local scans
    scans="$(ch_collection "SELECT count() FROM $COLLECTION_DB.regex_scanned WHERE collection_dataset = '$DATASET' AND file_hash = '$PROBE_HASH'")"
    [ "$scans" -ge 1 ] || fail 'recovery has no regex scan for the probe hash'
    check_detail_number "$RECOVERY_OP" failed_documents 0
    save_state
}

case_ocr_skip() {
    run_new_operation ../main_services/run.sh add-disk-dataset reruns images /testdata/hoover-testdata/data/disk-files/img --no-wait
    IMAGES_OP="$OP_ID"
    wait_terminal "$IMAGES_OP" finished
    expect_count "SELECT count() FROM $COLLECTION_DB.processing_errors WHERE collection_dataset = 'reruns_images' AND task_name LIKE 'run_ocr_and_store%easyocr%'" 0 'ocr-skip EasyOCR Error rows'
    local skipped
    skipped="$(ch_collection "SELECT count() FROM $COLLECTION_DB.processing_task_runs WHERE collection_dataset = 'reruns_images' AND task_name LIKE 'run_ocr_and_store%' AND toString(outcome) = 'skipped'")"
    [ "$skipped" -ge 1 ] || fail 'ocr-skip has no skipped OCR task run'
    save_state
}

case_projection() {
    local output status count projection_op
    projection_op="acceptance-projection-$(date +%s)"
    ch_global "INSERT INTO Hoover4_Processing.operations (op_id, kind, target_kind, collectionname, collection_dataset, state, started_at, finished_at, updated_at, progress_done, progress_total, eta_seconds, detail, error, user_id, rerun_of) VALUES ('$projection_op', 'retry_failed_files', 'dataset', 'reruns', '$DATASET', 'finished', now(), now(), now(), 0, 0, 0, '{\"failed_documents\": 3}', '', 'acceptance', '')"
    set +e
    output="$(../main_services/run.sh operations rerun "$projection_op" --no-wait 2>&1)"
    status=$?
    set -e
    printf '%s\n' "$output" >&2
    [ "$status" -ne 0 ] || fail 'projection dispatched an incomplete operation'
    case "$output" in
        *'needs task_name'*) ;;
        *) fail 'projection refusal did not name task_name' ;;
    esac
    count="$(ch_global "SELECT count() FROM Hoover4_Processing.operations FINAL WHERE collection_dataset = '$DATASET' AND rerun_of = '$projection_op'")"
    expect_equal "$count" 0 'projection child operation count'
}

case_failure_fixture() {
    local output status
    set +e
    output="$(../main_services/run.sh import-collection reruns --source acceptance-missing-backup --confirm reruns --wait 2>&1)"
    status=$?
    set -e
    printf '%s\n' "$output" >&2
    [ "$status" -ne 0 ] || fail 'failure fixture import succeeded'
    OP_ID="$(awk '$1 == "operation" { print $2; exit }' <<<"$output")"
    [ -n "$OP_ID" ] || fail 'failure fixture did not print an operation id'
    FAILURE_OP="$OP_ID"
    printf 'op_id %s\n' "$FAILURE_OP"
    wait_terminal "$FAILURE_OP" errored
    local operation_failures operation_node import_node
    operation_failures="$(ch_global "SELECT countIf(task_name = 'Operation'), countIf(task_name = 'begin_import') FROM Hoover4_Processing.operation_failures WHERE op_id = '$FAILURE_OP'")"
    read -r operation_node import_node <<<"$operation_failures"
    [ "$operation_node" -ge 1 ] && [ "$import_node" -ge 1 ] || fail 'failure-fixture failure tree is incomplete'
    expect_count "SELECT count() FROM system.databases WHERE name = '$COLLECTION_DB'" 1 'failure-fixture collection database'
    save_state
}

run_case() {
    local case_name="$1" status
    set +e
    VERIFY_RERUNS_STATE_FILE="$STATE_FILE" \
        VERIFY_RERUNS_DEADLINE_EPOCH="$DEADLINE_EPOCH" \
        "$SELF" --case "$case_name"
    status=$?
    set -e
    if [ "$status" -eq 0 ]; then
        printf 'OK %s\n' "$case_name"
    else
        printf 'FAIL %s: command exited %s\n' "$case_name" "$status"
        return 1
    fi
}

run_cases() {
    DEADLINE_EPOCH=$(( $(date +%s) + 1800 ))
    export VERIFY_RERUNS_DEADLINE_EPOCH="$DEADLINE_EPOCH"
    : >"$STATE_FILE"
    drop_reruns
    local failures=0 case_name
    for case_name in first-run inject-history dispatch-is-clean repeat-failure lock recovery ocr-skip projection failure-fixture; do
        if ! run_case "$case_name"; then
            failures=$((failures + 1))
        fi
    done
    [ "$failures" -eq 0 ]
}

case "${1:-}" in
    --case)
        load_state
        case "${2:-}" in
            first-run) case_first_run ;;
            inject-history) case_inject_history ;;
            dispatch-is-clean) case_dispatch_is_clean ;;
            repeat-failure) case_repeat_failure ;;
            lock) case_lock ;;
            recovery) case_recovery ;;
            ocr-skip) case_ocr_skip ;;
            projection) case_projection ;;
            failure-fixture) case_failure_fixture ;;
            *) fail "unknown acceptance case ${2:-empty}" ;;
        esac
        ;;
    --run-cases)
        run_cases
        ;;
    "")
        run_cases
        ;;
    *)
        fail "usage: $SELF"
        ;;
esac
