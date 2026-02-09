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
    from tasks.P3_parse_files.parse_pdf import PdfProcessingWorkflowParams
    from tasks.P3_parse_files.parse_email import EmailExtractionWorkflowParams
    from tasks.P3_parse_files.parse_common import record_errors_from_results
    from tasks.P3_parse_files.parse_archives import ArchiveExtractionAndScan
    from tasks.P3_parse_files.parse_email import parse_email_extract_text_headers, EmailExtractionAndScan
    from tasks.P3_parse_files.parse_text import extract_plaintext_chunks
    from tasks.P3_parse_files.parse_tika import run_tika_and_store, RunTikaParams
    from tasks.P3_parse_files.parse_mime import detect_mime_with_gnu_file, detect_mime_with_magika, DetectMimeParams
    from tasks.P3_parse_files.parse_pdf import PdfProcessingAndScan
    from tasks.P3_parse_files.parse_image import parse_image_metadata_and_store, ParseImageParams
    from tasks.P3_parse_files.parse_audio import parse_audio_metadata_and_store, ParseAudioParams
    from tasks.P3_parse_files.parse_video import VideoProcessingAndScan
    from tasks.P3_parse_files.parse_ocr import run_easyocr_and_store, RunEasyOCRParams
    from tasks.P2_execute_plan.activities import record_processing_errors


