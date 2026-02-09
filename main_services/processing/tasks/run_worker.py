"""Temporal worker entry points for processing queues."""

import asyncio
import concurrent.futures
import logging
from temporalio.client import Client
from temporalio.worker import Worker

log = logging.getLogger(__name__)


async def run_common_worker():
    # Localized imports for common worker only
    from .P0_scan_disk.activities import list_disk_folder, insert_vfs_directories, ingest_files_batch
    from .P0_scan_disk.workflows import IngestDiskDataset, HandleFolders, HandleFiles
    from .P1_compute_plans.activities import count_new_blobs, compute_plans
    from .P1_compute_plans.workflows import ComputePlans
    from .P2_execute_plan.activities import (
        list_pending_plans,
        get_plan_items_metadata,
        download_plan_files,
        cleanup_plan_dir,
        mark_plan_finished,
        ensure_temp_dir_exists,
        record_processing_errors,
    )
    from .P2_execute_plan.workflows import (
        ExecutePlans,
        ExecuteSinglePlan,
        ProcessItemsBatched,
    )
    from .P3_parse_files.workflows import ParseSingleFile
    from .P3_parse_files.parse_archives import ArchiveExtractionAndScan, extract_archive_to_temp, cleanup_temp_dir, record_archive_container
    from .P3_parse_files.parse_email import parse_email_extract_text_headers, extract_email_attachments_to_temp, EmailExtractionAndScan
    from .P3_parse_files.parse_text import extract_plaintext_chunks
    from .P3_parse_files.parse_mime import detect_mime_with_gnu_file, detect_mime_with_magika
    from .P3_parse_files.parse_pdf import PdfProcessingAndScan, pdf_get_metadata_and_store, pdf_small_extract_text_and_images, pdf_large_split_to_chunks
    from .P3_parse_files.parse_image import parse_image_metadata_and_store
    from .P3_parse_files.parse_audio import parse_audio_metadata_and_store
    from .P3_parse_files.parse_video import VideoProcessingAndScan, video_ffprobe_and_store, video_extract_frames_and_subtitles
    from .P4_index_data.activities import fetch_plan_hashes, index_metadatas
    from .P4_index_data.workflows import IndexDatasetPlan

    log.info("Starting common worker...")
    client = await Client.connect("temporal:7233")
    CONCURRENCY = 8
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
        worker = Worker(
          client,
          task_queue="processing-common-queue",
          workflows=[
            IngestDiskDataset,
            HandleFolders,
            HandleFiles,
            ComputePlans,
            ExecutePlans,
            ExecuteSinglePlan,
            ProcessItemsBatched,
            ParseSingleFile,
            ArchiveExtractionAndScan,
            EmailExtractionAndScan,
            PdfProcessingAndScan,
            VideoProcessingAndScan,
            IndexDatasetPlan,
          ],
          activities=[
            list_disk_folder,
            insert_vfs_directories,
            ingest_files_batch,
            count_new_blobs,
            compute_plans,
            list_pending_plans,
            get_plan_items_metadata,
            download_plan_files,
            cleanup_plan_dir,
            mark_plan_finished,
            ensure_temp_dir_exists,
            record_processing_errors,
            extract_archive_to_temp,
            cleanup_temp_dir,
            record_archive_container,
            parse_email_extract_text_headers,
            extract_email_attachments_to_temp,
            extract_plaintext_chunks,
            pdf_get_metadata_and_store,
            pdf_small_extract_text_and_images,
            pdf_large_split_to_chunks,
            parse_image_metadata_and_store,
            parse_audio_metadata_and_store,
            video_ffprobe_and_store,
            video_extract_frames_and_subtitles,
            detect_mime_with_gnu_file,
            detect_mime_with_magika,

            # P4 Index Data
            fetch_plan_hashes,
            index_metadatas,
          ],
          activity_executor=activity_executor,
          max_concurrent_activities=CONCURRENCY,
          max_concurrent_workflow_tasks=CONCURRENCY*2,
          max_concurrent_local_activities=CONCURRENCY*2,
          max_concurrent_activity_task_polls=CONCURRENCY*2,
          max_concurrent_workflow_task_polls=CONCURRENCY*2,
        )
        await worker.run()


async def run_tika_worker():
    # Localized import for Tika-only worker
    from .P3_parse_files.parse_tika import run_tika_and_store

    log.info("Starting Tika worker...")
    client = await Client.connect("temporal:7233")
    CONCURRENCY = 8
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
        worker = Worker(
          client,
          task_queue="processing-tika-queue",
          workflows=[],
          activities=[run_tika_and_store],
          activity_executor=activity_executor,
          max_concurrent_activities=CONCURRENCY,
          max_concurrent_workflow_tasks=CONCURRENCY*2,
          max_concurrent_local_activities=CONCURRENCY*2,
          max_concurrent_activity_task_polls=CONCURRENCY*2,
          max_concurrent_workflow_task_polls=CONCURRENCY*2,
        )
        await worker.run()


async def run_easyocr_worker():
    # Localized import for EasyOCR-only worker
    from .P3_parse_files.parse_ocr import run_easyocr_and_store

    log.info("Starting EasyOCR worker...")
    client = await Client.connect("temporal:7233")
    CONCURRENCY = 4
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
        worker = Worker(
          client,
          task_queue="processing-easyocr-queue",
          workflows=[],
          activities=[run_easyocr_and_store],
          activity_executor=activity_executor,
          max_concurrent_activities=CONCURRENCY,
          max_concurrent_workflow_tasks=CONCURRENCY*2,
          max_concurrent_local_activities=CONCURRENCY*2,
          max_concurrent_activity_task_polls=CONCURRENCY*2,
          max_concurrent_workflow_task_polls=CONCURRENCY*2,
        )
        await worker.run()


async def run_indexing_worker():
  from .P4_index_data.activities import index_text_content
  log.info("Starting Indexing worker...")
  client = await Client.connect("temporal:7233")
  CONCURRENCY = 1
  with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
    worker = Worker(
      client,
      task_queue="processing-indexing-queue",
      workflows=[],
      activities=[index_text_content],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await worker.run()

# Removed parallel run_worker. Each worker runs in its own process via main CLI.