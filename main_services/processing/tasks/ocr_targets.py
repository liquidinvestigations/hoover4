"""Select OCR work and verify its completion under current dataset settings.

Current targets include image preview, image OCR, image PDF, PDF preparation,
PDF variant completion, and indexing. Preparation includes Office conversion.
PDF completion requires durable text processing, including successful empty text.
Index receipts cover current image OCR, PDF OCR, and original native PDF text.
Recorded skips, current errors, prerequisite failures, and source removal can settle targets.

Legacy activity arguments retain the earlier result-existence completion contract.
Versioned arguments select the current completion contract.
Both use stored detector rows and the group workflow's route rules.

Engine error versions are compared with their language setting versions.
Current writers use microseconds. Earlier whole-second settings include errors from the same second.
An absent setting uses the epoch, so any recorded error is current.
"""

import json
import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from tasks.text_sources import (
    ENGINE_EASYOCR,
    ENGINE_TESSERACT,
    OCR_ENGINES,
    OCR_PREFIX,
    easyocr_language_groups,
    ocr_extracted_by,
)

log = logging.getLogger(__name__)

STAGE_PREVIEW = "preview"
STAGE_IMAGE_PDF = "image_pdf"
STAGE_PDF_PREPARE = "pdf_prepare"
STAGE_IMAGE = "image"
STAGE_PDF = "pdf"
STAGE_INDEX = "index"
#: The error name of a failed text-page write, which settles an index target.
INDEX_ERROR_TASK = "P6_IndexTextPages"
#: Hashes in one query. The same bound as the error retry selection, which the server's
#: parameter size limit sets.
HASH_CHUNK = 500
MICROS = 1_000_000


@dataclass(frozen=True)
class SettingVersion:
    """The version of one language setting.

    `version_us` is 0 when the dataset has no setting row. `is_precise` is false for a
    version copied from the earlier whole-second column.
    """

    version_us: int = 0
    is_precise: bool = True


@dataclass(frozen=True)
class LanguageSetting:
    value: str
    version: SettingVersion


@dataclass(frozen=True)
class Target:
    file_hash: str
    stage: str
    engine: str = ""
    languages: str = ""


def error_task(target: Target) -> str:
    """The `processing_errors.task_name` that settles the target."""
    from tasks.P3_parse_files.workflows import ocr_error_name, ocr_pdf_error_name

    if target.stage == STAGE_IMAGE:
        return ocr_error_name(target.engine)
    if target.stage == STAGE_PDF:
        return ocr_pdf_error_name(target.engine)
    if target.stage == STAGE_PDF_PREPARE:
        return "pdf_process"
    if target.stage == STAGE_IMAGE_PDF:
        return f"make_image_pdf[{target.engine}]"
    if target.stage == STAGE_PREVIEW:
        return "make_image_preview"
    return INDEX_ERROR_TASK


def chunked(values: Iterable[str], size: int = HASH_CHUNK) -> Iterable[List[str]]:
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


# ---- settings --------------------------------------------------------------------------


def language_settings(collection_dataset: str) -> Dict[str, LanguageSetting]:
    """Each engine's effective languages and the version of the row that set them.

    The value and the version come from one row, the latest by `setting_version_us`. A
    deleted or absent row gives the stack-wide default, with the version of the deletion
    or the epoch.
    """
    from tasks.dataset_config import DEFAULTS, latest_setting_rows, ocr_language_key

    keys = {engine: ocr_language_key(engine) for engine in OCR_ENGINES}
    rows = latest_setting_rows(collection_dataset, list(keys.values()))
    settings = {}
    for engine, key in keys.items():
        row = rows.get(key)
        if row is None:
            settings[engine] = LanguageSetting(DEFAULTS[key], SettingVersion())
            continue
        value = DEFAULTS[key] if row.is_deleted else row.value
        settings[engine] = LanguageSetting(
            value, SettingVersion(row.version_us, row.is_precise))
    return settings


def engine_passes(engine: str, languages: str) -> List[str]:
    """The language passes of one engine for a setting value, as the OCR stages run them."""
    if engine == ENGINE_TESSERACT:
        return [languages] if languages else []
    if engine == ENGINE_EASYOCR:
        return easyocr_language_groups(languages)
    raise ValueError(f"unknown OCR engine {engine!r}")


