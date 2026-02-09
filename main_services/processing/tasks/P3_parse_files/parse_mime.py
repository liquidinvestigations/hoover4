"""MIME detection activities using GNU file and Magika."""

from temporalio import activity
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Set
import subprocess
import mimetypes
import os


@dataclass
class DetectMimeParams:
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


@activity.defn
def detect_mime_with_gnu_file(params: DetectMimeParams) -> Dict[str, Any]:
    """Activity that runs `file` to detect MIME/encoding, stores to file_types, and returns lists."""
    from database.clickhouse import get_clickhouse_client
    from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type
    import pyarrow as pa

    mime_types_list, encodings_list, ext_list = _run_file_multi(params.file_path)
    mime_types: List[str] = [m for m in mime_types_list if m]
    mime_encodings: List[str] = [e for e in encodings_list if e]
    coarse_types: List[str] = sorted({coarse_file_type(m) for m in mime_types if m})
    # Combine filename-derived extensions with `file --extension`
    extensions: List[str] = sorted(set(ext_list + _extract_extensions(params.file_path)))

    # Insert into ClickHouse file_types with arrays and extracted_by='file'
    with get_clickhouse_client() as client:
        tbl = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "hash": pa.array([params.file_hash], type=pa.string()),
            "mime_type": pa.array([mime_types], type=pa.list_(pa.string())),
            "mime_encoding": pa.array([mime_encodings], type=pa.list_(pa.string())),
            "file_type": pa.array([coarse_types], type=pa.list_(pa.string())),
            "extensions": pa.array([extensions], type=pa.list_(pa.string())),
            "extracted_by": pa.array(["file"], type=pa.large_string()),
        })
        client.insert_arrow("file_types", tbl)

    return {
        "mime_types": mime_types,
        "mime_encodings": mime_encodings,
        "coarse_types": coarse_types,
        "extensions": extensions,
    }


@activity.defn
def detect_mime_with_magika(params: DetectMimeParams) -> Dict[str, Any]:
    """Activity that uses Google Magika to detect content type and stores it.

    Writes a row to file_types with extracted_by='magika' and returns lists.
    """
    # Import locally to avoid hard dependency at import time
    from database.clickhouse import get_clickhouse_client
    from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type
    import pyarrow as pa
    try:
        from magika import Magika
    except Exception as e:
        # Surface structured error for workflow error recording
        raise RuntimeError(f"magika not available or failed to import: {e}")

    m = Magika()
    res = m.identify_path(params.file_path)
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

    with get_clickhouse_client() as client:
        tbl = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "hash": pa.array([params.file_hash], type=pa.string()),
            "mime_type": pa.array([mime_types], type=pa.list_(pa.string())),
            "mime_encoding": pa.array([mime_encodings], type=pa.list_(pa.string())),
            "file_type": pa.array([coarse_types], type=pa.list_(pa.string())),
            "extensions": pa.array([extensions], type=pa.list_(pa.string())),
            "extracted_by": pa.array(["magika"], type=pa.large_string()),
        })
        client.insert_arrow("file_types", tbl)

    return {
        "mime_types": mime_types,
        "mime_encodings": mime_encodings,
        "coarse_types": coarse_types,
        "extensions": extensions,
    }


def magicka_filetype_to_hoover_filetype(filetype: str) -> str:
    if filetype == "document":
        return "doc"
    if filetype == "unknown":
        return "other"
    if not filetype:
        return "other"
    return filetype