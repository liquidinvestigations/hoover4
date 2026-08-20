"""MIME detection activities using GNU file and Magika."""

from temporalio import activity
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Set
import subprocess
import threading
import mimetypes
import os
from tasks.heartbeat import with_heartbeat


@dataclass
class DetectMimeParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int


def _run_file_multi(file_path: str) -> Tuple[List[str], List[str], List[str]]:
    """Run `file` to obtain possible multiple mime types, encodings, and extensions."""
    mime_types: Set[str] = set()
    encodings: Set[str] = set()
    extensions: Set[str] = set()

    def _collect_values(cmd: List[str], is_extension: bool = False) -> List[str]:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                return []
            out = res.stdout
            # Normalize GNU file multi-results sometimes represented with literal \012 sequences
            out = out.replace("\\012", "\n").replace("\\n", "\n")
            out = out.strip()
            if not out:
                return []
            vals: List[str] = []
            # file may prefix with "path: value"; may also contain multiple lines with -k
            for line in out.splitlines():
                # Remove optional "path: " prefix
                if ": " in line:
                    line = line.split(": ", 1)[1]
                # Lines may start with "- " for secondary matches
                line = line.lstrip()
                if line.startswith("- "):
                    line = line[2:]
                # After normalization, a single line may still contain embedded newlines; split again just in case
                parts_lines = [p for p in line.replace("\\012", "\n").splitlines() if p]
                for txt in parts_lines:
                    txt = txt.strip()
                    if not txt:
                        continue
                    if is_extension:
                        # Slash-separated list, filter unknowns
                        parts = [p.strip() for p in txt.split('/') if p.strip()]
                        for p in parts:
                            if '?' in p:
                                continue
                            if not p.startswith('.'):
                                vals.append('.' + p)
                            else:
                                vals.append(p)
                    else:
                        # Also split on " - " that may be inline separators
                        for token in [t.strip() for t in txt.split(' - ') if t.strip()]:
                            vals.append(token)
            return vals
        except Exception:
            return []

    # Collect using -k to keep going
    mime_types.update(_collect_values(["file", "-k", "--mime-type", file_path]))
    encodings.update(_collect_values(["file", "-k", "--mime-encoding", file_path]))
    extensions.update(_collect_values(["file", "-k", "--extension", file_path], is_extension=True))

    # Fallbacks
    if not mime_types or not encodings:
        guessed, enc = mimetypes.guess_type(file_path)
        if guessed:
            mime_types.add(guessed)
        if enc:
            encodings.add(enc)

    return sorted(mime_types), sorted(encodings), sorted(extensions)


def _extract_extensions(file_path: str) -> List[str]:
    base = os.path.basename(file_path)
    # Collect last extension and combined multi-part (e.g., .gz and .tar.gz)
    name_lower = base.lower()
    exts: List[str] = []
    # Handle multi-dot filenames
    parts = name_lower.split('.')
    if len(parts) > 1:
        last_ext = '.' + parts[-1]
        exts.append(last_ext)
        # Full extension chain (excluding the basename before first dot)
        full_ext = '.' + '.'.join(parts[1:])
        if full_ext not in exts:
            exts.append(full_ext)
    return exts


def _detect_gnu_file(params: DetectMimeParams,
                     file_multi: Tuple[List[str], List[str], List[str]] | None = None
                     ) -> Dict[str, Any]:
    """`file`'s view of the bytes. Pure: the caller decides where the row goes."""
    from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type

    mime_types_list, encodings_list, ext_list = file_multi or _run_file_multi(params.file_path)
    mime_types: List[str] = [m for m in mime_types_list if m]
    mime_encodings: List[str] = [e for e in encodings_list if e]
    coarse_types: List[str] = sorted({coarse_file_type(m) for m in mime_types if m})
    # Combine filename-derived extensions with `file --extension`
    extensions: List[str] = sorted(set(ext_list + _extract_extensions(params.file_path)))
    return {
        "mime_types": mime_types,
        "mime_encodings": mime_encodings,
        "coarse_types": coarse_types,
        "extensions": extensions,
    }


