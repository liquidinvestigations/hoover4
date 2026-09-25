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
    from tasks.P3_parse_files.table_formats import is_table_mime
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
    "extract_plaintext_chunks",
    "parse_office_xml_and_store",
    "parse_table_and_store",
    "pdf_process",
    "parse_image_metadata_and_store",
    "parse_audio_metadata_and_store",
    "video_process",
})


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
        if str(current).startswith("qpdf --show-npages failed:"):
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
    return list({str(value) for value in values if isinstance(value, str) and value})


def combine_detector_results(detector_results: List[Any]) -> Dict[str, List[str]]:
    """The union of the types that the detectors of one file found."""
    all_coarse: List[str] = []
    all_mime: List[str] = []
    all_enc: List[str] = []
    for result in detector_results:
        if isinstance(result, Exception):
            continue
        all_coarse += _as_list(result, "coarse_types")
        all_mime += _as_list(result, "mime_types")
        all_enc += _as_list(result, "mime_encodings")
    return {
        "coarse_types": sorted(set(all_coarse)),
        "mime_types": sorted(set(all_mime)),
        "mime_encodings": sorted(set(all_enc)),
    }


def detector_results_for_file(detect_result: FileResult, tika_result: FileResult) -> List[Any]:
    """One result for each detector of one file: the local detectors, then Tika.

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
    results.append(file_error(tika_result) if tika_result.status == "failed"
                   else tika_result.value)
    return results


def route_stages(combined: Dict[str, List[str]]) -> List[str]:
    """The routes of one file, in the order of ROUTE_ERROR_NAMES.

    A file takes every route whose condition one of its detectors meets, even when the
    other detectors disagree.
    """
    coarse_types = combined["coarse_types"]
    mime_types = combined["mime_types"]
    routes: List[str] = []
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
    if any(is_table_mime(m) for m in mime_types):
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