@dataclass(frozen=True)
class OcrPairs:
    """The `(engine, languages, version)` passes of each stage under one settings snapshot."""

    image: Tuple[Tuple[str, str, SettingVersion], ...]
    pdf: Tuple[Tuple[str, str, SettingVersion], ...]


def current_pairs(settings: Dict[str, LanguageSetting]) -> OcrPairs:
    """The image and searchable-PDF passes that the configuration asks for."""
    from tasks.ocr_client import engine_configured
    from tasks.ocr_pdf_client import engines_for_provider, service_configured

    image = []
    for engine in OCR_ENGINES:
        if not engine_configured(engine):
            continue
        setting = settings[engine]
        image += [(engine, languages, setting.version)
                  for languages in engine_passes(engine, setting.value)]
    pdf = []
    if service_configured():
        for engine in engines_for_provider():
            setting = settings[engine]
            pdf += [(engine, languages, setting.version)
                    for languages in engine_passes(engine, setting.value)]
    return OcrPairs(tuple(image), tuple(pdf))


# ---- routes ------------------------------------------------------------------------------


@dataclass(frozen=True)
class StoredRoute:
    routes: Tuple[str, ...]
    mime_types: Tuple[str, ...]


def stored_routes(client, collection_dataset: str, hashes: Sequence[str]) -> Dict[str, StoredRoute]:
    """The routes of each file, rebuilt from its stored local detector rows.

    The same functions as in the group workflow decide the routes, so a file routed to OCR
    here is a file that ingestion routed to OCR. A file with no detector row has no route.
    """
    from tasks.P3_parse_files.parse_mime import LOCAL_DETECTORS
    from tasks.P3_parse_files.workflows import combine_detector_results, route_stages

    detectors: Dict[str, Dict[str, dict]] = {}
    for chunk in chunked(hashes):
        rows = client.query(
            "SELECT hash, extracted_by, mime_type, mime_encoding, file_type, extensions "
            "FROM file_types FINAL WHERE collection_dataset = {cd:String} "
            "AND hash IN {h:Array(String)} AND extracted_by IN {d:Array(String)}",
            parameters={"cd": collection_dataset, "h": chunk, "d": list(LOCAL_DETECTORS)},
        ).result_rows
        for file_hash, name, mimes, encodings, coarse, extensions in rows:
            detectors.setdefault(file_hash, {})[name] = {
                "mime_types": list(mimes), "mime_encodings": list(encodings),
                "coarse_types": list(coarse), "extensions": list(extensions),
            }
    from tasks.P3_parse_files.pdf_parts import live_hashes
    live = live_hashes(client, collection_dataset, list(hashes))
    names = {}
    for chunk in chunked(live):
        for file_hash, filenames, size in client.query(
            "SELECT hash, groupUniqArray(splitByChar('/', path)[-1]), max(file_size_bytes) "
            "FROM vfs_files FINAL WHERE collection_dataset = {cd:String} "
            "AND hash IN {h:Array(String)} AND is_deleted = 0 GROUP BY hash",
            parameters={"cd": collection_dataset, "h": chunk},
        ).result_rows:
            names[file_hash] = (list(filenames), int(size))
    routes = {}
    for file_hash, per in detectors.items():
        if file_hash not in live:
            continue
        combined = combine_detector_results([per.get(name) for name in LOCAL_DETECTORS])
        routes[file_hash] = StoredRoute(tuple(route_stages(combined, True, *names.get(file_hash, ([], 0)))),
                                        tuple(combined["mime_types"]))
    return routes


# ---- stored text from retained OCR results ---------------------------------------------------


#: The error type of a retained OCR result whose payload cannot give its text.
OCR_TEXT_RECOVERY_FAILED = "OcrTextRecoveryFailed"


def _recovery_failed(message: str):
    """A non-retryable failure: the same payload gives the same answer on a retry."""
    from temporalio.exceptions import ApplicationError

    return ApplicationError(message, type=OCR_TEXT_RECOVERY_FAILED, non_retryable=True)


def _payload_text(raw_json: str, file_hash: str, engine: str, languages: str) -> str:
    try:
        payload = json.loads(raw_json)
    except (TypeError, ValueError) as exc:
        raise _recovery_failed(
            f"raw OCR payload of {file_hash} {engine}/{languages} is not JSON: {exc}") from exc
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str):
        raise _recovery_failed(
            f"raw OCR payload of {file_hash} {engine}/{languages} has no text field")
    return text