def _detect_magika(params: DetectMimeParams) -> Dict[str, Any]:
    """Google Magika's view of the bytes. Pure: the caller decides where the row goes."""
    # Import locally to avoid hard dependency at import time
    from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type

    res = identify_path_with_magika(params.file_path)
    # Use res.output (may be overwritten result)
    ct = res.output
    mime_types: List[str] = []
    mime_encodings: List[str] = []
    coarse_types: List[str] = []
    extensions: List[str] = []

    if getattr(res, 'ok', True) and ct:
        if getattr(ct, 'mime_type', None):
            mime_types.append(ct.mime_type)
        # Magika does not provide encodings; leave empty
        if getattr(ct, 'group', None):
            coarse_types.append(ct.group.lower())
        # Map additional coarse types via mime mapper as well
        if getattr(ct, 'mime_type', None):
            mapped = coarse_file_type(ct.mime_type)
            if mapped and mapped not in coarse_types:
                coarse_types.append(mapped)
        if getattr(ct, 'extensions', None):
            for ext in ct.extensions:
                if not ext:
                    continue
                if not ext.startswith('.'):
                    extensions.append('.' + ext.lower())
                else:
                    extensions.append(ext.lower())

    # Deduplicate and sort
    mime_types = sorted(set([m for m in mime_types if m]))
    mime_encodings = sorted(set([e for e in mime_encodings if e]))
    coarse_types = sorted(set([magicka_filetype_to_hoover_filetype(c) for c in coarse_types if c]))
    coarse_types2 = sorted(set([coarse_file_type(m) for m in mime_types if m]))
    coarse_types = sorted(set(coarse_types + coarse_types2) - set(""))
    extensions = sorted(set(extensions))
    return {
        "mime_types": mime_types,
        "mime_encodings": mime_encodings,
        "coarse_types": coarse_types,
        "extensions": extensions,
    }


_magika = None
_magika_lock = threading.Lock()


def reset_magika_for_tests() -> None:
    """Drop the process-wide detector so a test can re-count constructions."""
    global _magika
    with _magika_lock:
        _magika = None


def _magika_detector():
    """One Magika instance per process. Construction dominates identify_path."""
    global _magika
    if _magika is not None:
        return _magika
    with _magika_lock:
        if _magika is None:
            try:
                from magika import Magika
            except Exception as e:
                raise RuntimeError(f"magika not available or failed to import: {e}")
            _magika = Magika()
        return _magika


def identify_path_with_magika(file_path: str):
    """Identify ``file_path`` through the process-wide Magika detector.

    Magika is not documented as thread-safe, so identify runs under the same
    lock as construction. Import stays inside the first call so a missing
    magika fails in the activity, not at worker import.
    """
    detector = _magika_detector()
    with _magika_lock:
        return detector.identify_path(file_path)


def magicka_filetype_to_hoover_filetype(filetype: str) -> str:
    if filetype == "document":
        return "doc"
    if filetype == "unknown":
        return "other"
    if not filetype:
        return "other"
    return filetype

#: Extensions `mimetypes` does not know, or knows wrongly for this corpus. The name
#: detector is the only one that can be right about a `.docx` whose bytes are a zip and
#: about an extension-less-format file whose bytes are plain text, so its table is worth
#: curating rather than deferring entirely to the stdlib.
_EXTRA_EXTENSION_MIMES = {
    '.eml': 'message/rfc822',
    '.emlx': 'message/x-emlx',
    '.mbox': 'application/mbox',
    '.msg': 'application/vnd.ms-outlook',
    '.pst': 'application/x-hoover-pst',
    '.ost': 'application/x-hoover-pst',
    '.7z': 'application/x-7z-compressed',
    '.rar': 'application/vnd.rar',
    '.zst': 'application/x-zstd',
    '.lz': 'application/x-lzip',
    '.odt': 'application/vnd.oasis.opendocument.text',
    '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
    '.odp': 'application/vnd.oasis.opendocument.presentation',
    '.odg': 'application/vnd.oasis.opendocument.graphics',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.epub': 'application/epub+zip',
    '.rtf': 'application/rtf',
    '.heic': 'image/heic',
    '.webp': 'image/webp',
    '.avif': 'image/avif',
}


