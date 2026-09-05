"""Tika/Extractous parsing activity for text and metadata extraction."""

from temporalio import activity
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass
import json
import logging
import os
import queue
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

from tasks.heartbeat import heartbeat_pump, with_heartbeat

log = logging.getLogger(__name__)

@dataclass
class RunTikaParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int


def _coarse_from_mime(mime: str) -> str:
    try:
        from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type
        return coarse_file_type(mime)
    except Exception:
        return ""


# Hard cap for a single Extractous call, regardless of the activity timeout.
_EXTRACTOUS_SUBPROCESS_TIMEOUT_S = 600

# Matches the tika worker's activity-slot count. One helper per in-flight
# extract; extras wait on the idle queue rather than spawning unbounded.
_EXTRACTOUS_POOL_SIZE = 8

# How long a checkout parks on the idle queue before re-checking whether it may
# spawn instead. Only reached when every helper is busy.
_CHECKOUT_WAIT_SECONDS = 1.0

# Long-lived helper: one JSON request per line on stdin, one JSON object per
# line on stdout. Native Extractous stays isolated in the child so a wedge can
# be killed; the parent does not pay interpreter startup per file.
_EXTRACTOUS_HELPER = r"""
import json, sys
from extractous import Extractor, TesseractOcrConfig
ex = Extractor().set_ocr_config(TesseractOcrConfig().set_language('eng'))
for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
        path = req['path'] if isinstance(req, dict) else req
        text, meta = ex.extract_file_to_string(path)
        sys.stdout.write(json.dumps(
            {'ok': True, 'text': text or '', 'metadata': meta or {}},
            default=str,
        ))
        sys.stdout.write('\n')
        sys.stdout.flush()
    except Exception as exc:
        sys.stdout.write(json.dumps({'ok': False, 'error': str(exc)}))
        sys.stdout.write('\n')
        sys.stdout.flush()
"""


def _drain_stderr(proc: subprocess.Popen) -> None:
    """Read stderr to EOF so a noisy child cannot fill a PIPE and block."""
    stderr = proc.stderr
    if stderr is None:
        return
    try:
        for _ in stderr:
            pass
    except Exception:
        pass