def recover_ocr_text(client, collectionname: str, collection_dataset: str,
                     hashes: Sequence[str], pairs: Iterable[Tuple[str, str]]) -> List[str]:
    """Write the OCR text that a retained raw result holds and `text_content` lacks.

    Reads the `raw_ocr_results` rows of `hashes` for the `(engine, languages)` pairs, and
    builds the pages that the image stage writes from each payload. A variant whose stored
    pages equal those pages is left as it is, with its versions. Any other variant is
    written again through the complete-source writer. A payload with empty text needs no
    page. A payload without a text field raises the non-retryable
    `OcrTextRecoveryFailed`, and the raw row stays. No OCR request is sent.

    Returns the hashes whose text was written.
    """
    from tasks.P3_parse_files.parse_common import (
        insert_text_chunks, stored_page_bodies, text_chunk_pages,
    )

    wanted = {(engine, languages) for engine, languages in pairs}
    if not hashes or not wanted:
        return []
    engines = sorted({engine for engine, _ in wanted})
    expected: Dict[Tuple[str, str], Dict[int, str]] = {}
    sources: Dict[Tuple[str, str], str] = {}
    for chunk in chunked(hashes):
        rows = client.query(
            "SELECT image_hash, engine, languages, raw_json FROM raw_ocr_results FINAL "
            "WHERE collection_dataset = {cd:String} AND image_hash IN {h:Array(String)} "
            "AND engine IN {e:Array(String)}",
            parameters={"cd": collection_dataset, "h": chunk, "e": engines},
        ).result_rows
        for file_hash, engine, languages, raw_json in rows:
            if (engine, languages) not in wanted:
                continue
            text = _payload_text(raw_json, file_hash, engine, languages)
            # The image stage writes no text for a result whose text is white space.
            if not text.strip():
                continue
            extracted_by = ocr_extracted_by(engine, languages)
            expected[file_hash, extracted_by] = dict(stored_page_bodies(text_chunk_pages(text)))
            sources[file_hash, extracted_by] = text
    if not expected:
        return []

    stored: Dict[Tuple[str, str], Dict[int, str]] = {}
    variants = sorted({extracted_by for _, extracted_by in expected})
    for chunk in chunked(sorted({file_hash for file_hash, _ in expected})):
        rows = client.query(
            "SELECT file_hash, extracted_by, page_id, argMax(text, version) FROM text_content "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {h:Array(String)} "
            "AND extracted_by IN {v:Array(String)} GROUP BY file_hash, extracted_by, page_id",
            parameters={"cd": collection_dataset, "h": chunk, "v": variants},
        ).result_rows
        for file_hash, extracted_by, page_id, text in rows:
            stored.setdefault((file_hash, extracted_by), {})[int(page_id)] = text

    written = []
    for key in sorted(expected):
        if stored.get(key, {}) == expected[key]:
            continue
        file_hash, extracted_by = key
        insert_text_chunks(collectionname, collection_dataset, file_hash, extracted_by,
                           sources[key])
        log.info("[ocr-targets] recovered OCR text of %s %s from its stored result",
                 file_hash, extracted_by)
        written.append(file_hash)
    return sorted(set(written))


# ---- the done rule ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ErrorTimes:
    """The latest error of one `(file, task)`, in the units of each comparison."""

    max_write_version: int = 0
    #: The latest second, from `write_version` where it is set, else from `timestamp`.
    max_second: int = 0
    #: The latest `timestamp` of a row without `write_version`.
    max_legacy_second: int = 0


def _error_times(client, collection_dataset: str, hashes: Sequence[str],
                 tasks: Sequence[str]) -> Dict[Tuple[str, str], _ErrorTimes]:
    times = {}
    if not tasks:
        return times
    for chunk in chunked(hashes):
        rows = client.query(
            "SELECT hash, task_name, max(write_version), "
            "max(if(write_version > 0, intDiv(write_version, 1000000), "
            "toUInt64(toUnixTimestamp(timestamp)))), "
            "maxIf(toUInt64(toUnixTimestamp(timestamp)), write_version = 0) "
            "FROM processing_errors WHERE collection_dataset = {cd:String} "
            "AND hash IN {h:Array(String)} AND task_name IN {t:Array(String)} "
            "GROUP BY hash, task_name",
            parameters={"cd": collection_dataset, "h": chunk, "t": list(tasks)},
        ).result_rows
        for file_hash, task, wv, second, legacy in rows:
            times[file_hash, task] = _ErrorTimes(int(wv), int(second), int(legacy))
    return times


