"""Parsing workflows that route files by type to specialized handlers."""

from temporalio import workflow, activity
from temporalio.common import RetryPolicy
from datetime import timedelta
import traceback
from typing import Dict, Any, List
from dataclasses import dataclass
import asyncio
import logging
import json
import math



log = logging.getLogger(__name__)


with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P3_parse_files.parse_pdf import PdfProcessingWorkflowParams
    from tasks.P3_parse_files.parse_email import EmailExtractionWorkflowParams
    from tasks.P3_parse_files.parse_common import record_errors_from_results, source_execution_id
    from tasks.P3_parse_files.parse_archives import ArchiveExtractionAndScan
    from tasks.P3_parse_files.parse_email import parse_email_extract_text_headers, EmailExtractionAndScan
    from tasks.P3_parse_files.parse_text import extract_plaintext_chunks
    from tasks.P3_parse_files.parse_tika import run_tika_and_store, RunTikaParams, TIKA_PARSE_FAILED
    from tasks.P3_parse_files.temp_dirs import has_application_error_type, is_temp_copy_missing
    from tasks.P3_parse_files.parse_mime import (
        detect_mime_all, DetectMimeParams, LOCAL_DETECTORS,
    )
    from tasks.P3_parse_files.parse_pdf import PdfProcessingAndScan
    from tasks.P3_parse_files.parse_image import parse_image_metadata_and_store, ParseImageParams
    from tasks.P3_parse_files.parse_audio import parse_audio_metadata_and_store, ParseAudioParams
    from tasks.P3_parse_files.parse_video import VideoProcessingAndScan
    from tasks.P3_parse_files.parse_ocr import run_ocr_and_store, RunOcrParams
    from tasks.P3_parse_files.parse_office_xml import parse_office_xml_and_store, ParseOfficeXmlParams
    from tasks.P3_parse_files.parse_table import parse_table_and_store, ParseTableParams
    from tasks.P3_parse_files.table_formats import is_table_mime
    from tasks.text_sources import OCR_ENGINES
    from tasks.P0_scan_disk.mime_type_mapper import is_zip_based_document_mime, should_expand_as_archive
    from tasks.visibility import dataset_search_attributes


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


@dataclass
class ParseSingleFileParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    item_hash: str
    file_path: str
    file_size_bytes: int | None = None
    op_id: str = ""