class ExtractousHelperPool:
    """Bounded pool of long-lived extractous helper processes.

    A wedged native call cannot be interrupted in-process. Helpers are killed
    on timeout, the error is non-retryable, and the next checkout respawns.
    """

    def __init__(
        self,
        size: int = _EXTRACTOUS_POOL_SIZE,
        helper_cmd: list[str] | None = None,
        timeout_s: float = _EXTRACTOUS_SUBPROCESS_TIMEOUT_S,
    ):
        self._size = size
        self._helper_cmd = helper_cmd
        self._timeout_s = timeout_s
        self._idle: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._live = 0
        self.last_killed_pid: int | None = None

    def _command(self) -> list[str]:
        if self._helper_cmd is not None:
            return list(self._helper_cmd)
        return [sys.executable, "-u", "-c", _EXTRACTOUS_HELPER]

    def _spawn(self) -> subprocess.Popen:
        proc = subprocess.Popen(
            self._command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        threading.Thread(target=_drain_stderr, args=(proc,), daemon=True).start()
        return proc

    def _checkout(self) -> subprocess.Popen:
        while True:
            try:
                proc = self._idle.get_nowait()
            except queue.Empty:
                proc = None
            if proc is not None:
                if proc.poll() is None:
                    return proc
                with self._lock:
                    self._live = max(0, self._live - 1)
                continue
            with self._lock:
                if self._live < self._size:
                    spawned = self._spawn()
                    self._live += 1
                    return spawned
            # Wait for a check-in, but never indefinitely: a helper killed on
            # timeout decrements `_live` without putting anything back, so a
            # thread parked on an unbounded get() would wait for a check-in that
            # is not coming. The timeout returns to the top, where the spawn
            # branch is now open again.
            try:
                proc = self._idle.get(timeout=_CHECKOUT_WAIT_SECONDS)
            except queue.Empty:
                continue
            if proc.poll() is None:
                return proc
            with self._lock:
                self._live = max(0, self._live - 1)

    def _checkin(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            with self._lock:
                self._live = max(0, self._live - 1)
            return
        self._idle.put(proc)

    def _kill(self, proc: subprocess.Popen) -> None:
        self.last_killed_pid = proc.pid
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        with self._lock:
            self._live = max(0, self._live - 1)

    def _read_line(self, proc: subprocess.Popen, timeout_s: float) -> str:
        stdout = proc.stdout
        if stdout is None:
            raise RuntimeError("extractous helper has no stdout")
        ready, _, _ = select.select([stdout], [], [], timeout_s)
        if not ready:
            raise TimeoutError
        line = stdout.readline()
        if line == "":
            raise EOFError("extractous helper closed stdout")
        return line

    def extract(self, file_path: str) -> tuple[str, dict]:
        from temporalio.exceptions import ApplicationError

        proc = self._checkout()
        try:
            if proc.stdin is None:
                raise RuntimeError("extractous helper has no stdin")
            proc.stdin.write(json.dumps({"path": file_path}) + "\n")
            proc.stdin.flush()
            try:
                line = self._read_line(proc, self._timeout_s)
            except TimeoutError:
                self._kill(proc)
                raise ApplicationError(
                    f"extractous timed out after {self._timeout_s}s for {file_path}",
                    non_retryable=True,
                )
            out = json.loads(line)
        except ApplicationError:
            raise
        except Exception:
            self._kill(proc)
            raise
        if not out.get("ok", True):
            self._checkin(proc)
            raise RuntimeError(
                f"extractous failed for {file_path}: {out.get('error')!r}"
            )
        self._checkin(proc)
        return out.get("text") or "", out.get("metadata") or {}

    def close(self) -> None:
        while True:
            try:
                proc = self._idle.get_nowait()
            except queue.Empty:
                break
            self._kill(proc)


_pool: ExtractousHelperPool | None = None
_pool_lock = threading.Lock()


def reset_extractous_pool_for_tests() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool = None


def _get_pool() -> ExtractousHelperPool:
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            _pool = ExtractousHelperPool()
        return _pool


def _detector_candidate_types(file_path: str) -> List[Tuple[str, str]]:
    """Up to three `(source, mime_type)` candidates, ahead of extractous's own guess.

    Order: the `file` detector's first match. Then a second match, when `file -k`
    reports one that differs from the first. Then the type the filename's extension
    implies, kept only when it differs from both. A file with one confident type
    across all three sources returns one candidate.
    """
    from tasks.P3_parse_files.parse_mime import detect_file_and_extension_types

    file_types, extension_types = detect_file_and_extension_types(file_path)
    candidates: List[Tuple[str, str]] = []
    seen: set = set()

    if file_types:
        candidates.append(("the file detector's first match", file_types[0]))
        seen.add(file_types[0])
    if len(file_types) > 1 and file_types[1] not in seen:
        candidates.append(("the file detector's second match", file_types[1]))
        seen.add(file_types[1])
    if extension_types and extension_types[0] not in seen:
        candidates.append(("the file extension", extension_types[0]))
        seen.add(extension_types[0])

    return candidates


def _extract_with_hinted_type(file_path: str, mime_type: str) -> tuple[str, dict]:
    """Extractous, given a same-bytes copy whose name declares `mime_type`.

    Extractous takes no type argument. `extract_file`, `extract_bytes` and
    `extract_file_to_string` all read only a path, a buffer, or a string. Checked
    against this pinned version and against the latest upstream Rust API. The
    filename's extension is the only lever that reaches its detector. It is a hint
    the detector weighs against the bytes. Content that already names its own type
    in a header wins over the copy's extension. Raises `ValueError` when `mime_type`
    maps to no known extension, so the caller can skip the step.
    """
    from tasks.P3_parse_files.parse_mime import extension_for_mime_type

    extension = extension_for_mime_type(mime_type)
    if extension is None:
        raise ValueError(f"no extension known for {mime_type!r}")
    tmp_dir = tempfile.mkdtemp(prefix="hoover4-tika-hint-")
    hinted_path = os.path.join(tmp_dir, "attempt" + extension)
    try:
        try:
            os.link(file_path, hinted_path)
        except OSError:
            shutil.copyfile(file_path, hinted_path)
        with heartbeat_pump("extractous"):
            return _get_pool().extract(hinted_path)
    finally:
        try:
            os.remove(hinted_path)
        except OSError:
            pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def _extract_with_extractous(file_path: str) -> tuple[str, dict]:
    """Run the four-step fallback chain, stopping at the first success.

    1. the type the `file` detector names first,
    2. a second type from `file`, when `-k` offers one and it differs from the first,
    3. the type the file's extension implies, when it differs from both,
    4. extractous's own detection, with no type given at all.

    A step whose type repeats an earlier one is skipped: it is not attempted and
    does not appear in the error this function raises when every step fails. Giving
    up raises one `RuntimeError` naming every attempt that ran and what each said, so
    a person reading the row sees which types were tried.

    Extractous (native Tika + Tesseract) wedges forever on some formats (camera RAW,
    PSD, TGA, ...). A stuck native call cannot be interrupted from Python and blocks
    the worker's activity threads, and every later call through the same helper. A
    subprocess can always be killed, which is why every attempt below goes through
    the same pooled helper: `ExtractousHelperPool.extract` kills and respawns on a
    timeout, and does so as a non-retryable `ApplicationError` immediately, without
    trying the next candidate type. A wedge is a property of the bytes reaching a
    native call, not of the name attached to them, so a second attempt under a
    different extension pays the same worst case for a result already certain. Only
    a parse failure -- extractous returning `ok: false` -- lets the chain move on.
    """
    from temporalio.exceptions import ApplicationError

    attempts: List[str] = []
    errors: List[str] = []

    for source, mime_type in _detector_candidate_types(file_path):
        attempts.append(f"{source} ({mime_type})")
        try:
            text, meta = _extract_with_hinted_type(file_path, mime_type)
        except ApplicationError:
            raise
        except Exception as exc:
            errors.append(f"{attempts[-1]}: {exc}")
            continue
        log.info("[P3] extractous succeeded at %s for %s", source, file_path)
        return text, meta

    attempts.append("extractous's own detection, no type given")
    with heartbeat_pump("extractous"):
        try:
            text, meta = _get_pool().extract(file_path)
        except ApplicationError:
            raise
        except Exception as exc:
            errors.append(f"{attempts[-1]}: {exc}")
        else:
            log.info("[P3] extractous succeeded via its own detection for %s", file_path)
            return text, meta

    raise RuntimeError(
        f"extractous failed for {file_path} after {len(attempts)} attempt(s): "
        + "; ".join(errors)
    )


@activity.defn
@with_heartbeat
def run_tika_and_store(params: RunTikaParams) -> Dict[str, Any]:
    """Activity that uses Extractous to extract text and metadata and stores results.

    Also writes detected file types to file_types with extracted_by='tika' and returns lists.
    """
    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    import pyarrow as pa

    log.info("[P3] Running Extractous for %s", params.file_path)

    # Extract text and metadata using Extractous (subprocess: interruptible)
    result_text, meta_parsed = _extract_with_extractous(params.file_path)
    content_text = result_text or ""

    # Single ClickHouse session for both inserts
    from datetime import datetime, timezone
    processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_collection_client(params.collectionname) as client:
        if content_text.strip():
            from tasks.P3_parse_files.parse_common import insert_text_chunks
            insert_text_chunks(params.collectionname, params.collection_dataset, params.file_hash, "extractous", content_text)

        tbl_m = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "hash": pa.array([params.file_hash], type=pa.string()),
            "tika_metadata_json": pa.array([json.dumps(meta_parsed)], type=pa.string()),
            "processed_at": pa.array([processed_at], type=pa.timestamp("s")),
        })
        insert_arrow_idempotent(client, "tika_metadata", tbl_m)

        # Extract MIME/type from metadata if present and write to file_types
        mime_candidates: List[str] = []
        enc_candidates: List[str] = []
        extensions: List[str] = []
        try:
            # Common keys from Tika-like outputs
            for key in ["Content-Type", "content-type", "ContentType", "mime" ]:
                val = meta_parsed.get(key)
                if isinstance(val, str) and val:
                    mime_candidates.append(val.strip())
            for key in ["Content-Encoding", "content-encoding", "encoding"]:
                val = meta_parsed.get(key)
                if isinstance(val, str) and val:
                    enc_candidates.append(val.strip())
            for key in ["resourceName", "X-Parsed-By-Filename", "filename"]:
                val = meta_parsed.get(key)
                if isinstance(val, str) and "." in val:
                    name = val.strip()
                    base = name.lower()
                    parts = base.split('.')
                    if len(parts) > 1:
                        last_ext = '.' + parts[-1]
                        extensions.append(last_ext)
                        full_ext = '.' + '.'.join(parts[1:])
                        if full_ext not in extensions:
                            extensions.append(full_ext)
        except Exception:
            pass

        mime_types = sorted({m for m in mime_candidates if m})
        mime_encodings = sorted({e for e in enc_candidates if e})
        coarse_types = sorted({_coarse_from_mime(m) for m in mime_types if m})

        if mime_types or mime_encodings or coarse_types or extensions:
            tbl_ft = pa.table({
                "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
                "hash": pa.array([params.file_hash], type=pa.string()),
                "mime_type": pa.array([mime_types], type=pa.list_(pa.string())),
                "mime_encoding": pa.array([mime_encodings], type=pa.list_(pa.string())),
                "file_type": pa.array([coarse_types], type=pa.list_(pa.string())),
                "extensions": pa.array([extensions], type=pa.list_(pa.string())),
                "extracted_by": pa.array(["tika"], type=pa.large_string()),
            })
            insert_arrow_idempotent(client, "file_types", tbl_ft)

    return {
        "mime_types": mime_types,
        "mime_encodings": mime_encodings,
        "coarse_types": coarse_types,
        "extensions": extensions,
    }