def mime_types_from_name(file_path: str) -> Tuple[List[str], List[str]]:
    """MIME types implied by a filename, and the extensions they came from.

    No file read at all: this is the detector that knows a `.docx` is a document while
    every content detector is looking at a zip.
    """
    extensions = _extract_extensions(file_path)
    mime_types: Set[str] = set()
    for ext in extensions:
        curated = _EXTRA_EXTENSION_MIMES.get(ext)
        if curated:
            mime_types.add(curated)
            continue
        guessed, _enc = mimetypes.guess_type('x' + ext)
        if guessed:
            mime_types.add(guessed)
    return sorted(mime_types), extensions


def _store_file_types_many(params: DetectMimeParams, rows: List[Dict[str, Any]]) -> None:
    """One `file_types` insert for several detectors' rows.

    Each detector keeps its own row, keyed by `extracted_by` -- the canonical resolution
    weighs them against each other and needs them distinct. What is shared is the round
    trip: four separate inserts of one row each cost four of them for no gain.
    """
    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    import pyarrow as pa

    if not rows:
        return
    n = len(rows)
    with get_collection_client(params.collectionname) as client:
        tbl = pa.table({
            "collection_dataset": pa.array([params.collection_dataset] * n, type=pa.string()),
            "hash": pa.array([params.file_hash] * n, type=pa.string()),
            "mime_type": pa.array([r["mime_types"] for r in rows], type=pa.list_(pa.string())),
            "mime_encoding": pa.array([r.get("mime_encodings") or [] for r in rows],
                                      type=pa.list_(pa.string())),
            "file_type": pa.array([r["coarse_types"] for r in rows], type=pa.list_(pa.string())),
            "extensions": pa.array([r.get("extensions") or [] for r in rows],
                                   type=pa.list_(pa.string())),
            "extracted_by": pa.array([r["extracted_by"] for r in rows], type=pa.large_string()),
        })
        insert_arrow_idempotent(client, "file_types", tbl)


# The four detectors that run locally, in the order the fan-out used to schedule them.
# Tika is deliberately absent: it lives on its own task queue because it holds an
# extractous helper, and merging it here would put that helper on the common worker.
LOCAL_DETECTORS = ("file", "magika", "extension", "content_sniff")


@activity.defn
@with_heartbeat
def detect_mime_all(params: DetectMimeParams) -> Dict[str, Any]:
    """All four local detectors in one activity, one `file` run, one insert.

    Each detector is cheap -- tens of milliseconds -- so scheduling four Temporal
    activities to carry them costs several times what the work does. They are also not
    independent: `file` and the content sniff both need `file`'s output, which is a
    subprocess launch each. Running them together pays for that once.

    Failure stays per detector. One that raises contributes no `file_types` row and
    reports its error under its own name in `errors`, exactly as a failed activity in
    the old fan-out did; the other three still store and still return.
    """
    file_multi = None
    try:
        file_multi = _run_file_multi(params.file_path)
    except Exception:
        # Leave it None and let the two detectors that want it fail individually with
        # their own message, rather than failing all four here.
        pass

    runners = {
        "file": lambda: _detect_gnu_file(params, file_multi),
        "magika": lambda: _detect_magika(params),
        "extension": lambda: _detect_from_name(params),
        "content_sniff": lambda: _detect_by_content(params, file_multi),
    }
    results: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    rows: List[Dict[str, Any]] = []
    for name in LOCAL_DETECTORS:
        try:
            res = runners[name]()
        except Exception as exc:
            errors[name] = "%s: %s" % (type(exc).__name__, exc)
            continue
        results[name] = res
        rows.append({"extracted_by": name, **res})
    _store_file_types_many(params, rows)
    return {"detectors": results, "errors": errors}