@workflow.defn
class ParseSingleFile:
    """Workflow that parses a single downloaded file based on coarse type."""
    @workflow.run
    async def run(self, params: ParseSingleFileParams) -> str:
        # Compute timeout dynamically: 15min + transfer time at 10 kbps
        try:
            size_bytes = int(getattr(params, "file_size_bytes", 0) or 0)
        except Exception:
            size_bytes = 0
        BPS_10_K = 10_000 // 8  # 1,250 bytes/sec
        proc_secs = 900 + math.ceil(size_bytes / BPS_10_K)

        # One activity for the four local detectors, one for Tika. The local four are
        # tens of milliseconds each: scheduling a Temporal activity per detector cost
        # several times what the detection did, and two of them ran `file` separately on
        # the same bytes. Tika stays its own activity on its own queue because it holds
        # an extractous helper there.
        local_fut = workflow.execute_activity(
            detect_mime_all,
            DetectMimeParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                file_hash=params.item_hash,
                file_path=params.file_path,
                timeout_seconds=proc_secs,
                op_id=params.op_id,
            ),
            start_to_close_timeout=timedelta(seconds=proc_secs),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        tika_fut = workflow.execute_activity(
            run_tika_and_store,
            RunTikaParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                file_hash=params.item_hash,
                file_path=params.file_path,
                timeout_seconds=1000+proc_secs,
                op_id=params.op_id,
            ),
            start_to_close_timeout=timedelta(seconds=1000+proc_secs),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue="processing-tika-queue",
        )

        detectors_started_at = workflow.now()
        local_res, tika_res = await asyncio.gather(
            local_fut, tika_fut, return_exceptions=True,
        )

        def _as_list(d: dict | Any, key: str) -> List[str]:
            v = d.get(key) if isinstance(d, dict) else []
            if not v:
                return []
            return list({str(x) for x in v if isinstance(x, str) and x})

        def _combine_detector_results(detector_results: List[Any]) -> Dict[str, List[str]]:
            all_coarse: List[str] = []
            all_mime: List[str] = []
            all_enc: List[str] = []
            for res in detector_results:
                if isinstance(res, Exception):
                    continue
                all_coarse += _as_list(res, "coarse_types")
                all_mime += _as_list(res, "mime_types")
                all_enc += _as_list(res, "mime_encodings")
            return {
                "coarse_types": sorted(set(all_coarse)),
                "mime_types": sorted(set(all_mime)),
                "mime_encodings": sorted(set(all_enc)),
            }

        # Unpack the combined activity back into one result per detector, so error
        # attribution and the canonical resolution below see the same shape they always
        # have. A detector that raised inside the activity comes back under `errors`;
        # the activity itself failing means all four are unavailable.
        detector_names = list(LOCAL_DETECTORS) + ["tika"]
        if isinstance(local_res, Exception):
            detector_results: List[Any] = [local_res] * len(LOCAL_DETECTORS)
        else:
            per_detector = local_res.get("detectors") or {}
            per_error = local_res.get("errors") or {}
            detector_results = [
                per_detector.get(name, RuntimeError(per_error.get(name, "detector produced no result")))
                for name in LOCAL_DETECTORS
            ]
        detector_results.append(tika_res)
        combined = _combine_detector_results(detector_results)
        coarse_types: List[str] = combined["coarse_types"]
        mime_types: List[str] = combined["mime_types"]
        mime_encodings: List[str] = combined["mime_encodings"]

        # Always log baseline args
        futs: List = []
        task_ids: List[str] = []
        starts: List = []


        # Route by type
        if should_expand_as_archive(coarse_types, mime_types):
            child_id = f"archive-scan-{params.collection_dataset}-{params.item_hash}"
            futs.append(
                workflow.execute_child_workflow(
                    ArchiveExtractionAndScan.run,
                    {
                        "collectionname": params.collectionname,
                        "collection_dataset": params.collection_dataset,
                        "archive_hash": params.item_hash,
                        "archive_types": mime_types,
                        "archive_path": params.file_path,
                        "timeout_seconds": proc_secs,
                    },
                    task_queue="processing-common-queue",
                    id=child_id,
                    search_attributes=dataset_search_attributes(params.collection_dataset)
                )
            )
            task_ids.append('archive_scan')
            starts.append(workflow.now())

        if "email" in coarse_types:
            child_id = f"email-scan-{params.collection_dataset}-{params.item_hash}"
            futs.append(
                workflow.execute_child_workflow(
                    EmailExtractionAndScan.run,
                    EmailExtractionWorkflowParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        email_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                    ),
                    task_queue="processing-common-queue",
                    id=child_id,
                    search_attributes=dataset_search_attributes(params.collection_dataset)
                )
            )
            task_ids.append('email_scan')
            starts.append(workflow.now())

        if "text" in coarse_types:
            from tasks.P3_parse_files.parse_text import ExtractPlaintextParams
            futs.append(
                workflow.execute_activity(
                    extract_plaintext_chunks,
                    ExtractPlaintextParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        file_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                        op_id=params.op_id,
                    ),
                    start_to_close_timeout=timedelta(seconds=proc_secs),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                )
            )
            task_ids.append("extract_plaintext_chunks")
            starts.append(workflow.now())

        # Zip-based office documents get a SECOND extractor, always, not only when
        # Extractous fails -- the same arrangement a PDF has had all along with
        # `extractous` + `pdftotext`. Until this existed, one Tika bug (easychair.docx,
        # TIKA-198) left a document with no searchable text at all.
        #
        # The condition is the MIME set, not a coarse type: `doc`/`xls`/`ppt` also cover
        # the legacy binary formats, which are not zips and have nothing here to read.
        if any(is_zip_based_document_mime(m) for m in mime_types):
            futs.append(
                workflow.execute_activity(
                    parse_office_xml_and_store,
                    ParseOfficeXmlParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        file_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                        op_id=params.op_id,
                    ),
                    start_to_close_timeout=timedelta(seconds=proc_secs),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                )
            )
            task_ids.append("parse_office_xml_and_store")
            starts.append(workflow.now())

        # A tabular document gets a THIRD reading, structural rather than textual: the
        # same .xlsx is flattened to text by the office extractor and by Tika, and read
        # into cells here. Nothing is replaced -- a search for a value inside a cell still
        # goes through the text path, and this is what makes the columns browsable.
        #
        # It runs on the common queue with the other parse activities and relies on the
        # caps in `table_formats` rather than on a queue of its own.
        if any(is_table_mime(m) for m in mime_types):
            futs.append(
                workflow.execute_activity(
                    parse_table_and_store,
                    ParseTableParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        file_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                        mime_types=mime_types,
                        mime_encodings=mime_encodings,
                        op_id=params.op_id,
                    ),
                    start_to_close_timeout=timedelta(seconds=proc_secs),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                )
            )
            task_ids.append("parse_table_and_store")
            starts.append(workflow.now())

        if "pdf" in coarse_types:
            child_id = f"pdf-process-{params.collection_dataset}-{params.item_hash}"
            futs.append(
                workflow.execute_child_workflow(
                    PdfProcessingAndScan.run,
                    PdfProcessingWorkflowParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        pdf_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                        op_id=params.op_id,
                    ),
                    task_queue="processing-common-queue",
                    id=child_id,
                    search_attributes=dataset_search_attributes(params.collection_dataset),
                )
            )
            task_ids.append("pdf_process")
            starts.append(workflow.now())

        if "image" in coarse_types:
            futs.append(
                workflow.execute_activity(
                    parse_image_metadata_and_store,
                    ParseImageParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        file_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                        op_id=params.op_id,
                    ),
                    start_to_close_timeout=timedelta(seconds=proc_secs),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                )
            )
            task_ids.append("parse_image_metadata_and_store")
            starts.append(workflow.now())

            # One OCR activity per engine, on the engine-neutral OCR queue. Which
            # languages each engine runs -- and whether it runs at all -- is decided
            # inside the activity from `dataset_settings`, not here: a workflow argument
            # would freeze the value at schedule time, and the apply job
            # exists to reach activities that are already in flight.
            #
            # An engine with no endpoint configured records a skip and succeeds, so this
            # fan-out costs nothing on a box with no GPU tier.
            for engine in OCR_ENGINES:
                futs.append(
                    workflow.execute_activity(
                        run_ocr_and_store,
                        RunOcrParams(
                            collectionname=params.collectionname,
                            collection_dataset=params.collection_dataset,
                            file_hash=params.item_hash,
                            file_path=params.file_path,
                            engine=engine,
                            timeout_seconds=proc_secs,
                            op_id=params.op_id,
                        ),
                        start_to_close_timeout=timedelta(seconds=proc_secs),
                        heartbeat_timeout=HEARTBEAT_TIMEOUT,
                        retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                        task_queue="processing-ocr-queue",
                    )
                )
                task_ids.append(f"run_ocr_and_store[{engine}]")
                starts.append(workflow.now())

        if "audio" in coarse_types:
            futs.append(
                workflow.execute_activity(
                    parse_audio_metadata_and_store,
                    ParseAudioParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        file_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                        op_id=params.op_id,
                    ),
                    start_to_close_timeout=timedelta(seconds=proc_secs),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                )
            )
            task_ids.append("parse_audio_metadata_and_store")
            starts.append(workflow.now())

        if "video" in coarse_types:
            child_id = f"video-process-{params.collection_dataset}-{params.item_hash}"
            futs.append(
                workflow.execute_child_workflow(
                    VideoProcessingAndScan.run,
                    {
                        "collectionname": params.collectionname,
                        "collection_dataset": params.collection_dataset,
                        "video_hash": params.item_hash,
                        "file_path": params.file_path,
                        "timeout_seconds": proc_secs,
                    },
                    task_queue="processing-common-queue",
                    id=child_id,
                    search_attributes=dataset_search_attributes(params.collection_dataset),
                )
            )
            task_ids.append("video_process")
            starts.append(workflow.now())

        # Already ran Tika above; no need to run again here

        # Wait for all and capture exceptions, then record via common helper
        results = await asyncio.gather(*futs, return_exceptions=True)
        detector_results_for_error_capture = _detector_results_for_error_capture(
            detector_names, detector_results, task_ids, results,
        )
        try:
            await record_errors_from_results(
                detector_results_for_error_capture,
                source_execution_ids=[source_execution_id(workflow.info().run_id,
                    "P3.detector", ordinal) for ordinal, _ in enumerate(detector_names)],
                task_ids=_detector_error_task_ids(
                    detector_names, detector_results, task_ids, results,
                ),
                starts=[detectors_started_at] * len(detector_results),
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                item_hashes=[params.item_hash] * len(detector_results),
                op_id=params.op_id,
                default_task_name="detector_error_unknown",
            )
        except Exception:
            # Best-effort: a detector that failed must not also fail the parse. But never
            # silently -- this call site lost every detector error for months by swallowing
            # a param-shape TypeError here.
            log.exception(
                "[P3] failed to record detector errors for %s/%s",
                params.collection_dataset, params.item_hash,
            )
        await record_errors_from_results(
            results,
            source_execution_ids=[source_execution_id(workflow.info().run_id,
                "P3.parser", ordinal) for ordinal, _ in enumerate(futs)],
            task_ids=task_ids,
            starts=starts,
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            item_hashes=[params.item_hash] * len(task_ids),
            op_id=params.op_id,
            start_to_close_timeout_seconds=proc_secs,
        )
        return "ok"
