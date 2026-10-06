"""The routing and error-name rules of the parse stage, as pure functions.

The group workflow `ProcessItemsBatched` (`tasks/P2_execute_plan/workflows.py`) calls
them for each file: it combines the detector results, picks the routes, and names each
Error row that it records.
"""

from typing import Dict, Any, List

from temporalio import workflow


with workflow.unsafe.imports_passed_through():
    from tasks.P3_parse_files.batch_runner import FileResult, file_error
    from tasks.P3_parse_files.parse_tika import TIKA_PARSE_FAILED
    from tasks.P3_parse_files.temp_dirs import has_application_error_type, is_temp_copy_missing
    from tasks.P3_parse_files.parse_mime import LOCAL_DETECTORS
    from tasks.P3_parse_files.table_formats import is_table_mime, BINARY_TABLE_MIMES, DELIMITED_TABLE_MIMES, DELIMITED_EXTENSIONS
    from tasks.P3_parse_files.content_types import AUTHORITATIVE_SNIFF_MIMES, AUTHORITATIVE_ALIASES
    from tasks.P0_scan_disk.mime_type_mapper import is_zip_based_document_mime, should_expand_as_archive


def _detector_results_for_error_capture(
    detector_names: List[str],
    detector_results: List[Any],
    parser_task_ids: List[str],
    parser_results: List[Any],
) -> List[Any]:
    """Return the detector failures to record, one result for each detector.

    Two rules remove a failure that repeats another one. After a qpdf page-count
    failure, the Tika failure is dropped. When the temporary copy of the file is
    missing, only the first detector that reports it keeps its failure.
    """
    qpdf_page_count_failed = any(
        task_id == "pdf_process"
        and isinstance(result, Exception)
        and _is_qpdf_page_count_failure(result)
        for task_id, result in zip(parser_task_ids, parser_results)
    )
    results = list(detector_results)
    if qpdf_page_count_failed:
        # qpdf is authoritative for an unreadable PDF. Tika reads the same bytes and its
        # retry error would otherwise write a second Error row for the document.
        results = [None if name == "tika" else result for name, result in zip(detector_names, results)]
    # Every detector reads the same missing path, so the cause is recorded once.
    missing_seen = False
    for index, result in enumerate(results):
        if isinstance(result, BaseException) and is_temp_copy_missing(result):
            if missing_seen:
                results[index] = None
            missing_seen = True
    return results


#: The parse tasks that extract the content of a file without Tika.
_CONTENT_EXTRACTORS_BESIDE_TIKA = frozenset({
    "email_scan",
    "archive_scan",
    "extract_plaintext_chunks",
    "parse_office_xml_and_store",
    "parse_table_and_store",
    "pdf_process",
    "parse_image_metadata_and_store",
    "parse_audio_metadata_and_store",
    "video_process",
})


def parser_results_for_error_capture(names: List[str], results: List[Any]) -> List[Any]:
    """Remove a Tika document failure when another content reader succeeded."""
    covered = any(
        (name in _CONTENT_EXTRACTORS_BESIDE_TIKA or name.startswith("run_ocr_and_store["))
        and not isinstance(result, BaseException)
        for name, result in zip(names, results)
    )
    qpdf_failed = any(name == "pdf_process" and isinstance(result, BaseException)
                      and _is_qpdf_page_count_failure(result)
                      for name, result in zip(names, results))
    failures = ("TikaParseFailed", "TikaServiceFailed", "TikaOutputTooLarge")
    return [None if (name == "tika_text_batch" and (covered or qpdf_failed)
                     and isinstance(result, BaseException)
                     and any(has_application_error_type(result, t) for t in failures))
            else result for name, result in zip(names, results)]


def _detector_error_task_ids(
    detector_names: List[str],
    detector_results: List[Any],
    parser_task_ids: List[str],
    parser_results: List[Any],
) -> List[str]:
    """The `processing_errors` task name for each detector result.

    A Tika parse failure (`TikaParseFailed`) is a parse failure of the file. When
    another parse task of the file succeeded, Tika was one extractor of several, and
    the failure is recorded as `parse_error_tika`. Otherwise Tika's failure is the
    only reading of the file, and it keeps the name `detector_error_tika`.
    """
    other_extractor_ok = any(
        (task_id in _CONTENT_EXTRACTORS_BESIDE_TIKA or task_id.startswith("run_ocr_and_store["))
        and not isinstance(result, BaseException)
        for task_id, result in zip(parser_task_ids, parser_results)
    )
    names: List[str] = []
    for name, result in zip(detector_names, detector_results):
        if (name == "tika" and other_extractor_ok and isinstance(result, BaseException)
                and has_application_error_type(result, TIKA_PARSE_FAILED)):
            names.append("parse_error_tika")
        else:
            names.append(f"detector_error_{name}")
    return names