def error_is_current(error: Optional[_ErrorTimes], since: SettingVersion) -> bool:
    """Whether an OCR error belongs to the language setting of version `since`."""
    if error is None:
        return False
    if since.version_us == 0:
        return error.max_write_version > 0 or error.max_second > 0
    if since.is_precise:
        return error.max_write_version > since.version_us
    return error.max_second >= since.version_us // MICROS


def index_error_is_current(error: Optional[_ErrorTimes], newest_text_version: int) -> bool:
    """Whether a text-page error is newer than the newest OCR text, in nanoseconds."""
    if error is None:
        return False
    if error.max_write_version and error.max_write_version * 1000 > newest_text_version:
        return True
    return error.max_legacy_second > newest_text_version // 1_000_000_000


@dataclass
class _IndexState:
    #: (extracted_by, page_id) -> current text version, OCR variants only.
    segments: Dict[Tuple[str, int], int]
    indexed: bool
    receipts: Dict[Tuple[str, int], int]
    error: Optional[_ErrorTimes]

    def done(self) -> bool:
        if not self.segments:
            return True
        if self.indexed and all(self.receipts.get(key) == version
                                for key, version in self.segments.items()):
            return True
        return index_error_is_current(self.error, max(self.segments.values()))


def _index_states(client, collection_dataset: str,
                  hashes: Sequence[str]) -> Dict[str, _IndexState]:
    states = {h: _IndexState({}, False, {}, None) for h in hashes}
    for chunk in chunked(hashes):
        parameters = {"cd": collection_dataset, "h": chunk, "p": OCR_PREFIX}
        for file_hash, extracted_by, page_id, version in client.query(
                "SELECT file_hash, extracted_by, page_id, max(version) FROM text_content "
                "WHERE collection_dataset = {cd:String} AND file_hash IN {h:Array(String)} "
                "AND (startsWith(extracted_by, {p:String}) OR startsWith(extracted_by, 'pdfocr_') OR extracted_by = 'pdftotext') "
                "GROUP BY file_hash, extracted_by, page_id",
                parameters=parameters).result_rows:
            states[file_hash].segments[extracted_by, int(page_id)] = int(version)
        with_text = [h for h in chunk if states[h].segments]
        if not with_text:
            continue
        parameters["h"] = with_text
        for (file_hash,) in client.query(
                "SELECT DISTINCT file_hash FROM index_state "
                "WHERE collection_dataset = {cd:String} AND file_hash IN {h:Array(String)}",
                parameters=parameters).result_rows:
            states[file_hash].indexed = True
        for file_hash, extracted_by, page_id, version in client.query(
                "SELECT file_hash, extracted_by, page_id, argMax(text_version, receipt_version) "
                "FROM ocr_indexed_text WHERE collection_dataset = {cd:String} "
                "AND file_hash IN {h:Array(String)} GROUP BY file_hash, extracted_by, page_id",
                parameters=parameters).result_rows:
            states[file_hash].receipts[extracted_by, int(page_id)] = int(version)
    errors = _error_times(client, collection_dataset,
                          [h for h, state in states.items() if state.segments],
                          [INDEX_ERROR_TASK])
    for (file_hash, _), times in errors.items():
        states[file_hash].error = times
    return states


