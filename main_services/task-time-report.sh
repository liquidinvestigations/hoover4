#!/bin/bash
# Where processing time went: the per-task performance report, straight out of ClickHouse.
#
# Usage: ./task-time-report.sh [collectionname] [--csv] [--since '2026-08-08 12:00:00'] [--dataset NAME]
#
#   collectionname   default testdata
#   --csv            machine-readable output (CSVWithNames) instead of tables
#   --since TS       only executions started at or after TS (UTC). Use this to scope the
#                    report to ONE ingest when the collection has been ingested more
#                    than once -- otherwise the wall clock spans both runs and the
#                    parallelism figure is meaningless.
#   --dataset NAME   restrict to one collection_dataset (the full
#                    <collectionname>_<dataset_name> id).
#
# Reads `processing_task_runs`, which the worker-side activity interceptor
# (processing/tasks/task_timing.py) fills with one row per activity execution. Failures
# are in there at their real cost, so "total" means total, not total-when-it-worked.
#
# The three numbers to read first are in the headline block:
#
#   summed_task_seconds     how much work the pipeline did, adding up every activity
#   wall_clock_seconds      how long that took on the clock, idle gaps included
#   achieved_parallelism    the ratio. Near 1 means the pipeline ran serially and the
#                           top row of the per-task table is the whole cost. Near the
#                           total worker slot count (8+8+4+2+2+1+1 across the seven
#                           queues) means the slots are saturated and the fix is more
#                           workers, not a faster task.
#
# WHAT THIS DOES NOT MEASURE: CPU. Every figure is wall duration of an activity, which
# for the subprocess-heavy tasks (7z, ffmpeg, qpdf, tesseract) is mostly time spent
# waiting for a child process that is itself using a core.
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";
cd "$SCRIPT_DIR"

COLLECTION="testdata"
FORMAT="PrettyCompact"
SINCE=""
DATASET=""

while [ $# -gt 0 ]; do
    case "$1" in
        --csv)     FORMAT="CSVWithNames"; shift ;;
        --since)   SINCE="$2"; shift 2 ;;
        --dataset) DATASET="$2"; shift 2 ;;
        -h|--help) sed -n '2,36p' "$0"; exit 0 ;;
        *)         COLLECTION="$1"; shift ;;
    esac
done

DB="Hoover4_Collection_${COLLECTION}"
# A collection name is [a-z0-9_] by construction (validate_collectionname), and a
# database name cannot be bound as a parameter, so refuse anything else rather than
# interpolating it.
if ! printf '%s' "$COLLECTION" | grep -qE '^[a-z0-9_]{1,48}$'; then
    echo "refusing collectionname: $COLLECTION" >&2; exit 2
fi

WHERE="WHERE 1"
if [ -n "$SINCE" ]; then
    if ! printf '%s' "$SINCE" | grep -qE '^[0-9 :-]{4,19}$'; then
        echo "refusing --since value: $SINCE" >&2; exit 2
    fi
    WHERE="$WHERE AND started_at >= toDateTime64('$SINCE', 3)"
fi
if [ -n "$DATASET" ]; then
    if ! printf '%s' "$DATASET" | grep -qE '^[a-z0-9_]{1,96}$'; then
        echo "refusing --dataset value: $DATASET" >&2; exit 2
    fi
    WHERE="$WHERE AND collection_dataset = '$DATASET'"
fi

CH() { docker exec clickhouse clickhouse-client -u hoover4 --password hoover4 \
        --database "$DB" --format "$FORMAT" -q "$1"; }

# Same as CH but swallows errors so extra sections can skip when a column or
# table is missing (an older collection database, an empty ingest).
CH_try() {
    docker exec clickhouse clickhouse-client -u hoover4 --password hoover4 \
        --database "$DB" --format "$FORMAT" -q "$1" 2>/dev/null || true
}

section() { [ "$FORMAT" = "CSVWithNames" ] && echo "# $1" || printf '\n== %s ==\n' "$1"; }

# `t0ms`/`t1ms` are WITH aliases over the row, so every aggregate below sees the same
# start and end instants. Wall clock is the last end minus the first start.
COMMON="WITH toUnixTimestamp64Milli(started_at) AS t0ms, t0ms + toInt64(run_time_ms) AS t1ms"

section "Headline: $DB"
CH "$COMMON
SELECT count() AS executions,
       countIf(outcome = 'error') AS failed,
       round(sum(run_time_ms) / 1000, 1) AS summed_task_seconds,
       round((max(t1ms) - min(t0ms)) / 1000, 1) AS wall_clock_seconds,
       round(sum(run_time_ms) / greatest(1, max(t1ms) - min(t0ms)), 2) AS achieved_parallelism,
       min(started_at) AS first_started,
       toDateTime64(max(t1ms) / 1000, 3) AS last_finished
FROM processing_task_runs $WHERE"