def _is_qpdf_page_count_failure(error: BaseException) -> bool:
    """Whether an exception chain contains the qpdf page-count failure."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        message = str(getattr(current, "message", "") or current)
        if message.startswith("qpdf --show-npages failed:"):
            return True
        seen.add(id(current))
        temporal_cause = getattr(current, "cause", None)
        current = temporal_cause if isinstance(temporal_cause, BaseException) else current.__cause__
    return False


#: The parser error name of each route, in the order that the error call passes them.
#: The OCR stages of an image follow `parse_image_metadata_and_store`, and the OCR-PDF
#: stages of a PDF follow every route of the file.
ROUTE_ERROR_NAMES: Dict[str, str] = {
    "archive": "archive_scan",
    "email": "email_scan",
    "text": "extract_plaintext_chunks",
    "office_xml": "parse_office_xml_and_store",
    "table": "parse_table_and_store",
    "pdf": "pdf_process",
    "image": "parse_image_metadata_and_store",
    "audio": "parse_audio_metadata_and_store",
    "video": "video_process",
}


def ocr_error_name(engine: str) -> str:
    """The parser error name of the image OCR stage of one engine."""
    return f"run_ocr_and_store[{engine}]"


def ocr_pdf_error_name(engine: str) -> str:
    """The parser error name of the searchable-PDF stage of one engine."""
    return f"run_ocr_pdf_and_store[{engine}]"


def _as_list(result: Any, key: str) -> List[str]:
    values = result.get(key) if isinstance(result, dict) else []
    if not values:
        return []
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def combine_detector_results(detector_results: List[Any]) -> Dict[str, List[str]]:
    """Keep authoritative sniffs separate from the other detector types."""
    detections = dict(zip(LOCAL_DETECTORS, detector_results))
    sniff = _as_list(detections.get("content_sniff"), "mime_types")
    authoritative = sorted(set(sniff) & AUTHORITATIVE_SNIFF_MIMES)
    file_types = _as_list(detections.get("file"), "mime_types")
    content_text = bool(file_types and file_types[0].startswith("text/"))
    all_mime = []
    all_enc = []
    coarse = []
    permitted_delimited = set()
    for name, result in detections.items():
        mimes = _as_list(result, "mime_types")
        original_mimes = list(mimes)
        if name != "content_sniff":
            mimes = [m for m in mimes if m not in AUTHORITATIVE_ALIASES
                     and not (name == "extension" and content_text and m in BINARY_TABLE_MIMES)]
        all_mime += mimes
        all_enc += _as_list(result, "mime_encodings")
        if name in ("content_sniff", "file", "extension"):
            permitted_delimited.update(set(mimes) & DELIMITED_TABLE_MIMES)
        # Preserve coarse results when every MIME value remains eligible.
        if mimes == original_mimes:
            coarse += _as_list(result, "coarse_types")
    from tasks.P0_scan_disk.mime_type_mapper import coarse_file_type
    coarse += [coarse_file_type(m) for m in all_mime]
    name_extensions = _as_list(detections.get("extension"), "extensions")
    if set(name_extensions) & DELIMITED_EXTENSIONS:
        permitted_delimited.add("extension")
    return {"coarse_types": sorted(set(coarse)), "mime_types": sorted(set(all_mime)),
            "mime_encodings": sorted(set(all_enc)), "authoritative_types": authoritative,
            "permitted_delimited": sorted(permitted_delimited)}


def detector_results_for_file(detect_result: FileResult) -> List[Any]:
    """Return one result for each local detector of one file.

    A detector that raised inside `detect_mime_all` comes back under `errors`. A failed
    detect result, for example a missing temporary copy, makes every local detector
    unavailable with that failure.
    """
    if detect_result.status == "failed":
        results: List[Any] = [file_error(detect_result)] * len(LOCAL_DETECTORS)
    else:
        value = detect_result.value if isinstance(detect_result.value, dict) else {}
        per_detector = value.get("detectors") or {}
        per_error = value.get("errors") or {}
        results = [
            per_detector.get(name, RuntimeError(per_error.get(name, "detector produced no result")))
            for name in LOCAL_DETECTORS
        ]
    return results


def route_stages(combined: Dict[str, List[str]]) -> List[str]:
    """The routes of one file, in the order of ROUTE_ERROR_NAMES.

    Mail containers take only the archive route.
    Other files take each applicable route from their detected types.
    """
    authoritative = combined.get("authoritative_types") or []
    if authoritative:
        return ["text"] if authoritative[0] == "text/vcard" else ["table"]
    coarse_types = combined["coarse_types"]
    mime_types = combined["mime_types"]
    routes: List[str] = []
    mail_containers = {"application/x-hoover-pst", "application/vnd.ms-outlook",
                       "application/mbox", "application/ms-tnef",
                       "application/vnd.ms-outlook-pst", "application/vnd.ms-tnef"}
    is_mail_container = bool(set(mime_types) & mail_containers)
    if is_mail_container:
        return ["archive"]
    if should_expand_as_archive(coarse_types, mime_types):
        routes.append("archive")
    if "email" in coarse_types:
        routes.append("email")
    if "text" in coarse_types:
        routes.append("text")
    # A zip-based office document gets a second extractor beside Tika, always. The
    # condition is the MIME set: the legacy binary formats of the same coarse types are
    # not zips, and this extractor has nothing to read in them.
    if any(is_zip_based_document_mime(m) for m in mime_types):
        routes.append("office_xml")
    # A tabular document also gets a structural reading into cells. The text readers
    # still index the same values as text.
    if any(is_table_mime(m) for m in mime_types) and (
            set(mime_types) & BINARY_TABLE_MIMES or combined.get("permitted_delimited", ["legacy"])):
        routes.append("table")
    if "pdf" in coarse_types:
        routes.append("pdf")
    # An image also runs one OCR stage for each engine of OCR_ENGINES. Each OCR call
    # reads its languages from the dataset settings when it runs.
    if "image" in coarse_types:
        routes.append("image")
    if "audio" in coarse_types:
        routes.append("audio")
    if "video" in coarse_types:
        routes.append("video")
    return routes
