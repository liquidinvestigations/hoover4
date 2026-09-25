"""Run one existing per-file step over every file of a stage activity.

A stage activity of the group workflow calls `run_batch` with its files and a step. The
step calls the existing per-file function for one file. `run_batch` returns one
`FileResult` for each file, in input order.

A try that raises puts its file on a wait list, with the backoff of the default Temporal
retry policy. The runner goes on with the next file and with each retry that is due. It
sleeps only when every file left is waiting. A try has a time limit equal to the file's
budget. After that limit, `send_heartbeat` drops every heartbeat of the attempt, and the
server ends the attempt at `HEARTBEAT_TIMEOUT`.

Every heartbeat of the attempt carries the batch detail first. The next attempt restores
the finished files, the wait list and the lost-attempt counts from it.

The group workflow imports the dataclasses and the pure functions of this module, so
module scope imports only what the workflow sandbox allows. The runner imports the rest
when it runs.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from temporalio import activity
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    CancelledError,
    TimeoutError as TemporalTimeoutError,
)

from tasks.heartbeat import (
    ACTIVITY_MAX_ATTEMPTS,
    HEARTBEAT_TIMEOUT,
    batch_progress,
    send_heartbeat,
    stop_if_worker_is_stopping,
    worker_is_stopping,
)

#: The version of the heartbeat detail. A retry ignores a detail of another version.
BATCH_DETAIL_VERSION = 2

#: The tries of one file inside one attempt, and the wait before its second try. Each
#: later wait is twice the one before, so the waits are 1, 2, 4 and 8 s, as the default
#: Temporal retry policy gave each per-file activity.
FILE_TRIES = ACTIVITY_MAX_ATTEMPTS
FILE_RETRY_FIRST_WAIT_SECONDS = 1

#: A file fails after this many attempts end while it is in progress.
LOST_ATTEMPTS_PER_FILE = 2
#: A stage activity fails after this many consecutive attempts finish no new file.
NO_PROGRESS_ATTEMPTS = 5

STAGE_ATTEMPT_LOST = "StageAttemptLost"
STAGE_NO_PROGRESS = "StageNoProgress"
FILE_TRY_TIMED_OUT = "FileTryTimedOut"

#: The largest error text of one file, in bytes as the JSON payload converter writes it.
FILE_ERROR_TYPE_BYTES = 64
FILE_ERROR_MESSAGE_BYTES = 512
FILE_ERROR_TRACE_BYTES = 1536
#: The largest encoded row of one finished file in the heartbeat detail. A larger row is
#: kept as {"i": index, "cut": true}, and a later attempt runs that file again.
DETAIL_ROW_BYTES = 2400

#: The time budget of one call for one file: a base, and the transfer time at 10 kbit/s.
FILE_BASE_SECONDS = 900
FILE_BYTES_PER_SECOND = 10_000 // 8

#: The member scan gives a folder the old limit of one scan range, 6 h, for each range of
#: RANGE_ENTRIES (500, tasks/P0_scan_disk/activities.py:24) members that HandleFolders would
#: have planned.
MEMBER_SCAN_RANGE_SECONDS = 6 * 3600
MEMBER_SCAN_RANGE_ENTRIES = 500

COMMON_QUEUE = "processing-common-queue"
TIKA_QUEUE = "processing-tika-queue"
OCR_QUEUE = "processing-ocr-queue"

#: Every stage activity, by its registered name, and the queue it runs on.
STAGE_QUEUES: Dict[str, str] = {
    "detect_mime_batch": COMMON_QUEUE,
    "run_tika_batch": TIKA_QUEUE,
    "extract_plaintext_batch": COMMON_QUEUE,
    "parse_office_xml_batch": COMMON_QUEUE,
    "parse_table_batch": COMMON_QUEUE,
    "parse_image_metadata_batch": COMMON_QUEUE,
    "run_ocr_batch": OCR_QUEUE,
    "parse_audio_metadata_batch": COMMON_QUEUE,
    "parse_email_headers_batch": COMMON_QUEUE,
    "extract_email_attachments_batch": COMMON_QUEUE,
    "extract_archive_batch": COMMON_QUEUE,
    "pdf_metadata_batch": COMMON_QUEUE,
    "run_ocr_pdf_batch": OCR_QUEUE,
    "pdf_extract_batch": COMMON_QUEUE,
    "video_batch": COMMON_QUEUE,
    "scan_container_folders": COMMON_QUEUE,
}

#: The time limit of one try of one file of each stage, as (multiplier, extra seconds,
#: floor seconds) over file_budget_seconds. It covers every call that the step of the
#: stage makes for one file.
STAGE_BUDGETS: Dict[str, Tuple[int, int, int]] = {
    "detect_mime_batch": (1, 0, 0),
    "run_tika_batch": (1, 1000, 0),
    "extract_plaintext_batch": (1, 0, 0),
    "parse_office_xml_batch": (1, 0, 0),
    "parse_table_batch": (1, 0, 0),
    "parse_image_metadata_batch": (1, 0, 0),
    "run_ocr_batch": (1, 0, 0),
    "parse_audio_metadata_batch": (1, 0, 0),
    "parse_email_headers_batch": (1, 0, 0),
    "extract_email_attachments_batch": (1, 0, 0),
    "extract_archive_batch": (2, 0, 0),
    "pdf_metadata_batch": (1, 0, 0),
    "run_ocr_pdf_batch": (1, 0, 3600),
    "pdf_extract_batch": (1, 600, 0),
    "video_batch": (2, 300, 0),
    "scan_container_folders": (1, 0, 0),   # plus member_scan_seconds, see below
}


@dataclass
class BatchFile:
    """One file of a stage activity. The last four fields feed one stage each."""

    item_hash: str
    file_path: str
    file_size_bytes: int = 0
    mime_types: List[str] = field(default_factory=list)
    mime_encodings: List[str] = field(default_factory=list)
    page_count: int = 0
    pdf_size_bytes: int = 0


@dataclass
class StageBatchParams:
    """The input of every stage activity except the member scan."""

    collectionname: str
    collection_dataset: str
    plan_hash: str
    files: List[BatchFile] = field(default_factory=list)
    op_id: str = ""
    engine: str = ""


@dataclass
class ContainerFolder:
    """One folder that a stage of the group extracted, and the file it came from."""

    container_hash: str
    out_dir: str
    error_task_name: str
    source_size_bytes: int = 0
    member_count: int = 0   # files the extraction wrote into out_dir, all levels


@dataclass
class ScanContainerFoldersParams:
    """The input of the member scan of one group."""

    collectionname: str
    collection_dataset: str
    plan_hash: str
    folders: List[ContainerFolder] = field(default_factory=list)
    op_id: str = ""


@dataclass
class FileResult:
    """What one file of a batch activity did. `status` is ok, skipped or failed."""

    item_hash: str
    task_name: str
    status: str
    value: Any = None
    error_type: str = ""
    error_message: str = ""
    error_trace: str = ""
    non_retryable: bool = False
    attempts: int = 0
    started_at_ms: int = 0
    run_time_ms: int = 0


@dataclass
class BatchResult:
    """The result of a stage activity: one `FileResult` for each input, in input order."""

    stage: str
    results: List[FileResult] = field(default_factory=list)


def file_budget_seconds(size_bytes: int, extra_seconds: int = 0) -> int:
    """The time budget of one call for one file: a base and the transfer time of its size."""
    size = max(0, int(size_bytes or 0))
    return FILE_BASE_SECONDS + extra_seconds + math.ceil(size / FILE_BYTES_PER_SECOND)


def try_budget_seconds(stage: str, size_bytes: int) -> int:
    """The time limit of one try of one file of `stage`."""
    multiplier, extra, floor = STAGE_BUDGETS[stage]
    return max(floor, multiplier * file_budget_seconds(size_bytes, extra))


def stage_timeout_seconds(stage: str, sizes: Sequence[int]) -> int:
    """The start-to-close of one attempt of a stage activity.

    Each file gets FILE_TRIES tries at its try budget and the waits between them.
    """
    waits = sum(FILE_RETRY_FIRST_WAIT_SECONDS * 2 ** n for n in range(FILE_TRIES - 1))
    return sum(FILE_TRIES * try_budget_seconds(stage, size) + waits for size in sizes)


def member_scan_seconds(folder: "ContainerFolder") -> int:
    """The time limit of one try of the member scan of one folder."""
    ranges = max(1, math.ceil(folder.member_count / MEMBER_SCAN_RANGE_ENTRIES))
    return file_budget_seconds(folder.source_size_bytes) + MEMBER_SCAN_RANGE_SECONDS * ranges


def folder_stage_timeout_seconds(folders: Sequence["ContainerFolder"]) -> int:
    """The start-to-close of one attempt of scan_container_folders."""
    waits = sum(FILE_RETRY_FIRST_WAIT_SECONDS * 2 ** n for n in range(FILE_TRIES - 1))
    return sum(FILE_TRIES * member_scan_seconds(folder) + waits for folder in folders)


def file_error(result: FileResult) -> ApplicationError:
    """The failure of one file as an exception, for the error recorder and its helpers."""
    return ApplicationError(
        result.error_message,
        result.error_trace,
        type=result.error_type or None,
        non_retryable=result.non_retryable,
    )


def stage_keys_digest(keys: Sequence[str]) -> str:
    """A short digest of the input keys, so that a retry can tell its own detail."""
    import hashlib

    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:16]


def results_from_detail(detail: Any, stage: str, keys: Sequence[str]) -> Dict[int, FileResult]:
    """The finished results that one batch detail records, by input index.

    It returns nothing when the detail has another version, stage or input list. A row
    that the runner cut for its size is not a result, so that file runs again.
    """
    if not _is_detail_of(detail, stage, stage_keys_digest(keys)):
        return {}
    names = {item.name for item in dataclasses.fields(FileResult)} - {"item_hash"}
    found: Dict[int, FileResult] = {}
    for row in detail.get("done") or []:
        index = row.get("i") if isinstance(row, dict) else None
        if not isinstance(index, int) or not 0 <= index < len(keys):
            return {}
        if row.get("cut"):
            continue
        try:
            found[index] = FileResult(item_hash=keys[index],
                                      **{k: v for k, v in row.items() if k in names})
        except TypeError:
            return {}
    return found


def detail_of_failure(exc: BaseException) -> Any:
    """The batch detail that a failed stage activity carries, or None."""
    cause = exc.cause if isinstance(exc, ActivityError) else exc
    if isinstance(cause, ApplicationError) and cause.type == STAGE_NO_PROGRESS and cause.details:
        return cause.details[0]
    if isinstance(cause, TemporalTimeoutError) and cause.last_heartbeat_details:
        return cause.last_heartbeat_details[0]
    return None


def stage_failure_results(stage: str, keys: Sequence[str],
                          exc: BaseException) -> List[FileResult]:
    """One result for each file of a stage activity that failed.

    A file that the last detail lists as finished keeps its result. Every other file gets
    a failed result that names the stage and the cause. It carries no detail, so that its
    error row stays small.
    """
    finished = results_from_detail(detail_of_failure(exc), stage, keys)
    cause = exc.cause if isinstance(exc, ActivityError) and exc.cause else exc
    error_type = _clip(str(getattr(cause, "type", "") or type(cause).__name__),
                       FILE_ERROR_TYPE_BYTES, keep_tail=False)
    message = _clip(f"{stage} failed: {getattr(cause, 'message', '') or cause}",
                    FILE_ERROR_MESSAGE_BYTES, keep_tail=False)
    return [
        finished.get(index) or FileResult(item_hash=key, task_name=stage, status="failed",
                                          error_type=error_type, error_message=message)
        for index, key in enumerate(keys)
    ]


def run_batch(
    stage: str,
    items: Sequence[Any],
    *,
    key: Callable[[Any], str],
    size: Callable[[Any], int],
    step: Callable[[Any], Any],
    task_name: Union[str, Callable[[Any], str]],
    budget: Optional[Callable[[Any], int]] = None,
) -> BatchResult:
    """Run `step` for each item and return one result for each item, in input order.

    `key` gives the hash of an item, and `size` its size in bytes, which sets the time
    limit of one try. `budget`, when given, returns that time limit in seconds in place
    of `try_budget_seconds(stage, size(item))`. The member scan passes
    `member_scan_seconds`. `task_name` is the name of the per-file function, or a function of
    the item that returns it. The timing interceptor writes it as the task of the item's
    rows.
    """
    keys = [key(item) for item in items]
    names = [task_name(item) if callable(task_name) else task_name for item in items]
    state = _State.start(stage, keys, names)
    with batch_progress(state):
        while True:
            stop_if_worker_is_stopping()
            index = state.next_index()
            if index is None:
                if not state.due_ms:
                    return BatchResult(stage=stage, results=state.results())
                state.sleep_until_due()
                continue
            limit = (budget(items[index]) if budget is not None
                     else try_budget_seconds(stage, size(items[index])))
            state.start_try(index, limit)
            state.end_try(index, _try_once(state, index, items[index], step))


class _State:
    """The progress of one attempt, and the detail that each of its heartbeats carries.

    `send_heartbeat` calls `heartbeat_detail` from the pump threads. Each change builds a
    new detail and assigns it in one step, so a reader always gets a whole detail. The
    lock orders the end of a try against a heartbeat that finds the try past its limit.
    """

    def __init__(self, stage: str, keys: List[str], names: List[str], attempt: int) -> None:
        import threading

        self.stage, self.keys, self.names, self.attempt = stage, keys, names, attempt
        self.digest = stage_keys_digest(keys)
        self.done: Dict[int, FileResult] = {}
        self.rows: Dict[int, Dict[str, Any]] = {}
        self.due_ms: Dict[int, int] = {}       # the wait list: file index to due time
        self.tries: Dict[int, int] = {}        # tries started, for each unfinished file
        self.started_ms: Dict[int, int] = {}   # the start of the first try of each file
        self.lost: Dict[int, int] = {}         # attempts that ended while the file ran
        self.progress_attempt = 0              # the last attempt that finished a file
        self.running: Optional[int] = None
        self.suspect: Optional[int] = None
        self.deadline: Optional[float] = None
        self.expired = False
        self.lock = threading.Lock()
        self.detail: Dict[str, Any] = {}
        self._publish()

    @classmethod
    def start(cls, stage: str, keys: List[str], names: List[str]) -> "_State":
        """Restore the state of the last detail, then apply the lost-attempt and no-progress limits."""
        info = activity.info() if activity.in_activity() else None
        state = cls(stage, keys, names, info.attempt if info else 1)
        detail = info.heartbeat_details[0] if info and info.heartbeat_details else None
        if _is_detail_of(detail, stage, state.digest):
            state._restore(detail)
        idle = state.attempt - 1 - state.progress_attempt
        if idle >= NO_PROGRESS_ATTEMPTS:
            raise ApplicationError(
                f"{stage}: {idle} consecutive attempts finished no new file",
                state.detail, type=STAGE_NO_PROGRESS, non_retryable=True)
        if activity.in_activity():
            activity.logger.info(
                "[P3] %s attempt %d: %d of %d files restored, %d waiting, lost %s",
                stage, state.attempt, len(state.done), len(keys), len(state.due_ms),
                state.lost)
        return state

    def _restore(self, detail: Dict[str, Any]) -> None:
        for index, result in results_from_detail(detail, self.stage, self.keys).items():
            self.done[index] = result
            self.rows[index] = _detail_row(index, result)
        for index, tries, due_ms, started_ms in detail.get("wait") or []:
            if index not in self.done:
                self.due_ms[index], self.tries[index] = due_ms, tries
                self.started_ms[index] = started_ms
        self.lost = {int(k): int(v) for k, v in (detail.get("lost") or {}).items()}
        self.progress_attempt = int(detail.get("prog") or 0)
        running = detail.get("run")
        if running and running[0] not in self.done:
            index, tries, started_ms = running
            # The attempt that wrote the detail ended while this file ran. An attempt
            # after it that sent no heartbeat restored the same detail and ran the same
            # file, so it counts too.
            ended = max(1, self.attempt - int(detail.get("att") or 0))
            self.lost[index] = self.lost.get(index, 0) + ended
            self.tries[index], self.started_ms[index] = tries - 1, started_ms
            self.due_ms.pop(index, None)
            if self.lost[index] >= LOST_ATTEMPTS_PER_FILE:
                self._finish(index, _lost(self.keys[index], self.names[index],
                                          self.lost[index], tries, started_ms))
            else:
                self.suspect = index
        self._publish()

    def next_index(self) -> Optional[int]:
        """The suspect file first, then the earliest due retry, then the next new file."""
        import time

        if self.suspect is not None:
            index, self.suspect = self.suspect, None
            return index
        now_ms = int(time.time() * 1000)
        due = [index for index, due_ms in self.due_ms.items() if due_ms <= now_ms]
        if due:
            return min(due, key=lambda index: (self.due_ms[index], index))
        for index in range(len(self.keys)):
            if index not in self.done and index not in self.due_ms:
                return index
        return None

    def start_try(self, index: int, budget_seconds: int) -> None:
        import time

        self.due_ms.pop(index, None)
        self.tries[index] = self.tries.get(index, 0) + 1
        self.started_ms.setdefault(index, int(time.time() * 1000))
        self.running = index
        with self.lock:
            self.deadline = time.monotonic() + budget_seconds
        self._publish()
        send_heartbeat()

    def close_try(self) -> None:
        """End the time limit of the try in progress. Raise when a heartbeat was dropped."""
        with self.lock:
            self.deadline, expired = None, self.expired
        if expired:
            raise ApplicationError(
                f"{self.stage}: file {self.running} passed its try time limit",
                type=FILE_TRY_TIMED_OUT)

    def end_try(self, index: int, result: Optional[FileResult]) -> None:
        import time

        self.running = None
        if result is None:
            wait = FILE_RETRY_FIRST_WAIT_SECONDS * 2 ** (self.tries[index] - 1)
            self.due_ms[index] = int(time.time() * 1000) + wait * 1000
        else:
            self._finish(index, result)
        self._publish()
        send_heartbeat()

    def heartbeat_detail(self) -> Optional[Dict[str, Any]]:
        """The first detail of a heartbeat, or None after the try passed its limit."""
        import time

        with self.lock:
            deadline = self.deadline
            if self.expired or (deadline is not None and time.monotonic() > deadline):
                self.expired = True
                return None
            return self.detail

    def sleep_until_due(self) -> None:
        import time

        send_heartbeat()
        _wait((min(self.due_ms.values()) - int(time.time() * 1000)) / 1000)

    def results(self) -> List[FileResult]:
        return [self.done[index] for index in range(len(self.keys))]

    def _finish(self, index: int, result: FileResult) -> None:
        self.done[index] = result
        self.rows[index] = _detail_row(index, result)
        self.lost.pop(index, None)
        self.progress_attempt = self.attempt

    def _publish(self) -> None:
        running = self.running
        self.detail = {
            "v": BATCH_DETAIL_VERSION, "stage": self.stage, "keys": self.digest,
            "att": self.attempt, "prog": self.progress_attempt,
            "done": [self.rows[index] for index in sorted(self.rows)],
            "wait": [[index, self.tries[index], due, self.started_ms[index]]
                     for index, due in sorted(self.due_ms.items())],
            "run": None if running is None
            else [running, self.tries[running], self.started_ms[running]],
            "lost": {str(index): count for index, count in self.lost.items()},
        }


def _is_detail_of(detail: Any, stage: str, digest: str) -> bool:
    return (isinstance(detail, dict) and detail.get("v") == BATCH_DETAIL_VERSION
            and detail.get("stage") == stage and detail.get("keys") == digest)


def _try_once(state: _State, index: int, item: Any,
              step: Callable[[Any], Any]) -> Optional[FileResult]:
    """One try of one file. Return its result, or None when the file waits for a retry."""
    import time

    from tasks.task_timing import SkippedOutcome

    clock = time.monotonic()
    try:
        value = step(item)
    except Exception as exc:  # noqa: BLE001 - the failure of one file is a result
        state.close_try()
        if isinstance(exc, CancelledError) or worker_is_stopping():
            raise
        if _is_non_retryable(exc) or state.tries[index] >= FILE_TRIES:
            return _failed(state, index, exc, clock)
        return None
    state.close_try()
    status = "ok"
    if isinstance(value, SkippedOutcome):
        status, value = "skipped", value.value
    return FileResult(item_hash=state.keys[index], task_name=state.names[index],
                      status=status, value=value, attempts=state.tries[index],
                      started_at_ms=state.started_ms[index], run_time_ms=_elapsed_ms(clock))


def _is_non_retryable(exc: BaseException) -> bool:
    return isinstance(exc, ApplicationError) and bool(exc.non_retryable)


def _failed(state: _State, index: int, exc: Exception, clock: float) -> FileResult:
    import traceback

    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    error_type = exc.type if isinstance(exc, ApplicationError) and exc.type else type(exc).__name__
    return FileResult(
        item_hash=state.keys[index], task_name=state.names[index], status="failed",
        error_type=_clip(error_type, FILE_ERROR_TYPE_BYTES, keep_tail=False),
        error_message=_clip(str(exc), FILE_ERROR_MESSAGE_BYTES, keep_tail=False),
        error_trace=_clip(trace, FILE_ERROR_TRACE_BYTES, keep_tail=True),
        non_retryable=_is_non_retryable(exc), attempts=state.tries[index],
        started_at_ms=state.started_ms[index], run_time_ms=_elapsed_ms(clock),
    )


def _lost(key: str, task_name: str, lost: int, tries: int, started_ms: int) -> FileResult:
    return FileResult(
        item_hash=key, task_name=task_name, status="failed", error_type=STAGE_ATTEMPT_LOST,
        error_message=f"{lost} attempts of the stage activity ended while this file ran",
        non_retryable=True, attempts=tries, started_at_ms=started_ms,
    )


def _wait(seconds: float) -> None:
    """Sleep, and stop at once when the worker drains or the activity is cancelled."""
    import time

    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        stop_if_worker_is_stopping()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.5, remaining))


def _detail_row(index: int, result: FileResult) -> Dict[str, Any]:
    """The row of one finished file in the detail, at most DETAIL_ROW_BYTES encoded."""
    row = {"i": index}
    row.update((k, v) for k, v in dataclasses.asdict(result).items() if k != "item_hash")
    if _encoded_size(row) > DETAIL_ROW_BYTES:
        return {"i": index, "cut": True}
    return row


def _encoded_size(value: Any) -> int:
    """The encoded size of one value, measured as the payload guard measures a payload."""
    from temporalio.converter import PayloadConverter

    from tasks.payload_guard import payload_size

    converter = activity.payload_converter() if activity.in_activity() else PayloadConverter.default
    return payload_size(converter.to_payloads([value])[0])


def _clip(text: str, limit: int, *, keep_tail: bool) -> str:
    """At most `limit` bytes as the JSON converter writes the text. The head always stays."""
    if _json_size(text) <= limit:
        return text
    if not keep_tail:
        return _head(text, limit)
    marker = "\n[...]\n"
    head = _head(text, limit // 4)
    return head + marker + _tail(text, limit - _json_size(head) - _json_size(marker))


def _json_size(text: str) -> int:
    import json

    return len(json.dumps(text)) - 2


def _head(text: str, limit: int) -> str:
    import json

    used = 0
    for count, char in enumerate(text):
        used += len(json.dumps(char)) - 2
        if used > limit:
            return text[:count]
    return text


def _tail(text: str, limit: int) -> str:
    import json

    used = 0
    for count, char in enumerate(reversed(text)):
        used += len(json.dumps(char)) - 2
        if used > limit:
            return text[len(text) - count:]
    return text


def _elapsed_ms(clock: float) -> int:
    import time

    return max(0, int((time.monotonic() - clock) * 1000))