def _current_settled(client, collection_dataset: str,
            targets: Dict[Target, SettingVersion]) -> Set[Target]:
    """Settle current targets by durable completion, skips, errors, or source removal."""
    from tasks.P3_parse_files.pdf_parts import live_hashes
    from tasks.text_sources import PDF_SEGMENTATION_VERSION, OCR_PAGE_RULE_VERSION
    hashes = sorted({target.file_hash for target in targets})
    live = live_hashes(client, collection_dataset, hashes)
    done = {target for target in targets if target.file_hash not in live}
    results, skips, prepared, defective, no_pages = set(), set(), set(), set(), set()
    for values in chunked(live):
        p = {"cd": collection_dataset, "h": values, "s": PDF_SEGMENTATION_VERSION, "r": OCR_PAGE_RULE_VERSION}
        results.update((h, STAGE_IMAGE, e, l) for h, e, l in client.query(
            "SELECT DISTINCT image_hash, engine, languages FROM raw_ocr_results "
            "WHERE collection_dataset = {cd:String} AND image_hash IN {h:Array(String)}", parameters=p).result_rows)
        results.update((h, STAGE_IMAGE_PDF if kind == "image" else STAGE_PDF, e, l)
                       for h, e, l, kind in client.query(
            "SELECT pdf_hash, engine, languages, source_kind FROM pdf_ocr_results FINAL "
            "WHERE collection_dataset = {cd:String} AND pdf_hash IN {h:Array(String)} "
            "AND is_deleted = 0 AND text_complete = 1", parameters=p).result_rows)
        skips.update(tuple(row) for row in client.query(
            "SELECT DISTINCT file_hash, stage, engine, languages FROM ocr_skips "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {h:Array(String)}", parameters=p).result_rows)
        for h, count, pages in client.query(
            "SELECT hash, page_count, ocr_pages FROM ocr_page_needs FINAL "
            "WHERE collection_dataset = {cd:String} AND hash IN {h:Array(String)} "
            "AND rule_version = {r:UInt16}", parameters=p).result_rows:
            ranges = client.query(
                "SELECT first_page, last_page FROM pdf_parts FINAL "
                "WHERE collection_dataset = {cd:String} AND hash = {hash:String} "
                "AND segmentation = {s:UInt16} ORDER BY part_index",
                parameters={**p, "hash": h}).result_rows
            expected = 1
            for first, last in ranges:
                if first != expected:
                    break
                expected = last + 1
            else:
                if ranges and expected == count + 1:
                    prepared.add(h)
                    if not pages:
                        no_pages.add(h)
        defective.update(h for h, in client.query(
            "SELECT DISTINCT pdf_hash FROM pdfs FINAL WHERE collection_dataset = {cd:String} "
            "AND pdf_hash IN {h:Array(String)} AND defect IS NOT NULL", parameters=p).result_rows)
        results.update((h, STAGE_PREVIEW, "", "") for h, in client.query(
            "SELECT DISTINCT hash FROM image_previews WHERE collection_dataset = {cd:String} "
            "AND hash IN {h:Array(String)}", parameters=p).result_rows)
    tasks = sorted({error_task(t) for t in targets} | {"pdf_process", "make_pdf_preview", "make_image_preview"} | {f"run_ocr_and_store[{engine}]" for engine in OCR_ENGINES})
    errors = _error_times(client, collection_dataset, list(live), tasks)
    index_targets = [t for t in targets if t.stage == STAGE_INDEX and t.file_hash in live]
    states = _index_states(client, collection_dataset, sorted({t.file_hash for t in index_targets})) if index_targets else {}
    for target, version in targets.items():
        h = target.file_hash
        if h not in live:
            continue
        key = (h, target.stage, target.engine, target.languages)
        prerequisite_failed = (target.stage in (STAGE_PDF, STAGE_PDF_PREPARE)
                               and (h in defective or (h, "pdf_preview", "", "") in skips
                                    or errors.get((h, "pdf_process")) or errors.get((h, "make_pdf_preview"))))
        if (key in results or key in skips or prerequisite_failed
                or (target.stage == STAGE_PDF_PREPARE and h in prepared)
                or error_is_current(errors.get((h, error_task(target))), version)
                or (target.stage == STAGE_INDEX and states[h].done())):
            done.add(target)
        if target.stage == STAGE_PDF and h in no_pages:
            existing = client.query(
                "SELECT count() FROM pdf_ocr_results FINAL WHERE collection_dataset = {cd:String} "
                "AND pdf_hash = {h:String} AND engine = {en:String} AND languages = {la:String} "
                "AND is_deleted = 0", parameters={"cd": collection_dataset, "h": h,
                                                "en": target.engine, "la": target.languages}).result_rows[0][0]
            if not existing:
                done.add(target)
        if target.stage == STAGE_IMAGE_PDF and ((h, STAGE_IMAGE, target.engine, target.languages) in skips or error_is_current(errors.get((h, f"run_ocr_and_store[{target.engine}]")), version)):
            done.add(target)
    return done


def text_pending_index(client, collection_dataset: str, hashes: Sequence[str]) -> List[str]:
    """The files among `hashes` whose OCR text is not indexed by the index rule."""
    from tasks.P3_parse_files.pdf_parts import live_hashes
    states = _index_states(client, collection_dataset,
                           sorted(live_hashes(client, collection_dataset, list(hashes))))
    return sorted(h for h, state in states.items() if not state.done())


# ---- skips ----------------------------------------------------------------------------------


def record_ocr_skips(client, collection_dataset: str, file_hash: str, stage: str,
                     engine: str, passes: Sequence[str], reason: str, op_id: str = "") -> None:
    """Store the decision of an OCR stage to skip a file, one row for each pass.

    Written through the parser insert buffer, so the rows join the insert batch of the
    file. The row settles the target, so a later OCR run sends no request for it.
    """
    import pyarrow as pa

    from database.clickhouse import insert_parser_arrow

    if not passes:
        return
    count = len(passes)
    insert_parser_arrow(client, "ocr_skips", pa.table({
        "collection_dataset": pa.array([collection_dataset] * count, type=pa.string()),
        "file_hash": pa.array([file_hash] * count, type=pa.string()),
        "stage": pa.array([stage] * count, type=pa.string()),
        "engine": pa.array([engine] * count, type=pa.string()),
        "languages": pa.array(list(passes), type=pa.string()),
        "reason": pa.array([reason] * count, type=pa.string()),
        "op_id": pa.array([op_id] * count, type=pa.string()),
    }))


def legacy_settled(client, collection_dataset: str,
            targets: Dict[Target, SettingVersion]) -> Set[Target]:
    """The targets among `targets` that are done, each under its own setting version."""
    done: Set[Target] = set()
    by_stage: Dict[str, List[Target]] = {}
    for target in targets:
        by_stage.setdefault(target.stage, []).append(target)

    ocr_targets = by_stage.get(STAGE_IMAGE, []) + by_stage.get(STAGE_PDF, [])
    ocr_hashes = sorted({t.file_hash for t in ocr_targets})
    results: Set[Tuple[str, str, str, str]] = set()
    skips: Set[Tuple[str, str, str, str]] = set()
    for chunk in chunked(ocr_hashes):
        parameters = {"cd": collection_dataset, "h": chunk}
        if by_stage.get(STAGE_IMAGE):
            results.update((h, STAGE_IMAGE, e, l) for h, e, l in client.query(
                "SELECT DISTINCT image_hash, engine, languages FROM raw_ocr_results "
                "WHERE collection_dataset = {cd:String} AND image_hash IN {h:Array(String)}",
                parameters=parameters).result_rows)
        if by_stage.get(STAGE_PDF):
            results.update((h, STAGE_PDF, e, l) for h, e, l in client.query(
                "SELECT pdf_hash, engine, languages FROM pdf_ocr_results "
                "WHERE collection_dataset = {cd:String} AND pdf_hash IN {h:Array(String)} "
                "GROUP BY pdf_hash, engine, languages "
                "HAVING argMax(is_deleted, updated_at) = 0",
                parameters=parameters).result_rows)
        skips.update(tuple(row) for row in client.query(
            "SELECT DISTINCT file_hash, stage, engine, languages FROM ocr_skips "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {h:Array(String)}",
            parameters=parameters).result_rows)
    errors = _error_times(client, collection_dataset, ocr_hashes,
                          sorted({error_task(t) for t in ocr_targets}))
    for target in ocr_targets:
        key = (target.file_hash, target.stage, target.engine, target.languages)
        if (key in results or key in skips
                or error_is_current(errors.get((target.file_hash, error_task(target))),
                                    targets[target])):
            done.add(target)

    index_targets = by_stage.get(STAGE_INDEX, [])
    if index_targets:
        states = _index_states(client, collection_dataset,
                               sorted({t.file_hash for t in index_targets}))
        done.update(t for t in index_targets if states[t.file_hash].done())
    return done



def settled(client, collection_dataset: str, targets: Dict[Target, SettingVersion],
            parts_version: bool = False) -> Set[Target]:
    """Use the completion contract of the activity arguments, including earlier workflows."""
    return (_current_settled if parts_version else legacy_settled)(client, collection_dataset, targets)
