"""The antivirus stage: each file of a group goes to the ClamAV service before parsing.

The stage runs first in the group and never stops parsing. Every file gets one attempt
row in `virus_scan_results`:

| `attempt_status` | Meaning |
|---|---|
| `completed` | The scanner gave a verdict: `clean` or `infected`. |
| `incomplete` | The scanner stopped at a recursive limit (`Heuristics.Limits.Exceeded...`). No verdict. |
| `skipped_size` | The file is larger than `CLAMAV_MAX_FILE_BYTES`. A file of exactly that size is scanned. |
| `skipped_disabled` | `clamav_enabled` is off. No request was sent. |
| `failed` | The service was unreachable or answered an error. |

The **effective verdict** of a hash is its latest `completed` attempt by `result_seq`.
A later failed, incomplete, skipped or disabled attempt never replaces a known verdict,
so a positive verdict stays until a later completed scan says otherwise. `result_seq` is
a monotonic number of the attempt, separate from `scan_version`, the logical version of
the stage. A scan failure is not a processing error: the "Virus scan" update step selects
the hashes without an effective verdict again.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Sequence

from temporalio import activity

from tasks.heartbeat import with_heartbeat
from tasks.P3_parse_files.batch_runner import BatchFile, BatchResult, StageBatchParams, run_batch, try_budget_seconds
from tasks.task_timing import SkippedOutcome

log = logging.getLogger(__name__)

#: The largest file that the stage sends. A file of exactly this size is scanned.
CLAMAV_MAX_FILE_BYTES = 500 * 1024 * 1024
#: The logical version of the stage output. `STAGE_VERSIONS["virus_scan"]` reads it.
SCAN_VERSION = 1
#: The waits in seconds before the second and third try of a request that the service
#: refused with 502 or 503, or that did not reach it.
RETRY_DELAYS = (2, 10)
#: The workflow patch that runs the stage first in the group.
CLAMAV_SCAN_PATCH = "clamav-scan"


def clamav_enabled() -> bool:
    return os.environ.get("CLAMAV_ENABLED", "false").strip().lower() == "true"


def clamav_url() -> str:
    return os.environ.get("CLAMAV_URL", "").strip().rstrip("/")


def _result_seq() -> int:
    return time.time_ns()


def attempt_row(collection_dataset: str, file_hash: str, attempt_status: str, verdict: str = "",
                signature: str = "", engine: str = "", database: str = "", fingerprint: str = "",
                error: str = "") -> Dict[str, Any]:
    return {"collection_dataset": collection_dataset, "hash": file_hash, "attempt_status": attempt_status,
            "verdict": verdict, "signature": signature[:500], "engine_version": engine,
            "database_version": database, "config_fingerprint": fingerprint,
            "scan_version": SCAN_VERSION, "result_seq": _result_seq(), "error": error[:2000]}


def scan_file(collection_dataset: str, file_hash: str, path: str, size: int,
              session=None) -> Dict[str, Any]:
    """One attempt row for one file. The request streams the file from disk."""
    import requests

    if not clamav_enabled():
        return attempt_row(collection_dataset, file_hash, "skipped_disabled")
    if size > CLAMAV_MAX_FILE_BYTES:
        return attempt_row(collection_dataset, file_hash, "skipped_size")
    url = clamav_url()
    if not url:
        return attempt_row(collection_dataset, file_hash, "failed", error="CLAMAV_URL is empty")
    read_seconds = max(60, try_budget_seconds("clamav_scan_batch", size) - 30)
    for delay in (*RETRY_DELAYS, None):
        try:
            with open(path, "rb") as handle:
                response = (session or requests).post(
                    f"{url}/scan", data=handle, headers={"Content-Length": str(size)},
                    timeout=(30, read_seconds))
            payload = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
        except FileNotFoundError as exc:
            return attempt_row(collection_dataset, file_hash, "failed", error=f"{type(exc).__name__}: {exc}")
        except (OSError, requests.RequestException, ValueError) as exc:
            if delay is None:
                return attempt_row(collection_dataset, file_hash, "failed", error=f"{type(exc).__name__}: {exc}")
            time.sleep(delay)
            continue
        if response.status_code in (502, 503) and delay is not None:
            # A full queue or a clamd that did not answer. The next try waits.
            time.sleep(delay)
            continue
        break
    status = payload.get("status", "")
    common = dict(signature=payload.get("signature") or "", engine=payload.get("engine_version") or "",
                  database=payload.get("database_version") or "",
                  fingerprint=payload.get("config_fingerprint") or "")
    if response.status_code == 200 and status in ("clean", "infected"):
        return attempt_row(collection_dataset, file_hash, "completed", verdict=status, **common)
    if response.status_code == 200 and status == "incomplete":
        return attempt_row(collection_dataset, file_hash, "incomplete", **common)
    return attempt_row(collection_dataset, file_hash, "failed", **common,
                       error=f"HTTP {response.status_code}: {payload.get('error') or payload.get('signature') or ''}")


def store_attempts(collectionname: str, rows: Sequence[Dict[str, Any]]) -> None:
    import pyarrow as pa

    from database.clickhouse import get_collection_client, insert_arrow_durable

    if not rows:
        return
    table = pa.table({
        "collection_dataset": pa.array([r["collection_dataset"] for r in rows], type=pa.string()),
        "hash": pa.array([r["hash"] for r in rows], type=pa.string()),
        "attempt_status": pa.array([r["attempt_status"] for r in rows], type=pa.string()),
        "verdict": pa.array([r["verdict"] for r in rows], type=pa.string()),
        "signature": pa.array([r["signature"] for r in rows], type=pa.string()),
        "engine_version": pa.array([r["engine_version"] for r in rows], type=pa.string()),
        "database_version": pa.array([r["database_version"] for r in rows], type=pa.string()),
        "config_fingerprint": pa.array([r["config_fingerprint"] for r in rows], type=pa.string()),
        "scan_version": pa.array([r["scan_version"] for r in rows], type=pa.uint16()),
        "result_seq": pa.array([r["result_seq"] for r in rows], type=pa.uint64()),
        "error": pa.array([r["error"] for r in rows], type=pa.string()),
    })
    with get_collection_client(collectionname) as client:
        insert_arrow_durable(client, "virus_scan_results", table)


def effective_verdicts(client, hashes: Sequence[str]) -> Dict[str, Dict[str, str]]:
    """The effective verdict of each hash that has one: its latest completed attempt."""
    if not hashes:
        return {}
    rows = client.query(
        "SELECT hash, argMax(verdict, result_seq), argMax(signature, result_seq), "
        "argMax(database_version, result_seq) FROM virus_scan_results "
        "WHERE hash IN {h:Array(String)} AND attempt_status = 'completed' GROUP BY hash",
        parameters={"h": list(hashes)}).result_rows
    return {r[0]: {"verdict": r[1], "signature": r[2], "database_version": r[3]} for r in rows}


@activity.defn
@with_heartbeat
def clamav_scan_batch(params: StageBatchParams) -> BatchResult:
    """Scan each file of a group and store one attempt row for each.

    The value of a file is its attempt status and verdict. The stage never fails a file,
    so the parse stages run for every file whatever the verdict.
    """
    import requests

    session = requests.Session()
    rows: List[Dict[str, Any]] = []

    def step(file: BatchFile) -> Dict[str, Any] | SkippedOutcome:
        row = scan_file(params.collection_dataset, file.item_hash, file.file_path, file.file_size_bytes, session)
        rows.append(row)
        value = {"attempt_status": row["attempt_status"], "verdict": row["verdict"],
                 "signature": row["signature"]}
        if row["attempt_status"] != "completed":
            return SkippedOutcome({**value, "error": row["error"][:300]})
        return value

    try:
        return run_batch("clamav_scan_batch", params.files, key=lambda f: f.item_hash,
                         size=lambda f: f.file_size_bytes, step=step, task_name="clamav_scan")
    finally:
        store_attempts(params.collectionname, rows)


def health() -> Optional[dict]:
    """The `/health` answer of the service, or None when it does not answer."""
    import requests

    url = clamav_url()
    if not url:
        return None
    try:
        response = requests.get(f"{url}/health", timeout=(5, 10))
        return response.json()
    except (requests.RequestException, ValueError):
        return None
