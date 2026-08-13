"""Temporal worker entry points for processing queues."""

import asyncio
import concurrent.futures
import logging
from temporalio.client import Client
from temporalio.worker import Worker

from .task_timing import TaskTimingInterceptor

log = logging.getLogger(__name__)


async def _probe_embeddings_at_startup(worker_name: str) -> None:
    """Record what the embeddings endpoint actually serves, before taking any work.

    The probe used to run only when a human or `verify-stack.sh` invoked
    `main.py probe-embeddings`. That made a model change a two-step operation where the
    second step was undocumented and easy to forget: every consumer correctly refuses
    while `embeddings_serving_model` is stale or missing (P5, P6's vector indexer,
    collection search), so the stack sat there refusing until someone remembered — the
    refusal being *correct* is exactly what made it hard to diagnose.

    Off the event loop because the probe is synchronous `requests`, and non-fatal because
    a worker that will not boot without the GPU tier is worse than one that boots and
    refuses one stage. Only the two workers that consume the value probe; the others have
    no business talking to the GPU tier at startup.
    """
    from .remote import record_embeddings_probe

    probed = await asyncio.to_thread(record_embeddings_probe)
    if probed is None:
        log.info("%s: no embeddings probe recorded at startup", worker_name)


async def run_common_worker():
    # Localized imports for common worker only
    from .P0_scan_disk.activities import list_disk_folder, insert_vfs_directories, ingest_files_batch
    from .P0_scan_disk.workflows import IngestAndProcessDataset, IngestDiskDataset, HandleFolders, HandleFiles
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
    from .P3_parse_files.document_dates import resolve_document_dates
    from .P3_parse_files.parse_text import extract_plaintext_chunks
    from .P3_parse_files.parse_office_xml import parse_office_xml_and_store
    from .P3_parse_files.parse_mime import detect_mime_with_gnu_file, detect_mime_with_magika
    from .P3_parse_files.parse_pdf import PdfProcessingAndScan, pdf_get_metadata_and_store, pdf_small_extract_text_and_images, pdf_large_split_to_chunks
    from .P3_parse_files.parse_image import parse_image_metadata_and_store
    from .P3_parse_files.parse_audio import parse_audio_metadata_and_store
    from .P3_parse_files.parse_video import VideoProcessingAndScan, video_ffprobe_and_store, video_extract_frames_and_subtitles
    from .plan_utils import fetch_plan_hashes
    from .P4_extract_entities.workflows import ExtractEntitiesForPlan
    from .P5_chunk_embed.workflows import ChunkEmbedForPlan
    from .P6_index_data.workflows import IndexDatasetPlan
    from .P_admin.activities import (
        collect_eta_samples,
        drop_collection_database,
        ensure_collection_database,
        purge_dataset_from_clickhouse,
        purge_dataset_from_manticore,
        recompute_shard_ledger_activity,
        sweep_chat_artifacts,
    )
    from .P_admin.ocr_languages import (
        begin_ocr_language_job,
        delete_orphaned_derived_pdfs,
        purge_dropped_ocr_variants,
        reopen_plans_for_ocr_change,
        report_ocr_language_progress,
    )
    from .P_admin.workflows import (
        ChangeOcrLanguages,
        CollectEtaSamples,
        DropCollectionDatabase,
        EnsureCollectionDatabase,
        PurgeDataset,
        SweepChatArtifacts,
    )
    from .P_agent.activities import run_research_agent, write_chat_message
    from .P_agent.workflows import ResearchTask
    from .visibility import ensure_search_attributes

    log.info("Starting common worker...")
    client = await Client.connect("temporal:7233")
    await ensure_search_attributes(client)

    # Self-scheduling ETA sampler for the admin processing page. A singleton:
    # two common workers race to (re-)assert it at startup, and
    # WorkflowAlreadyStartedError is the loser's normal outcome.
    import temporalio.common
    import temporalio.exceptions
    try:
        await client.start_workflow(
            CollectEtaSamples.run,
            id="collect-eta-samples",
            task_queue="processing-common-queue",
            id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except temporalio.exceptions.WorkflowAlreadyStartedError:
        pass

    # Daily chat-artifact retention. Same singleton pattern, same reason: two common
    # workers race to assert it and the loser's error is the normal outcome.
    try:
        await client.start_workflow(
            SweepChatArtifacts.run,
            id="sweep-chat-artifacts",
            task_queue="processing-common-queue",
            id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
        )
    except temporalio.exceptions.WorkflowAlreadyStartedError:
        pass

    CONCURRENCY = 8
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
        worker = Worker(
          client,
          interceptors=[TaskTimingInterceptor()],
          task_queue="processing-common-queue",
          workflows=[
            IngestDiskDataset,
            IngestAndProcessDataset,
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
            ExtractEntitiesForPlan,
            ChunkEmbedForPlan,
            IndexDatasetPlan,
            EnsureCollectionDatabase,
            DropCollectionDatabase,
            PurgeDataset,
            ChangeOcrLanguages,
            CollectEtaSamples,
            SweepChatArtifacts,
            ResearchTask,
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
            resolve_document_dates,
            extract_plaintext_chunks,
            parse_office_xml_and_store,
            pdf_get_metadata_and_store,
            pdf_small_extract_text_and_images,
            pdf_large_split_to_chunks,
            parse_image_metadata_and_store,
            parse_audio_metadata_and_store,
            video_ffprobe_and_store,
            video_extract_frames_and_subtitles,
            detect_mime_with_gnu_file,
            detect_mime_with_magika,

            # Shared plan helpers
            fetch_plan_hashes,

            # P_admin collection database lifecycle
            ensure_collection_database,
            drop_collection_database,
            purge_dataset_from_manticore,
            purge_dataset_from_clickhouse,
            recompute_shard_ledger_activity,
            collect_eta_samples,
            sweep_chat_artifacts,

            # P_admin change_ocr_languages apply job
            begin_ocr_language_job,
            report_ocr_language_progress,
            reopen_plans_for_ocr_change,
            purge_dropped_ocr_variants,
            delete_orphaned_derived_pdfs,

            # P_agent long-running AI research tasks
            run_research_agent,
            write_chat_message,
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
    from .visibility import ensure_search_attributes

    log.info("Starting Tika worker...")
    client = await Client.connect("temporal:7233")
    await ensure_search_attributes(client)
    CONCURRENCY = 8
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
        worker = Worker(
          client,
          interceptors=[TaskTimingInterceptor()],
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


async def run_ocr_worker():
    # Localized import for the OCR worker. The queue is engine-neutral
    # (`processing-ocr-queue`, not `processing-easyocr-queue`) because OCR is becoming
    # several engines behind one HTTP contract, and a queue named after one of them
    # would have to be renamed again -- which costs a full reset every time.
    from .P3_parse_files.parse_ocr import run_ocr_and_store
    # Searchable-PDF assembly shares this queue rather than getting one of its own: it is
    # one OCR call per page, so it must be bounded by the same tier that bounds image OCR.
    # A queue of its own would let a 500-page scan and every image in the corpus compete
    # for the OCR service from two directions at once.
    from .P3_parse_files.parse_ocr_pdf import run_ocr_pdf_and_store
    from .visibility import ensure_search_attributes

    log.info("Starting OCR worker...")
    client = await Client.connect("temporal:7233")
    await ensure_search_attributes(client)
    CONCURRENCY = 4
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
        worker = Worker(
          client,
          interceptors=[TaskTimingInterceptor()],
          task_queue="processing-ocr-queue",
          workflows=[],
          activities=[run_ocr_and_store, run_ocr_pdf_and_store],
          activity_executor=activity_executor,
          max_concurrent_activities=CONCURRENCY,
          max_concurrent_workflow_tasks=CONCURRENCY*2,
          max_concurrent_local_activities=CONCURRENCY*2,
          max_concurrent_activity_task_polls=CONCURRENCY*2,
          max_concurrent_workflow_task_polls=CONCURRENCY*2,
        )
        await worker.run()


async def run_nlp_worker():
  # Localized import for NLP-only worker
  from .P4_extract_entities.activities import extract_entities_for_hashes
  from .visibility import ensure_search_attributes
  log.info("Starting NLP worker...")
  client = await Client.connect("temporal:7233")
  await ensure_search_attributes(client)
  # The NER service is remote; concurrency here is about pipelining HTTP,
  # not local CPU.
  CONCURRENCY = 2
  with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
    worker = Worker(
      client,
      interceptors=[TaskTimingInterceptor()],
      task_queue="processing-nlp-queue",
      workflows=[],
      activities=[extract_entities_for_hashes],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await worker.run()


async def run_embed_worker():
  # Localized import for the embed-only worker. The embeddings endpoint is remote
  # (the GPU tier); concurrency here pipelines HTTP, not local CPU.
  from .P5_chunk_embed.activities import chunk_embed_for_hashes
  from .visibility import ensure_search_attributes
  log.info("Starting Embed worker...")
  client = await Client.connect("temporal:7233")
  await ensure_search_attributes(client)
  await _probe_embeddings_at_startup("embed worker")
  CONCURRENCY = 2
  with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
    worker = Worker(
      client,
      interceptors=[TaskTimingInterceptor()],
      task_queue="processing-embed-queue",
      workflows=[],
      activities=[chunk_embed_for_hashes],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await worker.run()


async def run_indexing_worker():
  from .P6_index_data.activities import (
      build_vfs_nodes, index_text_pages, index_vectors, index_vfs_structure,
      optimize_shard_tables,
  )
  from .visibility import ensure_search_attributes
  log.info("Starting Indexing worker...")
  client = await Client.connect("temporal:7233")
  await ensure_search_attributes(client)
  # `index_vectors` builds Manticore `_vectors` tables from the probed dimension, and a
  # table's knn_dims is fixed at creation — this worker needs the probe as much as P5.
  await _probe_embeddings_at_startup("indexing worker")
  CONCURRENCY = 1
  with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
    worker = Worker(
      client,
      interceptors=[TaskTimingInterceptor()],
      task_queue="processing-indexing-queue",
      workflows=[],
      activities=[index_text_pages, index_vectors, build_vfs_nodes,
                  index_vfs_structure, optimize_shard_tables],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await worker.run()


async def run_index_planner_worker():
  # WARNING: run EXACTLY ONE process of this worker. plan_shards reads and
  # rewrites the per-collection shard ledger (manticore_shards); two concurrent
  # planner activities for the same collection would corrupt it. The dedicated
  # queue plus max_concurrent_activities=1 is the whole concurrency story.
  from .P6_index_data.shard_planner import finalize_index_batch, plan_shards, record_indexed
  from .visibility import ensure_search_attributes
  log.info("Starting Index planner worker...")
  client = await Client.connect("temporal:7233")
  await ensure_search_attributes(client)
  CONCURRENCY = 1
  with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
    worker = Worker(
      client,
      interceptors=[TaskTimingInterceptor()],
      task_queue="processing-index-planner-queue",
      workflows=[],
      activities=[plan_shards, finalize_index_batch, record_indexed],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await worker.run()

# Removed parallel run_worker. Each worker runs in its own process via main CLI.