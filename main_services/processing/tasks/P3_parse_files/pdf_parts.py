"""Prepare source ranges and persist searchable parts with durable text completion."""

import base64
import dataclasses
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager

from temporalio import activity

from tasks.heartbeat import heartbeat_pump, with_heartbeat
from tasks.P3_parse_files.batch_runner import BatchFile, BatchResult, FileResult, StageBatchParams, run_batch
from tasks.task_timing import SkippedOutcome
from tasks.text_sources import (
    MIN_OCR_IMAGE_PX, OCR_PAGE_IMAGE_COVERAGE, OCR_PAGE_TEXT_FLOOR,
    OCR_PAGE_RULE_VERSION, PDF_SEGMENTATION_VERSION, pdf_ocr_extracted_by,
)

PART_TARGET_BYTES = 25_000_000
PART_MAX_PAGES = 100


def source_ranges(page_count: int, size_bytes: int) -> list[tuple[int, int]]:
    """Choose consecutive ranges once from the source page count and byte count."""
    width = min(PART_MAX_PAGES, max(1, page_count * PART_TARGET_BYTES // max(size_bytes, 1)))
    return [(first, min(page_count, first + width - 1))
            for first in range(1, page_count + 1, width)]


def live_hashes(client, dataset: str, hashes: list[str]) -> set[str]:
    """Return the hashes that a current source path reaches."""
    if not hashes:
        return set()
    result = set()
    for start in range(0, len(hashes), 500):
        result.update(row[0] for row in client.query(
            "SELECT DISTINCT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} "
            "AND is_deleted = 0 AND hash IN {h:Array(String)}",
            parameters={"cd": dataset, "h": hashes[start:start + 500]},
        ).result_rows)
    return result



def stored_path(path: str) -> tuple[str, str]:
    """Read the bucket and object key from a stored source path."""
    if not path.startswith("s3://"):
        return "", ""
    bucket, _, key = path[5:].partition("/")
    return bucket, key


def write_row(client, table: str, row: dict, *, durable: bool = True) -> None:
    """Write one manifest row with the declared integer and array types."""
    import pyarrow as pa
    from database.clickhouse import insert_arrow_durable, insert_parser_arrow
    types = {
        "segmentation": pa.uint16(), "part_index": pa.uint16(), "part_count": pa.uint16(),
        "first_page": pa.uint32(), "last_page": pa.uint32(), "page_count": pa.uint32(),
        "rule_version": pa.uint16(), "size_bytes": pa.uint64(), "run_time_ms": pa.uint32(),
        "text_complete": pa.uint8(), "borrows_source": pa.uint8(), "is_deleted": pa.uint8(),
        "ocr_pages": pa.list_(pa.uint32()), "page_numbers": pa.list_(pa.uint32()),
        "page_texts": pa.list_(pa.string()),
    }
    arrow = pa.table({key: pa.array([value], type=types.get(key, pa.string()))
                      for key, value in row.items()})
    (insert_arrow_durable if durable else insert_parser_arrow)(client, table, arrow)


def source_parts(client, dataset: str, file_hash: str, kind: str) -> list[dict]:
    rows = client.query(
        "SELECT part_index, first_page, last_page, s3_path, size_bytes FROM pdf_parts FINAL "
        "WHERE collection_dataset = {cd:String} AND hash = {h:String} "
        "AND source_kind = {kind:String} AND segmentation = {s:UInt16} ORDER BY part_index",
        parameters={"cd": dataset, "h": file_hash, "kind": kind, "s": PDF_SEGMENTATION_VERSION},
    ).result_rows
    return [dict(zip(("part_index", "first_page", "last_page", "s3_path", "size_bytes"), row))
            for row in rows]


def variant_parts(client, dataset: str, file_hash: str, kind: str,
                  engine: str, languages: str) -> list[dict]:
    rows = client.query(
        "SELECT part_index, first_page, last_page, blob_key, size_bytes, page_numbers, "
        "page_texts, borrows_source FROM pdf_ocr_parts FINAL "
        "WHERE collection_dataset = {cd:String} AND hash = {h:String} "
        "AND source_kind = {kind:String} AND engine = {en:String} AND languages = {la:String} "
        "AND segmentation = {s:UInt16} AND is_deleted = 0 ORDER BY part_index",
        parameters={"cd": dataset, "h": file_hash, "kind": kind, "en": engine,
                    "la": languages, "s": PDF_SEGMENTATION_VERSION},
    ).result_rows
    return [dict(zip(("part_index", "first_page", "last_page", "blob_key", "size_bytes",
                      "page_numbers", "page_texts", "borrows_source"), row)) for row in rows]


def variant_result(client, dataset: str, file_hash: str, engine: str, languages: str):
    rows = client.query(
        "SELECT blob_key, blob_hash, page_count, size_bytes, run_time_ms, source_kind, form, "
        "part_count, text_complete FROM pdf_ocr_results FINAL "
        "WHERE collection_dataset = {cd:String} AND pdf_hash = {h:String} "
        "AND engine = {en:String} AND languages = {la:String} AND is_deleted = 0",
        parameters={"cd": dataset, "h": file_hash, "en": engine, "la": languages},
    ).result_rows
    if not rows:
        return None
    return dict(zip(("blob_key", "blob_hash", "page_count", "size_bytes", "run_time_ms",
                     "source_kind", "form", "part_count", "text_complete"), rows[0]))


@contextmanager
def source_file(client, params: StageBatchParams, file: BatchFile):
    """Use the downloaded original or download the stored Office preview."""
    if file.source_kind != "preview":
        yield file.file_path
        return
    from database.s3 import get_s3_client
    rows = client.query(
        "SELECT s3_path FROM pdf_previews FINAL WHERE collection_dataset = {cd:String} "
        "AND hash = {h:String}", parameters={"cd": params.collection_dataset, "h": file.item_hash},
    ).result_rows
    if not rows:
        raise RuntimeError("Office PDF preview is missing")
    bucket, key = stored_path(rows[0][0])
    with tempfile.TemporaryDirectory(prefix="hoover4-pdf-source-") as folder:
        path = os.path.join(folder, "source.pdf")
        get_s3_client().fget_object(bucket, key, path)
        yield path


def page_needs(path: str, count: int, pages: list[str]) -> list[int]:
    """Select pages by native characters and displayed image coverage."""
    from tasks.P3_parse_files.parse_pdf import _PDF_SUBPROCESS_TIMEOUT_S
    import subprocess
    sizes = {}
    info = subprocess.run(["pdfinfo", "-f", "1", "-l", str(count), path],
                          capture_output=True, timeout=_PDF_SUBPROCESS_TIMEOUT_S, check=True)
    for match in re.finditer(r"^Page\s+(\d+) size:\s+([\d.]+) x ([\d.]+) pts",
                             info.stdout.decode("utf-8", "replace"), re.M):
        sizes[int(match[1])] = float(match[2]) * float(match[3])
    generic = re.search(r"^Page size:\s+([\d.]+) x ([\d.]+) pts",
                        info.stdout.decode("utf-8", "replace"), re.M)
    if generic:
        for page in range(1, count + 1):
            sizes.setdefault(page, float(generic[1]) * float(generic[2]))
    images = subprocess.run(["pdfimages", "-list", path], capture_output=True,
                            timeout=_PDF_SUBPROCESS_TIMEOUT_S, check=True)
    coverage = {}
    for line in images.stdout.decode("utf-8", "replace").splitlines():
        fields = line.split()
        if len(fields) < 14 or fields[2] != "image":
            continue
        try:
            page, width, height = int(fields[0]), int(fields[3]), int(fields[4])
            xp, yp = float(fields[12]), float(fields[13])
        except ValueError:
            continue
        if min(width, height) < MIN_OCR_IMAGE_PX or min(xp, yp) <= 0:
            continue
        area = width / xp * 72 * height / yp * 72
        coverage[page] = max(coverage.get(page, 0), area / sizes.get(page, area or 1))
    return [page for page in range(1, count + 1)
            if coverage.get(page, 0) >= OCR_PAGE_IMAGE_COVERAGE
            or math.isclose(coverage.get(page, 0), OCR_PAGE_IMAGE_COVERAGE, rel_tol=1e-12)
            or len("".join((pages[page - 1] if page <= len(pages) else "").split())) < OCR_PAGE_TEXT_FLOOR]


def split_pdf(source: str, dest: str, first: int, last: int) -> None:
    """Copy one source page range with qpdf."""
    from tasks.P3_parse_files.parse_pdf import _run_qpdf, _qpdf_succeeded
    result = _run_qpdf(["--empty", "--warning-exit-0", "--pages", source,
                        f"{first}-{last}", "--", dest])
    if not _qpdf_succeeded(result):
        raise RuntimeError(f"PDF split failed for pages {first}-{last}: {result.stderr[:200]!r}")


def prepare_pdf(params: StageBatchParams, file: BatchFile, *, compact: bool = False) -> dict | SkippedOutcome:
    from database.clickhouse import get_collection_client
    from database.s3 import collection_bucket, get_s3_client
    from tasks.P3_parse_files.parse_pdf import _qpdf_show_npages, _pdftotext_pages, _insert_pdf_text_pages
    from tasks.P3_parse_files.insert_batch import current_batch
    cd, h, kind = params.collection_dataset, file.item_hash, file.source_kind
    with get_collection_client(params.collectionname) as client:
        if h not in live_hashes(client, cd, [h]):
            return SkippedOutcome("pdf_source_removed")
        stored = source_parts(client, cd, h, kind)
        need_rows = client.query(
            "SELECT page_count, ocr_pages FROM ocr_page_needs FINAL "
            "WHERE collection_dataset = {cd:String} AND hash = {h:String} "
            "AND source_kind = {kind:String} AND rule_version = {r:UInt16}",
            parameters={"cd": cd, "h": h, "kind": kind, "r": OCR_PAGE_RULE_VERSION}).result_rows
        if need_rows and stored:
            count, needs = need_rows[0]
            expected = 1
            for part in stored:
                if part["first_page"] != expected:
                    break
                expected = part["last_page"] + 1
            else:
                if expected == count + 1:
                    return preparation_value(client, params, file, stored, count, list(needs), compact=compact)
        with source_file(client, params, file) as path, heartbeat_pump(f"PDF preparation {h[:8]}"):
            count = file.page_count or _qpdf_show_npages(path, h)
            size = os.path.getsize(path)
            pages = _pdftotext_pages(path)
            if len(pages) != count:
                raise RuntimeError("PDF native text extraction did not return every page")
            needs = page_needs(path, count, pages)
            ranges = source_ranges(count, size)
            bucket = collection_bucket(params.collectionname)
            source_path = ""
            table, column = ("pdf_previews", "hash") if kind == "preview" else ("blobs", "blob_hash")
            rows = client.query(f"SELECT s3_path FROM {table} FINAL "
                                f"WHERE collection_dataset = {{cd:String}} AND {column} = {{h:String}} LIMIT 1",
                                parameters={"cd": cd, "h": h}).result_rows
            if rows:
                source_path = rows[0][0]
            with tempfile.TemporaryDirectory(prefix="hoover4-pdf-parts-") as folder:
                parts = []
                for index, (first, last) in enumerate(ranges, 1):
                    part_path, part_size = source_path, size
                    if len(ranges) > 1:
                        dest = os.path.join(folder, f"{index}.pdf")
                        split_pdf(path, dest, first, last)
                        key = f"derived/pdf-parts/{cd}/{h}/{kind}/s{PDF_SEGMENTATION_VERSION}/{first}-{last}.pdf"
                        get_s3_client().fput_object(bucket, key, dest, content_type="application/pdf")
                        part_path, part_size = f"s3://{bucket}/{key}", os.path.getsize(dest)
                    row = dict(collection_dataset=cd, hash=h, source_kind=kind,
                               segmentation=PDF_SEGMENTATION_VERSION, part_index=index,
                               first_page=first, last_page=last, s3_path=part_path, size_bytes=part_size)
                    write_row(client, "pdf_parts", row)
                    parts.append({"part_index": index, "first_page": first, "last_page": last,
                                  "part_key": part_path, "file_size_bytes": part_size,
                                  "ocr_pages": [page - first + 1 for page in needs if first <= page <= last]})
            if kind == "original":
                _insert_pdf_text_pages(params.collectionname, cd, h, pages)
                if current_batch() is not None:
                    current_batch().flush()
            write_row(client, "ocr_page_needs", dict(collection_dataset=cd, hash=h,
                      source_kind=kind, rule_version=OCR_PAGE_RULE_VERSION, page_count=count, ocr_pages=needs))
            return preparation_value(client, params, file, source_parts(client, cd, h, kind), count, needs, compact=compact)


def preparation_value(client, params: StageBatchParams, file: BatchFile,
                      parts: list[dict], count: int, needs: list[int], *, compact: bool = False) -> dict:
    """Return legacy part jobs or compact source identities with completion flags."""
    rows = client.query(
        "SELECT DISTINCT engine FROM pdf_ocr_results FINAL "
        "WHERE collection_dataset = {cd:String} AND pdf_hash = {h:String} "
        "AND is_deleted = 0 AND text_complete = 0",
        parameters={"cd": params.collection_dataset, "h": file.item_hash}).result_rows
    if compact:
        from tasks.ocr_targets import language_settings, engine_passes
        from tasks.text_sources import OCR_ENGINES
        settings = language_settings(params.collection_dataset)
        return dict(segmentation=PDF_SEGMENTATION_VERSION,
                    source_digest=source_digest(parts, count, needs), part_count=len(parts),
                    page_count=count, source_kind=file.source_kind, has_ocr_pages=bool(needs),
                    saved_engines=[row[0] for row in rows],
                    languages={engine: engine_passes(engine, settings[engine].value)
                               for engine in OCR_ENGINES},
                    settings_versions={engine: dataclasses.asdict(settings[engine].version)
                                       for engine in OCR_ENGINES},
                    part_lists=min(4, max(1, int(os.getenv("HOOVER4_OCR_PDF_FILES_PER_BATCH", "4")))))
    return {"parts": [{"part_index": part["part_index"], "first_page": part["first_page"],
                       "last_page": part["last_page"], "part_key": part["s3_path"],
                       "file_size_bytes": part["size_bytes"],
                       "ocr_pages": [page - part["first_page"] + 1 for page in needs
                                     if part["first_page"] <= page <= part["last_page"]]}
                      for part in parts], "page_count": count,
            "source_kind": file.source_kind, "has_ocr_pages": bool(needs),
            "saved_engines": [row[0] for row in rows],
            "part_lists": max(1, int(os.getenv("HOOVER4_OCR_PDF_FILES_PER_BATCH", "4")))}



@activity.defn
@with_heartbeat
def pdf_prepare_batch(params: StageBatchParams) -> BatchResult:
    """Prepare the sources and native parent text for one group."""
    return run_batch("pdf_prepare_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=lambda f: prepare_pdf(params, f),
                     task_name="pdf_prepare")


def store_part(client, params: StageBatchParams, file: BatchFile, languages: str,
               *, key: str, size: int, pages: list[tuple[int, str]], borrowed: bool = False) -> None:
    write_row(client, "pdf_ocr_parts", dict(collection_dataset=params.collection_dataset,
              hash=file.item_hash, source_kind=file.source_kind, engine=params.engine,
              languages=languages, segmentation=PDF_SEGMENTATION_VERSION, part_index=file.part_index,
              first_page=file.first_page, last_page=file.last_page, blob_key=key, size_bytes=size,
              page_numbers=[number for number, _ in pages], page_texts=[text for _, text in pages],
              borrows_source=int(borrowed)))


def build_part(params: StageBatchParams, file: BatchFile) -> str | SkippedOutcome:
    from database.clickhouse import get_collection_client
    from tasks.ocr_pdf_client import build_ocr_pdf, service_configured, engines_for_provider
    from tasks.P3_parse_files.parse_ocr_pdf import _passes_for, MAX_INLINE_PDF_BYTES
    if not service_configured() or params.engine not in engines_for_provider():
        return SkippedOutcome("pdf_builder_disabled")
    passes = getattr(params, "languages", None)
    if passes is None:
        passes = _passes_for(params.engine, params.collection_dataset)
    with get_collection_client(params.collectionname) as client:
        if file.item_hash not in live_hashes(client, params.collection_dataset, [file.item_hash]):
            return SkippedOutcome("pdf_source_removed")
        for languages in passes:
            result = variant_result(client, params.collection_dataset, file.item_hash, params.engine, languages)
            if result and (result["text_complete"] or result["form"] == "raster"):
                continue
            existing = variant_parts(client, params.collection_dataset, file.item_hash,
                                     file.source_kind, params.engine, languages)
            if any(part["part_index"] == file.part_index and part["first_page"] == file.first_page
                   and part["last_page"] == file.last_page for part in existing):
                continue
            if not file.ocr_pages:
                store_part(client, params, file, languages, key="", size=file.file_size_bytes,
                           pages=[], borrowed=True)
                continue
            bucket, key = stored_path(file.part_key)
            inline = ""
            if not key:
                with open(file.file_path, "rb") as handle:
                    data = handle.read(MAX_INLINE_PDF_BYTES + 1)
                if len(data) > MAX_INLINE_PDF_BYTES:
                    raise RuntimeError("PDF inline source exceeds its input limit")
                inline = base64.b64encode(data).decode("ascii")
            sources = source_parts(client, params.collection_dataset, file.item_hash, file.source_kind)
            one_part = len(sources) == 1
            dest = f"derived/ocr-pdf/{params.collection_dataset}/{file.item_hash}/{params.engine}+{languages}"
            dest += ".pdf" if one_part else f"/s{PDF_SEGMENTATION_VERSION}/{file.first_page}-{file.last_page}.pdf"
            outcome = build_ocr_pdf(collectionname=params.collectionname,
                collection_dataset=params.collection_dataset, pdf_hash=file.item_hash,
                engine=params.engine, languages=languages, source_key=key, source_b64=inline,
                dest_key=dest, source_bucket=bucket, ocr_pages=file.ocr_pages)
            numbers = [int(page["page"]) for page in outcome.pages]
            if numbers != file.ocr_pages:
                raise RuntimeError("PDF builder returned incomplete selected-page text")
            store_part(client, params, file, languages, key=outcome.dest_key, size=outcome.size_bytes,
                       pages=[(file.first_page + int(page["page"]) - 1, page["text"])
                              for page in outcome.pages])
    return "pdf_part_complete"


@activity.defn
@with_heartbeat
def run_ocr_pdf_parts_batch(params: StageBatchParams) -> BatchResult:
    """Build each missing searchable part in sequential batch order."""
    result = run_batch("run_ocr_pdf_parts_batch", params.files,
                       key=lambda f: f"{f.item_hash}:{f.first_page}-{f.last_page}",
                       size=lambda f: f.file_size_bytes, step=lambda f: build_part(params, f),
                       task_name="run_ocr_pdf_and_store")
    for item, file in zip(result.results, params.files):
        item.item_hash = file.item_hash
    return result


def covered_parts(source: list[dict], parts: list[dict]) -> bool:
    """Require each current source range once, in consecutive page order."""
    if not source or len(source) != len(parts):
        return False
    next_page = 1
    for expected, actual in zip(source, parts):
        if expected["first_page"] != next_page:
            return False
        if any(expected[key] != actual[key] for key in ("part_index", "first_page", "last_page")):
            return False
        if len(actual["page_numbers"]) != len(actual["page_texts"]):
            return False
        next_page = expected["last_page"] + 1
    return True


def finalize_variant(client, params: StageBatchParams, file: BatchFile,
                     languages: str, result: dict | None = None) -> None:
    from tasks.P3_parse_files.parse_common import insert_text_pages
    from tasks.P3_parse_files.insert_batch import current_batch
    source = source_parts(client, params.collection_dataset, file.item_hash, file.source_kind)
    parts = variant_parts(client, params.collection_dataset, file.item_hash,
                          file.source_kind, params.engine, languages)
    if not covered_parts(source, parts):
        raise RuntimeError(f"Searchable PDF parts do not cover every source range for {file.item_hash}")
    pages = [(int(number), text) for part in parts
             for number, text in zip(part["page_numbers"], part["page_texts"])]
    if len({page for page, _ in pages}) != len(pages):
        raise RuntimeError("Searchable PDF part text has duplicate page identities")
    insert_text_pages(params.collectionname, params.collection_dataset, file.item_hash,
                      pdf_ocr_extracted_by(params.engine, languages), pages)
    if current_batch() is not None:
        current_batch().flush()
    direct = parts[0]["blob_key"] if len(parts) == 1 else ""
    row = dict(result or {})
    row.update(collection_dataset=params.collection_dataset, pdf_hash=file.item_hash,
               engine=params.engine, languages=languages, source_kind=file.source_kind,
               form=row.get("form", "overlay"), blob_key=row.get("blob_key", direct),
               blob_hash=row.get("blob_hash", ""), page_count=source[-1]["last_page"],
               size_bytes=row.get("size_bytes", sum(part["size_bytes"] for part in parts)),
               run_time_ms=row.get("run_time_ms", 0), part_count=len(parts), text_complete=1)
    write_row(client, "pdf_ocr_results", row)


def backfill_saved_pdf(client, params: StageBatchParams, file: BatchFile,
                       languages: str, result: dict, returned_pages: list[dict] | None = None) -> None:
    """Recover stored output text and parts using the current source segmentation."""
    from database.s3 import get_s3_client, collection_bucket
    from tasks.P3_parse_files.parse_pdf import _pdftotext_pages
    source = source_parts(client, params.collection_dataset, file.item_hash, file.source_kind)
    if not source:
        prepared = prepare_pdf(params, file)
        if isinstance(prepared, SkippedOutcome):
            return
        source = source_parts(client, params.collection_dataset, file.item_hash, file.source_kind)
    bucket = collection_bucket(params.collectionname)
    with tempfile.TemporaryDirectory(prefix="hoover4-pdf-backfill-") as folder:
        path = os.path.join(folder, "saved.pdf")
        get_s3_client().fget_object(bucket, result["blob_key"], path)
        if returned_pages is None:
            if result["form"] != "raster":
                raise RuntimeError("Overlay OCR text requires retained part text")
            texts = _pdftotext_pages(path)
            if len(texts) != source[-1]["last_page"]:
                raise RuntimeError("Stored raster text does not cover source pages")
            pages = dict(enumerate(texts, 1))
        else:
            pages = {int(page["page"]): page["text"] for page in returned_pages}
        for part in source:
            first, last = part["first_page"], part["last_page"]
            key, size = result["blob_key"], result["size_bytes"]
            if len(source) > 1:
                dest = os.path.join(folder, f"{part['part_index']}.pdf")
                split_pdf(path, dest, first, last)
                key = (f"derived/ocr-pdf/{params.collection_dataset}/{file.item_hash}/"
                       f"{params.engine}+{languages}/s{PDF_SEGMENTATION_VERSION}/{first}-{last}.pdf")
                get_s3_client().fput_object(bucket, key, dest, content_type="application/pdf")
                size = os.path.getsize(dest)
            item = dataclasses.replace(file, part_index=part["part_index"], first_page=first, last_page=last)
            store_part(client, params, item, languages, key=key, size=size,
                       pages=[(number, pages[number]) for number in range(first, last + 1) if number in pages])
    if returned_pages is not None and len(source) > 1:
        get_s3_client().remove_object(bucket, result["blob_key"])
        result = {**result, "blob_key": "", "blob_hash": "",
                  "size_bytes": sum(part["size_bytes"] for part in variant_parts(
                      client, params.collection_dataset, file.item_hash, file.source_kind, params.engine, languages))}
    finalize_variant(client, params, file, languages, result)


def recover_legacy_variant(client, params, languages: str) -> bool:
    """Complete retained legacy overlay parts before another whole-file OCR request."""
    from database.s3 import get_s3_client, collection_bucket
    from tasks.ocr_pdf_client import derived_key
    source = source_parts(client, params.collection_dataset, params.pdf_hash, "original")
    manifest = variant_parts(client, params.collection_dataset, params.pdf_hash, "original", params.engine, languages)
    if not covered_parts(source, manifest):
        return False
    if len(source) > 1:
        try:
            get_s3_client().remove_object(collection_bucket(params.collectionname),
                derived_key(params.collection_dataset, params.pdf_hash, params.engine, languages))
        except Exception as exc:
            if getattr(exc, "code", "") != "NoSuchKey":
                raise
    stage = StageBatchParams(params.collectionname, params.collection_dataset, "", engine=params.engine)
    finalize_variant(client, stage, BatchFile(params.pdf_hash, params.file_path), languages)
    return True


def complete_pdf(params: StageBatchParams, file: BatchFile) -> str | SkippedOutcome:
    from database.clickhouse import get_collection_client
    from tasks.P3_parse_files.parse_ocr_pdf import _passes_for
    from tasks.ocr_pdf_client import service_configured, engines_for_provider
    if not service_configured() or params.engine not in engines_for_provider():
        return SkippedOutcome("pdf_builder_disabled")
    with get_collection_client(params.collectionname) as client:
        if file.item_hash not in live_hashes(client, params.collection_dataset, [file.item_hash]):
            return SkippedOutcome("pdf_source_removed")
        passes = getattr(params, "languages", None)
        for languages in (passes if passes is not None else _passes_for(params.engine, params.collection_dataset)):
            result = variant_result(client, params.collection_dataset, file.item_hash, params.engine, languages)
            if result and result["text_complete"]:
                continue
            if result and result["form"] == "raster":
                backfill_saved_pdf(client, params, file, languages, result)
            else:
                finalize_variant(client, params, file, languages, result)
    return "pdf_variant_complete"


@activity.defn
@with_heartbeat
def pdf_ocr_finalize_batch(params: StageBatchParams) -> BatchResult:
    """Complete each variant after every part and its OCR text reach storage."""
    return run_batch("pdf_ocr_finalize_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=lambda f: complete_pdf(params, f),
                     task_name="run_ocr_pdf_and_store")


def source_digest(parts: list[dict], count: int, needs: list[int]) -> str:
    """Identify the stored source ranges and selected pages without transporting them."""
    import hashlib
    encoded = json.dumps([PDF_SEGMENTATION_VERSION, count, needs, parts],
                         sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def bounded_result(value):
    """Fail with a compact diagnostic before an oversized activity result reaches Temporal."""
    from temporalio.converter import DataConverter
    from temporalio.exceptions import ApplicationError
    from tasks.payload_guard import MAX_PAYLOAD_BYTES, PAYLOAD_TOO_LARGE, payload_size
    converter = activity.payload_converter() if activity.in_activity() else DataConverter.default.payload_converter
    sizes = [payload_size(payload) for payload in converter.to_payloads([value])]
    if max(sizes, default=0) > MAX_PAYLOAD_BYTES:
        raise ApplicationError("PDF activity result exceeds the payload limit",
                               type=PAYLOAD_TOO_LARGE, non_retryable=True)
    return value


@activity.defn
@with_heartbeat
def pdf_prepare_compact_batch(params: StageBatchParams) -> BatchResult:
    """Return source identities after source manifests and native text reach storage."""
    return bounded_result(run_batch(
        "pdf_prepare_compact_batch", params.files, key=lambda file: file.item_hash,
        size=lambda file: file.file_size_bytes,
        step=lambda file: prepare_pdf(params, file, compact=True), task_name="pdf_prepare"))


def cursor_source(client, params):
    """Verify that a cursor still describes the stored source and page selection."""
    from temporalio.exceptions import ApplicationError
    from tasks.ocr_targets import language_settings, engine_passes
    source = params.source
    settings = language_settings(params.collection_dataset)[params.engine]
    if (engine_passes(params.engine, settings.value) != source.languages
            or settings.version.version_us != source.settings_version_us
            or settings.version.is_precise != source.settings_version_precise):
        raise ApplicationError("PDF language settings changed during cursor processing",
                               type="PdfSettingsChanged", non_retryable=True)
    parts = source_parts(client, params.collection_dataset, source.item_hash, source.source_kind)
    rows = client.query(
        "SELECT page_count, ocr_pages FROM ocr_page_needs FINAL "
        "WHERE collection_dataset = {cd:String} AND hash = {h:String} "
        "AND source_kind = {kind:String} AND rule_version = {r:UInt16}",
        parameters={"cd": params.collection_dataset, "h": source.item_hash,
                    "kind": source.source_kind, "r": OCR_PAGE_RULE_VERSION}).result_rows
    if (source.segmentation != PDF_SEGMENTATION_VERSION or not rows
            or len(parts) != source.part_count
            or source_digest(parts, int(rows[0][0]), list(rows[0][1])) != source.source_digest):
        raise ApplicationError("PDF source ranges changed during cursor processing",
                               type="PdfSourceChanged", non_retryable=True)
    return parts, list(rows[0][1])


def cursor_stage(params, files):
    """Use the frozen engine language passes for part processing and finalization."""
    from tasks.P3_parse_files.pdf_cursor import FrozenPdfStageParams
    return FrozenPdfStageParams(params.collectionname, params.collection_dataset,
                                params.plan_hash, files, params.op_id, params.engine,
                                list(params.source.languages))


from tasks.P3_parse_files.pdf_cursor import PdfPartCursorParams, PdfPartProgress


@activity.defn
@with_heartbeat
def run_ocr_pdf_part_cursor(params: PdfPartCursorParams) -> PdfPartProgress:
    """Load and process at most one hundred stored source ranges."""
    from database.clickhouse import get_collection_client
    from tasks.P3_parse_files.pdf_cursor import PDF_PART_WINDOW
    source = params.source
    with get_collection_client(params.collectionname) as client:
        parts, needs = cursor_source(client, params)
    chosen = [part for part in parts if part["part_index"] > params.after][:PDF_PART_WINDOW]
    files = [BatchFile(source.item_hash, source.file_path, part["size_bytes"],
                       source_kind=source.source_kind, part_index=part["part_index"],
                       first_page=part["first_page"], last_page=part["last_page"],
                       part_key=part["s3_path"],
                       ocr_pages=[page - part["first_page"] + 1 for page in needs
                                  if part["first_page"] <= page <= part["last_page"]])
             for part in chosen]
    stage = cursor_stage(params, files)
    result = run_batch("run_ocr_pdf_parts_batch", files,
                       key=lambda file: f"{file.item_hash}:{file.first_page}-{file.last_page}",
                       size=lambda file: file.file_size_bytes,
                       step=lambda file: build_part(stage, file), task_name="run_ocr_pdf_and_store")
    failed = next((row for row in result.results if row.status == "failed"), None)
    if failed:
        failed = dataclasses.replace(failed, item_hash=source.item_hash)
    after = chosen[-1]["part_index"] if chosen else params.after
    return bounded_result(PdfPartProgress(after, len(chosen), after >= source.part_count, failed))


@activity.defn
@with_heartbeat
def pdf_ocr_finalize_cursor(params: PdfPartCursorParams) -> FileResult:
    """Verify source identity and complete the variant after all stored parts exist."""
    from database.clickhouse import get_collection_client
    with get_collection_client(params.collectionname) as client:
        cursor_source(client, params)
    source = params.source
    file = BatchFile(source.item_hash, source.file_path, source.file_size_bytes,
                     source_kind=source.source_kind, page_count=source.page_count)
    stage = cursor_stage(params, [file])
    return bounded_result(run_batch(
        "pdf_ocr_finalize_batch", [file], key=lambda item: item.item_hash,
        size=lambda item: item.file_size_bytes, step=lambda item: complete_pdf(stage, item),
        task_name="run_ocr_pdf_and_store").results[0])