@dataclass
class ParseSingleFileParams:
    collection_dataset: str
    plan_hash: str
    item_hash: str
    file_path: str
    file_size_bytes: int | None = None


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

        # First, detect MIME/type via two parallel activities: `file` and Tika
        mime_fut = workflow.execute_activity(
            detect_mime_with_gnu_file,
            DetectMimeParams(
                collection_dataset=params.collection_dataset,
                file_hash=params.item_hash,
                file_path=params.file_path,
                timeout_seconds=proc_secs,
            ),
            start_to_close_timeout=timedelta(seconds=proc_secs),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        tika_fut = workflow.execute_activity(
            run_tika_and_store,
            RunTikaParams(
                collection_dataset=params.collection_dataset,
                file_hash=params.item_hash,
                file_path=params.file_path,
                content_type="application/octet-stream",
                timeout_seconds=1000+proc_secs,
            ),
            start_to_close_timeout=timedelta(seconds=1000+proc_secs),
            retry_policy=RetryPolicy(maximum_attempts=3),
            task_queue="processing-tika-queue",
        )

        magika_fut = workflow.execute_activity(
            detect_mime_with_magika,
            DetectMimeParams(
                collection_dataset=params.collection_dataset,
                file_hash=params.item_hash,
                file_path=params.file_path,
                timeout_seconds=proc_secs,
            ),
            start_to_close_timeout=timedelta(seconds=proc_secs),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        mime_res, tika_res, magika_res = await asyncio.gather(mime_fut, tika_fut, magika_fut, return_exceptions=True)

        def _as_list(d: dict | Any, key: str) -> List[str]:
            v = d.get(key) if isinstance(d, dict) else []
            if not v:
                return []
            return list({str(x) for x in v if isinstance(x, str) and x})

        async def _combine_detector_results(detector_results: List[Any]) -> Dict[str, List[str]]:
            all_coarse: List[str] = []
            all_mime: List[str] = []
            all_enc: List[str] = []
            detector_names = ["file", "tika", "magika"]
            for det_name, res in zip(detector_names, detector_results):
                if isinstance(res, Exception):
                    # Record error asynchronously with detector-specific task id
                    try:
                        await workflow.execute_activity(
                            record_processing_errors,
                            {
                                "collection_dataset": params.collection_dataset,
                                "item_hashes": [params.item_hash],
                                "task_ids": [f"detector_error_{det_name}"],
                                "errors": [str(res)],
                            },
                            start_to_close_timeout=timedelta(minutes=15),
                            retry_policy=RetryPolicy(maximum_attempts=1),
                        )
                    except Exception:
                        pass
                    continue
                all_coarse += _as_list(res, "coarse_types")
                all_mime += _as_list(res, "mime_types")
                all_enc += _as_list(res, "mime_encodings")
            return {
                "coarse_types": sorted(set(all_coarse)),
                "mime_types": sorted(set(all_mime)),
                "mime_encodings": sorted(set(all_enc)),
            }

        combined = await _combine_detector_results([mime_res, tika_res, magika_res])
        coarse_types: List[str] = combined["coarse_types"]
        mime_types: List[str] = combined["mime_types"]
        mime_encodings: List[str] = combined["mime_encodings"]

        # Always log baseline args
        futs: List = []
        task_ids: List[str] = []
        starts: List = []


        # Route by type
        if "archive" in coarse_types:
            child_id = f"archive-scan-{params.collection_dataset}-{params.item_hash}"
            futs.append(
                workflow.execute_child_workflow(
                    ArchiveExtractionAndScan.run,
                    {
                        "collection_dataset": params.collection_dataset,
                        "archive_hash": params.item_hash,
                        "archive_types": mime_types,
                        "archive_path": params.file_path,
                        "timeout_seconds": proc_secs,
                    },
                    task_queue="processing-common-queue",
                    id=child_id
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
                        collection_dataset=params.collection_dataset,
                        email_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                    ),
                    task_queue="processing-common-queue",
                    id=child_id
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
                        collection_dataset=params.collection_dataset,
                        file_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                    ),
                    start_to_close_timeout=timedelta(seconds=proc_secs),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            )
            task_ids.append("extract_plaintext_chunks")
            starts.append(workflow.now())

        if "pdf" in coarse_types:
            child_id = f"pdf-process-{params.collection_dataset}-{params.item_hash}"
            futs.append(
                workflow.execute_child_workflow(
                    PdfProcessingAndScan.run,
                    PdfProcessingWorkflowParams(
                        collection_dataset=params.collection_dataset,
                        pdf_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                    ),
                    task_queue="processing-common-queue",
                    id=child_id,
                )
            )
            task_ids.append("pdf_process")
            starts.append(workflow.now())

        if "image" in coarse_types:
            futs.append(
                workflow.execute_activity(
                    parse_image_metadata_and_store,
                    ParseImageParams(
                        collection_dataset=params.collection_dataset,
                        file_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                    ),
                    start_to_close_timeout=timedelta(seconds=proc_secs),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            )
            task_ids.append("parse_image_metadata_and_store")
            starts.append(workflow.now())

            # Also run EasyOCR for text extraction from the image (routed to easyocr queue)
            futs.append(
                workflow.execute_activity(
                    run_easyocr_and_store,
                    RunEasyOCRParams(
                        collection_dataset=params.collection_dataset,
                        file_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                    ),
                    start_to_close_timeout=timedelta(seconds=proc_secs),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                    task_queue="processing-easyocr-queue",
                )
            )
            task_ids.append("run_easyocr_and_store")
            starts.append(workflow.now())

        if "audio" in coarse_types:
            futs.append(
                workflow.execute_activity(
                    parse_audio_metadata_and_store,
                    ParseAudioParams(
                        collection_dataset=params.collection_dataset,
                        file_hash=params.item_hash,
                        file_path=params.file_path,
                        timeout_seconds=proc_secs,
                    ),
                    start_to_close_timeout=timedelta(seconds=proc_secs),
                    retry_policy=RetryPolicy(maximum_attempts=3),
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
                        "collection_dataset": params.collection_dataset,
                        "video_hash": params.item_hash,
                        "file_path": params.file_path,
                        "timeout_seconds": proc_secs,
                    },
                    task_queue="processing-common-queue",
                    id=child_id,
                )
            )
            task_ids.append("video_process")
            starts.append(workflow.now())

        # Already ran Tika above; no need to run again here

        # Wait for all and capture exceptions, then record via common helper
        results = await asyncio.gather(*futs, return_exceptions=True)
        await record_errors_from_results(
            results,
            task_ids=task_ids,
            starts=starts,
            collection_dataset=params.collection_dataset,
            item_hashes=[params.item_hash] * len(task_ids),
            start_to_close_timeout_seconds=proc_secs,
        )
        return "ok"