def _detect_from_name(params: DetectMimeParams) -> Dict[str, Any]:
    """Detection from the filename alone, stored as its own `file_types` row.

    The extension used to be consulted only as a fallback for when `file` returned
    nothing at all, so for a `.docx` — which `file` names confidently, and names a zip —
    it was discarded. It is a first-class parallel detection, and the canonical
    resolution weighs it against the content detectors instead of behind them.
    """
    from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type

    mime_types, extensions = mime_types_from_name(params.file_path)
    coarse_types = sorted({coarse_file_type(m) for m in mime_types if m})
    return {
        "mime_types": mime_types,
        "mime_encodings": [],
        "coarse_types": coarse_types,
        "extensions": extensions,
    }


def _magic_output(file_path: str) -> str:
    """`file -kbpL` in its human-readable form, which names two things MIME does not."""
    try:
        res = subprocess.run(["file", "-kbpL", file_path], capture_output=True, text=True)
    except Exception:
        return ""
    if res.returncode != 0:
        return ""
    return (res.stdout or "").split(r"\012-")[0].strip()


def _detect_by_content(params: DetectMimeParams,
                       file_multi: Tuple[List[str], List[str], List[str]] | None = None
                       ) -> Dict[str, Any]:
    """The content sniff: email, plus the two rules libmagic still gets wrong.

    Emails first, because that is the whole reason this detector exists — an
    extension-less RFC 822 message is `text/plain` to every other detector in the
    fan-out, so a maildir indexes as text and never produces an `emails` row. The sniff
    runs only behind its cheap gate (`should_check_email`), which keeps it off the ~98%
    of a mixed corpus that no amount of header reading will turn into mail.

    Delimited text is sniffed after email and only when the email sniff declined: an
    extension-less export is `text/plain` to every other detector too, and an RFC 822
    message read with `:` as a delimiter is a perfectly rectangular two-column table. The
    table sniff excludes `:` outright and is never offered a message this one accepted.

    The other two rules are inherited from the previous generation of this codebase and
    are still true: libmagic names a PST file only in its human-readable output, and it
    calls a legacy Excel workbook a generic OLE container.
    """
    from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type
    from tasks.P3_parse_files.sniff_email import should_check_email, sniff_email_path
    from tasks.P3_parse_files.sniff_table import should_check_table, sniff_table_path

    magic_output = _magic_output(params.file_path)
    base_mimes, _encodings, _exts = file_multi or _run_file_multi(params.file_path)

    mime_types: Set[str] = set()
    details: Dict[str, Any] = {}

    is_email = False
    if should_check_email(base_mimes, magic_output):
        sniff = sniff_email_path(params.file_path)
        if sniff is not None:
            is_email = True
            mime_types.add(sniff.mime_type)
            details["email_headers_seen"] = sniff.headers
            details["emlx_prefix_bytes"] = sniff.emlx_prefix_bytes

    if should_check_table(base_mimes, is_email=is_email):
        table = sniff_table_path(params.file_path)
        if table is not None:
            mime_types.add(table.mime_type)
            details["table_delimiter"] = table.delimiter
            details["table_field_count"] = table.field_count

    if magic_output.startswith("Microsoft Outlook email folder") \
            or magic_output.startswith("Microsoft Outlook Personal"):
        mime_types.add("application/x-hoover-pst")

    if "application/x-ole-storage" in base_mimes:
        mime_types.add("application/vnd.ms-excel")

    mime_list = sorted(mime_types)
    coarse_types = sorted({coarse_file_type(m) for m in mime_list if m})
    return {
        "mime_types": mime_list,
        "mime_encodings": [],
        "coarse_types": coarse_types,
        "extensions": [],
        **details,
    }