section "Per task type, slowest first"
CH "SELECT task_name,
       round(sum(run_time_ms) / 1000, 1) AS total_seconds,
       round(100 * sum(run_time_ms) / (SELECT greatest(1, sum(run_time_ms)) FROM processing_task_runs $WHERE), 2) AS share_pct,
       count() AS executions,
       countIf(outcome = 'error') AS failed,
       round(avg(run_time_ms)) AS mean_ms,
       round(quantileExact(0.50)(run_time_ms)) AS p50_ms,
       round(quantileExact(0.95)(run_time_ms)) AS p95_ms,
       round(quantileExact(0.99)(run_time_ms)) AS p99_ms,
       max(run_time_ms) AS max_ms
FROM processing_task_runs $WHERE
GROUP BY task_name
ORDER BY total_seconds DESC"

section "Per worker queue (which tier the time was spent on)"
CH "SELECT task_queue,
       round(sum(run_time_ms) / 1000, 1) AS total_seconds,
       count() AS executions,
       uniqExact(worker_id) AS worker_processes,
       uniqExact(task_name) AS task_types
FROM processing_task_runs $WHERE
GROUP BY task_queue
ORDER BY total_seconds DESC"

section "Per dataset"
CH "$COMMON
SELECT collection_dataset,
       round(sum(run_time_ms) / 1000, 1) AS total_seconds,
       round((max(t1ms) - min(t0ms)) / 1000, 1) AS wall_clock_seconds,
       round(sum(run_time_ms) / greatest(1, max(t1ms) - min(t0ms)), 2) AS achieved_parallelism,
       count() AS executions
FROM processing_task_runs $WHERE
GROUP BY collection_dataset
ORDER BY total_seconds DESC"

section "The long tail: 20 slowest single executions"
CH "SELECT task_name, collection_dataset, hash, outcome,
       round(run_time_ms / 1000, 1) AS seconds, started_at
FROM processing_task_runs $WHERE
ORDER BY run_time_ms DESC
LIMIT 20"

section "Retries: task types that spent time failing"
CH "SELECT task_name,
       countIf(outcome = 'error') AS failed_executions,
       round(sumIf(run_time_ms, outcome = 'error') / 1000, 1) AS seconds_spent_failing,
       max(attempt) AS max_attempt
FROM processing_task_runs $WHERE
GROUP BY task_name
HAVING failed_executions > 0
ORDER BY seconds_spent_failing DESC"

P3_TASKS="'detect_mime_from_name','detect_mime_with_gnu_file','detect_mime_with_magika','detect_mime_by_content','run_tika_and_store','parse_email_extract_text_headers','extract_email_attachments_to_temp','extract_plaintext_chunks','pdf_get_metadata_and_store','pdf_small_extract_text_and_images','pdf_large_split_to_chunks','parse_image_metadata_and_store','parse_audio_metadata_and_store','video_ffprobe_and_store','video_extract_frames_and_subtitles','extract_archive_to_temp','record_archive_container','parse_office_xml_and_store','parse_table_and_store','run_ocr_and_store','run_ocr_pdf_and_store','resolve_document_dates'"

overhead=$(CH_try "SELECT round(quantileExact(0.5)(run_time_ms)) AS overhead_floor_p50_ms
FROM processing_task_runs $WHERE AND task_name = 'detect_mime_from_name'")
if [ -n "$overhead" ]; then
    section "Per-activity overhead floor (detect_mime_from_name p50)"
    printf '%s\n' "$overhead"
fi

wall_busy=$(CH_try "SELECT busy_ms, wall_ms,
    round(100 * (1 - busy_ms / greatest(wall_ms, 1)), 1) AS idle_pct
FROM (
    SELECT round(avg(b)) AS busy_ms, round(avg(w)) AS wall_ms
    FROM (
        SELECT sum(run_time_ms) AS b,
               max(toUnixTimestamp64Milli(started_at) + toInt64(run_time_ms))
                 - min(toUnixTimestamp64Milli(started_at)) AS w
        FROM processing_task_runs
        $WHERE AND hash != '' AND task_name IN ($P3_TASKS)
        GROUP BY hash
    )
)")
if [ -n "$wall_busy" ]; then
    section "Wall vs busy, per file (P3 activities)"
    printf '%s\n' "$wall_busy"
fi

repeats=$(CH_try "SELECT
    countIf(task_name = 'index_vfs_structure') AS index_vfs_structure,
    countIf(task_name = 'build_vfs_nodes') AS build_vfs_nodes,
    countIf(task_name = 'resolve_canonical_file_type') AS resolve_canonical_file_type
FROM processing_task_runs $WHERE")
if [ -n "$repeats" ]; then
    section "Dataset-scoped repeats (next to the plan count)"
    printf '%s\n' "$repeats"
fi

if [ "$FORMAT" != "CSVWithNames" ]; then
    printf '\nRun with --csv to pipe these into a spreadsheet, and with\n'
    printf "  --since '<UTC timestamp>' to scope the report to a single ingest.\n"
    printf 'Activities whose parameters name no collection (ensure_temp_dir_exists,\n'
    printf 'cleanup_temp_dir, collect_eta_samples, the chat activities) are recorded\n'
    printf 'in Hoover4_Processing.processing_task_runs -- see processing/tasks/task_timing.py.\n'
fi
