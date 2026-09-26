"""Temporal worker entry points for processing queues."""

import asyncio
import concurrent.futures
import logging
import os
import signal
from datetime import timedelta
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from .operation_failure_capture import (
    OperationFailureInterceptor, capture_operation_failure,
)
from .payload_guard import PayloadGuardInterceptor
from .task_timing import TaskTimingInterceptor, attach_temporal_client
from .worker_memory import ActivityMemoryInterceptor, watch_memory

log = logging.getLogger(__name__)

#: Every worker fails a workflow on its first attempt when workflow code raises.
#:
#: Without this, a Python exception in workflow code fails only the workflow task, and
#: Temporal 1.23 retries a failed workflow task at once and without a limit. A superclass
#: of `NondeterminismError` is in this list, so a non-determinism error fails the workflow
#: too. A deploy that changes a workflow's code therefore fails the runs of that workflow
#: that are in flight.
WORKFLOW_FAILURE_EXCEPTION_TYPES = [Exception]


def guard_interceptors() -> list:
    """The interceptors that every worker carries after its own ones.

    `PayloadGuardInterceptor` comes after `OperationFailureInterceptor`, so a refused
    workflow result reaches the failure capture as a workflow failure.
    """
    return [PayloadGuardInterceptor(), ActivityMemoryInterceptor()]


#: Graceful shutdown period when `HOOVER4_WORKER_GRACEFUL_SHUTDOWN_SECONDS` says nothing.
#:
#: The SDK's own default is `timedelta()` -- ZERO -- which means a worker that is told to
#: stop kills its in-flight activities where they stand. The server does not find out
#: until each one's heartbeat deadline expires, and every one of them then comes back as
#: a timeout against a retry budget that was never meant to absorb a deploy. That is not
#: a hypothetical: one restart under load produced 87 activity timeouts and left 14
#: documents permanently without embeddings on a plan that reported success.
DEFAULT_GRACEFUL_SHUTDOWN_SECONDS = 60


def graceful_shutdown_timeout() -> timedelta:
    """How long in-flight activities get before cancellation, from the environment.

    The container's own stop grace period is derived from the same ini key, with a
    margin on top. Do not raise this by editing a literal here: a graceful period longer
    than the container's grace period is false, because the runtime sends SIGKILL first.
    """
    raw = os.environ.get("HOOVER4_WORKER_GRACEFUL_SHUTDOWN_SECONDS", "").strip()
    seconds = DEFAULT_GRACEFUL_SHUTDOWN_SECONDS
    if raw:
        try:
            seconds = max(0, int(raw))
        except ValueError:
            log.warning(
                "HOOVER4_WORKER_GRACEFUL_SHUTDOWN_SECONDS is not a number: %r", raw)
    return timedelta(seconds=seconds)


async def run_until_signalled(*workers: Worker) -> None:
    """Run workers until they finish or the process is asked to stop.

    `Worker.run()` returns when `shutdown()` is called, and nothing calls it unless
    something listens for the signal. Without this, SIGTERM kills the interpreter
    mid-activity and the graceful period configured on the worker never happens --
    the setting is present, correct and unreachable.

    Variadic because one process may serve several queues, and a per-worker handler
    would not do: `add_signal_handler` REPLACES the handler for a signal rather than
    adding to it, so the last worker to install one would be the only one ever told to
    drain and the others would be killed mid-activity. One handler stops all of them.

    Both SIGTERM (what a container runtime sends) and SIGINT (Ctrl-C) are handled, and
    a second signal is left to the default disposition so an operator can still force
    the issue.
    """
    loop = asyncio.get_running_loop()
    name = ", ".join(w.task_queue for w in workers)
    stopping = False

    def request_shutdown(signum: int) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        log.info("%s: %s received, draining in-flight activities",
                 name, signal.Signals(signum).name)
        loop.remove_signal_handler(signum)
        for worker in workers:
            loop.create_task(worker.shutdown())

    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, request_shutdown, signum)
        except (NotImplementedError, RuntimeError):
            # No signal handling on this loop (a non-main thread, or a platform
            # without it). The worker still runs; it just dies abruptly.
            log.warning("%s: cannot install a %s handler", name, signum)

    # The memory log runs beside the workers and stops when they have shut down.
    memory = loop.create_task(watch_memory(name))
    try:
        await asyncio.gather(*(worker.run() for worker in workers))
    finally:
        memory.cancel()
    log.info("%s: shut down", name)


def sandboxed_runner() -> SandboxedWorkflowRunner:
    """The workflow sandbox, with this repo's own packages passed through.

    The sandbox re-imports a workflow's module graph for every workflow INSTANCE it
    creates, and this pipeline creates one per file. Passing `tasks` and `database`
    through takes that from ~1.5 ms to ~0.2 ms per instance, and it costs no safety
    that was being relied on: every workflow module already wraps its own imports in
    `workflow.unsafe.imports_passed_through()`, so these modules were never being
    re-imported for isolation -- only for nothing. The sandbox keeps doing its real job,
    which is catching non-deterministic use of the standard library.
    """
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(
            "tasks", "database",
        )
    )


def worker_concurrency(name: str, default: int) -> int:
    """Activity slots for one worker tier, from `HOOVER4_<NAME>_CONCURRENCY`.

    The defaults below are shaped by what each tier is waiting on, not by the host: tika
    holds a subprocess helper per slot, and the NLP and embed tiers pipeline HTTP against
    a remote GPU that has its own admission control -- more slots there only deepen a
    queue somebody else is already bounding.

    The common tier is the one to be careful with. Its slots multiply by the process
    count, and each slot's work is not one thread: a single detection forks several
    `file` processes and runs an ONNX model. Measured on a sixteen-core host, 4 processes
    of 8 slots demanded 22 cores during the parse burst -- the activities do not fail
    there, they just all take twice as long and the box has nothing left for anything
    else. Prefer more processes with fewer slots each: it is the same admission width
    with less contention inside any one interpreter.
    """
    import os
    raw = os.environ.get("HOOVER4_%s_CONCURRENCY" % name.upper(), "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("HOOVER4_%s_CONCURRENCY is not a number: %r", name.upper(), raw)
        return default
    return max(1, value)


#: Common-worker processes when `HOOVER4_COMMON_WORKERS` says nothing.
#:
#: Deliberately a CONSTANT and not a function of `os.cpu_count()`. The fleet's cost is
#: memory, not cores -- every process carries its own interpreter and its own Magika
#: model -- so a core-derived number quietly multiplies memory on a large host and
#: busts the container's limit there while looking fine on a laptop. The number that
#: decides CPU load is this times `common_concurrency`, and both are explicit for the
#: same reason: the two together are what has to fit the box, and neither is safe to
#: infer from the other.
DEFAULT_COMMON_WORKERS = 10


def common_worker_processes() -> int:
    """How many common-worker processes to spawn: `HOOVER4_COMMON_WORKERS`, else 10."""
    import os
    raw = os.environ.get("HOOVER4_COMMON_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            log.warning("HOOVER4_COMMON_WORKERS is not a number: %r", raw)
    return DEFAULT_COMMON_WORKERS


#: Index-worker processes when `HOOVER4_INDEXING_WORKERS` says nothing. Each process
#: serves `processing-indexing-queue` with `indexing_concurrency` slots, 1 by default.
#: The email graph runs in its own process, so an index process holds one writer chunk
#: or one dataset-wide activity at a time.
DEFAULT_INDEXING_WORKERS = 4


def indexing_worker_processes() -> int:
    """How many index-worker processes to spawn: `HOOVER4_INDEXING_WORKERS`, else 4."""
    import os
    raw = os.environ.get("HOOVER4_INDEXING_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            log.warning("HOOVER4_INDEXING_WORKERS is not a number: %r", raw)
    return DEFAULT_INDEXING_WORKERS


def common_max_cached_workflows() -> int:
    """Cached workflow runs for each common worker: `HOOVER4_COMMON_MAX_CACHED_WORKFLOWS`.

    deploy.py renders it from `common_max_cached_workflows`, default 100. Unset means the
    same 100. The SDK's own default of 1000 applies only when a Worker is given no value.
    """
    import os
    raw = os.environ.get("HOOVER4_COMMON_MAX_CACHED_WORKFLOWS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            log.warning("HOOVER4_COMMON_MAX_CACHED_WORKFLOWS is not a number: %r", raw)
    return 100


async def _probe_embeddings_at_startup(worker_name: str) -> None:
    """Record what the embeddings endpoint actually serves, before taking any work.

    The probe used to run only when a human or `verify-stack.sh` invoked
    `main.py probe-embeddings`. That made a model change a two-step operation where the
    second step was undocumented and commonly forgotten: every consumer correctly refuses
    while `embeddings_serving_model` is stale or missing (P5, P6's vector indexer,
    collection search), so the stack sat there refusing until someone remembered. The
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
    from .P0_scan_disk.activities import (
        plan_folder_ranges, scan_folder_range,
        reconcile_deleted_files,
    )
    from .P0_scan_disk.workflows import IngestAndProcessDataset, IngestDiskDataset, HandleFolders
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
    from .P3_parse_files.parse_archives import extract_archive_batch
    from .P3_parse_files.parse_email import parse_email_headers_batch, extract_email_attachments_batch
    from .P3_parse_files.document_dates import resolve_document_dates
    from .P3_parse_files.parse_text import extract_plaintext_batch
    from .P3_parse_files.parse_office_xml import parse_office_xml_batch
    from .P3_parse_files.parse_table import parse_table_batch
    from .P3_parse_files.parse_mime import detect_mime_batch
    from .P3_parse_files.parse_pdf import pdf_metadata_batch, pdf_extract_batch
    from .P3_parse_files.parse_image import parse_image_metadata_batch
    from .P3_parse_files.parse_audio import parse_audio_metadata_batch
    from .P3_parse_files.parse_video import video_batch
    from .P3_parse_files.member_scan import scan_container_folders
    from .plan_utils import fetch_plan_hashes
    from .P4_extract_entities.workflows import ExtractEntitiesForPlan, ScanRegexEntitiesForPlan
    from .P4_extract_entities.scan_regex_entities import scan_regex_entities_for_hashes
    from .P5_chunk_embed.workflows import ChunkEmbedForPlan
    from .P6_index_data.workflows import IndexDatasetPlan, RefreshDocumentLocations
    from .P_admin.activities import (
        collect_eta_samples,
        drop_collection_database,
        ensure_collection_database,
        purge_dataset_from_clickhouse,
        purge_dataset_from_manticore,
        recompute_shard_ledger_activity,
        sweep_chat_artifacts,
        sweep_orphan_table_cells,
    )
    from .P_admin.rerun_selection import (
        reconcile_selected_errors,
        select_historical_errors,
    )
    from .P_admin.collection_backfill import (
        clear_unattributed_entities,
        list_finished_plans,
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
    from .visibility import ensure_search_attributes

    log.info("Starting common worker...")
    client = await Client.connect("temporal:7233")
    attach_temporal_client(client)
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

    CONCURRENCY = worker_concurrency("common", 3)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
        worker = Worker(
          client,
          interceptors=[TaskTimingInterceptor(), OperationFailureInterceptor(), *guard_interceptors()],
          workflow_runner=sandboxed_runner(),
          task_queue="processing-common-queue",
          graceful_shutdown_timeout=graceful_shutdown_timeout(),
          workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
          max_cached_workflows=common_max_cached_workflows(),
          workflows=[
            IngestDiskDataset,
            IngestAndProcessDataset,
            HandleFolders,
            ComputePlans,
            ExecutePlans,
            ExecuteSinglePlan,
            ProcessItemsBatched,
            ExtractEntitiesForPlan,
            ScanRegexEntitiesForPlan,
            ChunkEmbedForPlan,
            IndexDatasetPlan,
            RefreshDocumentLocations,
            EnsureCollectionDatabase,
            DropCollectionDatabase,
            PurgeDataset,
            ChangeOcrLanguages,
            CollectEtaSamples,
            SweepChatArtifacts,
          ],
          activities=[
            plan_folder_ranges,
            scan_folder_range,
            reconcile_deleted_files,
            count_new_blobs,
            compute_plans,
            list_pending_plans,
            get_plan_items_metadata,
            download_plan_files,
            cleanup_plan_dir,
            mark_plan_finished,
            ensure_temp_dir_exists,
            record_processing_errors,
            resolve_document_dates,

            # The stage activities of the group workflow on this queue. Each one runs
            # its per-file function for every file of its stage.
            detect_mime_batch,
            extract_plaintext_batch,
            parse_office_xml_batch,
            parse_table_batch,
            parse_image_metadata_batch,
            parse_audio_metadata_batch,
            parse_email_headers_batch,
            extract_email_attachments_batch,
            extract_archive_batch,
            pdf_metadata_batch,
            pdf_extract_batch,
            video_batch,
            scan_container_folders,

            # Regex entity scanning: CPU work in another container, so it pipelines
            # HTTP here and belongs on the common queue rather than on the NLP tier's.
            scan_regex_entities_for_hashes,

            # Shared plan helpers
            fetch_plan_hashes,

            # P_admin collection database lifecycle
            ensure_collection_database,
            drop_collection_database,
            purge_dataset_from_manticore,
            purge_dataset_from_clickhouse,
            recompute_shard_ledger_activity,
            sweep_orphan_table_cells,
            collect_eta_samples,
            sweep_chat_artifacts,

            # P_admin change_ocr_languages apply job
            begin_ocr_language_job,
            report_ocr_language_progress,
            reopen_plans_for_ocr_change,
            purge_dropped_ocr_variants,
            delete_orphaned_derived_pdfs,
            select_historical_errors,
            reconcile_selected_errors,
            clear_unattributed_entities,
            list_finished_plans,

            capture_operation_failure,
          ],
          activity_executor=activity_executor,
          max_concurrent_activities=CONCURRENCY,
          max_concurrent_workflow_tasks=CONCURRENCY*2,
          max_concurrent_local_activities=CONCURRENCY*2,
          max_concurrent_activity_task_polls=CONCURRENCY*2,
          max_concurrent_workflow_task_polls=CONCURRENCY*2,
        )
        await run_until_signalled(worker)


async def run_tika_worker():
    # Localized import for Tika-only worker
    from .P3_parse_files.parse_tika import run_tika_batch
    from .visibility import ensure_search_attributes

    log.info("Starting Tika worker...")
    client = await Client.connect("temporal:7233")
    await ensure_search_attributes(client)
    CONCURRENCY = worker_concurrency("tika", 8)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
        worker = Worker(
          client,
          interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
          workflow_runner=sandboxed_runner(),
          task_queue="processing-tika-queue",
          graceful_shutdown_timeout=graceful_shutdown_timeout(),
          workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
          workflows=[],
          activities=[run_tika_batch],
          activity_executor=activity_executor,
          max_concurrent_activities=CONCURRENCY,
          max_concurrent_workflow_tasks=CONCURRENCY*2,
          max_concurrent_local_activities=CONCURRENCY*2,
          max_concurrent_activity_task_polls=CONCURRENCY*2,
          max_concurrent_workflow_task_polls=CONCURRENCY*2,
        )
        await run_until_signalled(worker)


async def run_ocr_worker():
    # Localized import for the OCR worker. The queue is engine-neutral
    # (`processing-ocr-queue`, not `processing-easyocr-queue`) because OCR is becoming
    # several engines behind one HTTP contract, and a queue named after one of them
    # would have to be renamed again -- which costs a full reset every time.
    from .P3_parse_files.parse_ocr import run_ocr_batch
    # Searchable-PDF assembly shares this queue rather than getting one of its own: it is
    # one OCR call per page, so it must be bounded by the same tier that bounds image OCR.
    # A queue of its own would let a 500-page scan and every image in the corpus compete
    # for the OCR service from two directions at once.
    from .P3_parse_files.parse_ocr_pdf import run_ocr_pdf_batch
    from .visibility import ensure_search_attributes

    log.info("Starting OCR worker...")
    client = await Client.connect("temporal:7233")
    await ensure_search_attributes(client)
    CONCURRENCY = worker_concurrency("ocr", 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
        worker = Worker(
          client,
          interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
          workflow_runner=sandboxed_runner(),
          task_queue="processing-ocr-queue",
          graceful_shutdown_timeout=graceful_shutdown_timeout(),
          workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
          workflows=[],
          activities=[run_ocr_batch, run_ocr_pdf_batch],
          activity_executor=activity_executor,
          max_concurrent_activities=CONCURRENCY,
          max_concurrent_workflow_tasks=CONCURRENCY*2,
          max_concurrent_local_activities=CONCURRENCY*2,
          max_concurrent_activity_task_polls=CONCURRENCY*2,
          max_concurrent_workflow_task_polls=CONCURRENCY*2,
        )
        await run_until_signalled(worker)


async def run_nlp_worker():
  # Localized import for NLP-only worker
  from .P4_extract_entities.activities import extract_entities_for_hashes
  from .visibility import ensure_search_attributes
  log.info("Starting NLP worker...")
  client = await Client.connect("temporal:7233")
  await ensure_search_attributes(client)
  # The NER service is remote; concurrency here is about pipelining HTTP, not local
  # CPU, so the number to match is the server's own admission window (its
  # ai_server_ner_concurrency, 4) rather than anything about this host. Below it the
  # GPU idles between batches; above it the server sheds with 503 + Retry-After, which
  # remote.py retries -- so the cost of being wrong is asymmetric and this sits at the
  # window rather than under it.
  CONCURRENCY = worker_concurrency("nlp", 4)
  with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
    worker = Worker(
      client,
      interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
      workflow_runner=sandboxed_runner(),
      task_queue="processing-nlp-queue",
      graceful_shutdown_timeout=graceful_shutdown_timeout(),
      workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
      workflows=[],
      activities=[extract_entities_for_hashes],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await run_until_signalled(worker)


async def run_embed_worker():
  # Localized import for the embed-only worker. The embeddings endpoint is remote
  # (the GPU tier); concurrency here pipelines HTTP, not local CPU.
  from .P5_chunk_embed.activities import chunk_embed_for_hashes
  from .visibility import ensure_search_attributes
  log.info("Starting Embed worker...")
  client = await Client.connect("temporal:7233")
  await ensure_search_attributes(client)
  await _probe_embeddings_at_startup("embed worker")
  # Same reasoning as the NLP tier: match the embeddings server's admission window
  # (ai_server_embed_concurrency, 8) rather than this host. A plan's chunk+embed work
  # arrives as a handful of long activities, so slots below that number turn one stage
  # into several serial waves at the end of every plan.
  CONCURRENCY = worker_concurrency("embed", 6)
  with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
    worker = Worker(
      client,
      interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
      workflow_runner=sandboxed_runner(),
      task_queue="processing-embed-queue",
      graceful_shutdown_timeout=graceful_shutdown_timeout(),
      workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
      workflows=[],
      activities=[chunk_embed_for_hashes],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await run_until_signalled(worker)


async def run_indexing_worker():
  from .P6_index_data.activities import (
      build_vfs_nodes, index_text_pages, index_vectors,
      index_entity_terms, index_vfs_structure, optimize_shard_tables,
      refresh_stale_document_locations, resolve_canonical_file_type,
  )
  from .visibility import ensure_search_attributes
  log.info("Starting Indexing worker...")
  client = await Client.connect("temporal:7233")
  await ensure_search_attributes(client)
  # `index_vectors` builds Manticore `_vectors` tables from the probed dimension, and a
  # table's knn_dims is fixed at creation. This worker needs the probe as much as P5.
  await _probe_embeddings_at_startup("indexing worker")
  CONCURRENCY = worker_concurrency("indexing", 1)
  with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
    worker = Worker(
      client,
      interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
      workflow_runner=sandboxed_runner(),
      task_queue="processing-indexing-queue",
      graceful_shutdown_timeout=graceful_shutdown_timeout(),
      workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
      workflows=[],
      activities=[index_text_pages, index_vectors, build_vfs_nodes,
                  index_vfs_structure, optimize_shard_tables,
                  resolve_canonical_file_type, index_entity_terms,
                  refresh_stale_document_locations],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await run_until_signalled(worker)


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
      interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
      workflow_runner=sandboxed_runner(),
      task_queue="processing-index-planner-queue",
      graceful_shutdown_timeout=graceful_shutdown_timeout(),
      workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
      workflows=[],
      activities=[plan_shards, finalize_index_batch, record_indexed],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await run_until_signalled(worker)


async def run_email_graph_worker():
  # WARNING: run EXACTLY ONE process of this worker. build_email_graph deletes the
  # rows of its collection that are older than its own start, so two concurrent runs
  # on one collection can delete the rows that the other run wrote. The dedicated
  # queue plus max_concurrent_activities=1 keeps one run at a time for the whole
  # deployment. The graph reads no vector, so this worker does not probe the
  # embedding server.
  from .P6_index_data.activities import build_email_graph
  from .P6_index_data.workflows import EMAIL_GRAPH_TASK_QUEUE
  from .visibility import ensure_search_attributes
  log.info("Starting Email graph worker...")
  client = await Client.connect("temporal:7233")
  await ensure_search_attributes(client)
  CONCURRENCY = 1
  with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as activity_executor:
    worker = Worker(
      client,
      interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
      workflow_runner=sandboxed_runner(),
      task_queue=EMAIL_GRAPH_TASK_QUEUE,
      graceful_shutdown_timeout=graceful_shutdown_timeout(),
      workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
      workflows=[],
      activities=[build_email_graph],
      activity_executor=activity_executor,
      max_concurrent_activities=CONCURRENCY,
    )
    await run_until_signalled(worker)


#: Slots per operations queue. The numbers are the point of the split, not the split.
#:
#: `operations-queue` orchestrates and never does store work, so its slots are cheap.
#: The three store queues are separated so a long backup on one store cannot starve
#: another, and each is capped at what that store can usefully absorb: ClickHouse gets
#: ONE because concurrent backups and restores are disabled in its server config
#: anyway, and a second slot would only queue inside ClickHouse where nothing here can
#: see it. `operations-admission-queue` gets ONE so the count and the write of one
#: admission never interleave with another, which is what keeps each kind under its cap.
OPERATIONS_QUEUE_SLOTS = {
    "operations-queue": 8,
    "operations-clickhouse-queue": 1,
    "operations-manticore-queue": 2,
    "operations-garage-queue": 2,
    "operations-admission-queue": 1,
}


#: The longest gap between two heartbeats that the SDK sends for a `run_agent` activity.
#: The SDK holds back each heartbeat for 0.8 of the heartbeat timeout by default, which is
#: 48 s for a chat run, and a stop reaches the activity only with a heartbeat reply. At 5 s,
#: with the `run_agent` pump at `RUN_AGENT_HEARTBEAT_SECONDS`, a stop ends the run in
#: about 10 s or less.
RUN_AGENT_HEARTBEAT_THROTTLE = timedelta(seconds=5)


async def run_chat_worker():
  """Serve the three agent queues from one process.

  One process rather than three because the slot counts, not the process boundary, are
  what bounds the load: twelve slots of mostly-waiting work do not need three interpreters,
  and one process means one place for the container's memory budget to apply. The queues
  stay separate so a long model turn cannot hold a write slot, and a research turn cannot
  take a chat-model slot.

  `chat-queue` carries `AgentRun` and its short activities (open, nag, ending, fan-in,
  todo read, title). `chat-model-queue` carries `run_agent` for a chat turn.
  `research-queue` carries `run_agent` for a run whose row names that queue: the planner
  and organizer runs of a deep-research plan, and their sub-agents. A slot is one agent run in flight, not one model call. One run makes
  up to `AGENT_MAX_TOOL_TURNS` model calls in sequence. Each sub-agent runs its own
  `run_agent` on its parent's queue, so a delegated turn takes one slot for each running
  sub-agent.

  The three queues are not the ingestion queue. An ingestion backlog delaying a person
  waiting at a screen is the failure a shared queue guarantees, and these three make it
  impossible. The worker deploys before the website: a workflow addressed to a queue
  nothing polls waits for ever with no error anywhere.
  """
  from .P_agent.activities import (
      append_nag,
      continue_run,
      fan_in,
      open_run,
      read_chat_todo,
      run_agent,
      summarize_if_first_turn,
      write_ending,
  )
  from .P_agent.workflows import (
      CHAT_MODEL_TASK_QUEUE,
      CHAT_TASK_QUEUE,
      RESEARCH_TASK_QUEUE,
      AgentRun,
  )
  from .visibility import ensure_search_attributes
  log.info("Starting Chat worker...")
  client = await Client.connect("temporal:7233")
  attach_temporal_client(client)
  await ensure_search_attributes(client)
  # An empty key yields 4, 8 and 4. The ini sets 4, 4 and 4.
  model_slots = worker_concurrency("chat_model", 4)
  low_latency_slots = worker_concurrency("chat_low_latency", 8)
  research_slots = worker_concurrency("research", 4)
  thread_count = model_slots + low_latency_slots + research_slots
  with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as activity_executor:
    workers = [
      Worker(
        client,
        interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
        workflow_runner=sandboxed_runner(),
        task_queue=CHAT_TASK_QUEUE,
        graceful_shutdown_timeout=graceful_shutdown_timeout(),
        workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
        workflows=[AgentRun],
        activities=[
            open_run, append_nag, write_ending, summarize_if_first_turn, fan_in,
            continue_run, read_chat_todo,
        ],
        activity_executor=activity_executor,
        max_concurrent_activities=low_latency_slots,
      ),
      Worker(
        client,
        interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
        workflow_runner=sandboxed_runner(),
        task_queue=CHAT_MODEL_TASK_QUEUE,
        graceful_shutdown_timeout=graceful_shutdown_timeout(),
        max_heartbeat_throttle_interval=RUN_AGENT_HEARTBEAT_THROTTLE,
        workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
        workflows=[],
        activities=[run_agent],
        activity_executor=activity_executor,
        max_concurrent_activities=model_slots,
      ),
      Worker(
        client,
        interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
        workflow_runner=sandboxed_runner(),
        task_queue=RESEARCH_TASK_QUEUE,
        graceful_shutdown_timeout=graceful_shutdown_timeout(),
        max_heartbeat_throttle_interval=RUN_AGENT_HEARTBEAT_THROTTLE,
        workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
        workflows=[],
        activities=[run_agent],
        activity_executor=activity_executor,
        max_concurrent_activities=research_slots,
      ),
    ]
    await run_until_signalled(*workers)


async def run_operations_worker():
  """Serve all five operations queues from one process.

  One process rather than five because the slot counts, not the process boundary, are
  what bounds the load: fourteen slots of mostly-waiting work do not need five
  interpreters, and one process means one place for the container's memory budget to
  apply. The queues stay separate so a store's work cannot starve another store's.

  `operations-admission-queue` carries `admit_operation` only, in one slot, so the caps
  of the `[operations]` section hold across the deployment.

  Each store queue carries that store's own backup and restore work and nothing else,
  which is what the split is for: a long object copy cannot take the single ClickHouse
  slot. That slot stays single because the server refuses concurrent backups and
  concurrent restores anyway, so a second slot would only queue inside ClickHouse where
  nothing here can see it.

  Every queue also carries the row writer, because the SDK refuses a worker with
  neither a workflow nor an activity, and because it is the one activity every store path
  needs.
  """
  from .P_ops.activities import (
      admit_operation, cancel_target_operation, count_dataset_rows_activity, record_operation_state,
      reindex_collection_activity, sample_dataset_progress, supervise_operations, tombstone_dataset_row,
  )
  from .P_ops.backup import (
      begin_export, export_clickhouse, export_manticore, export_object_store,
      finish_export,
  )
  from .P_ops.restore import (
      begin_import, finish_import, import_clickhouse, import_manticore,
      import_object_store,
  )
  from .P_ops.workflows import CancelOperation, Operation
  from .P_agent.supervise import supervise_agent_runs
  from .visibility import ensure_search_attributes
  log.info("Starting Operations worker...")
  client = await Client.connect("temporal:7233")
  attach_temporal_client(client)
  await ensure_search_attributes(client)

  orchestration = worker_concurrency(
      "operations", OPERATIONS_QUEUE_SLOTS["operations-queue"])
  with concurrent.futures.ThreadPoolExecutor(max_workers=orchestration) as executor:
    workers = [Worker(
      client,
      interceptors=[TaskTimingInterceptor(), OperationFailureInterceptor(), *guard_interceptors()],
      workflow_runner=sandboxed_runner(),
      task_queue="operations-queue",
      graceful_shutdown_timeout=graceful_shutdown_timeout(),
      workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
      workflows=[Operation, CancelOperation],
      activities=[cancel_target_operation, record_operation_state, sample_dataset_progress,
                  supervise_operations, reindex_collection_activity, count_dataset_rows_activity,
                  tombstone_dataset_row, begin_export, finish_export,
                  begin_import, finish_import, capture_operation_failure,
                  supervise_agent_runs],
      activity_executor=executor,
      max_concurrent_activities=orchestration,
    )]
    store_activities = {
      "operations-clickhouse-queue": [export_clickhouse, import_clickhouse],
      "operations-manticore-queue": [export_manticore, import_manticore],
      "operations-garage-queue": [export_object_store, import_object_store],
      "operations-admission-queue": [admit_operation],
    }
    for queue, slots in OPERATIONS_QUEUE_SLOTS.items():
      if queue == "operations-queue":
        continue
      workers.append(Worker(
        client,
        interceptors=[TaskTimingInterceptor(), *guard_interceptors()],
        workflow_runner=sandboxed_runner(),
        task_queue=queue,
        graceful_shutdown_timeout=graceful_shutdown_timeout(),
        workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
        workflows=[],
        activities=[record_operation_state, *store_activities[queue]],
        activity_executor=executor,
        max_concurrent_activities=slots,
      ))
    await run_until_signalled(*workers)

# Removed parallel run_worker. Each worker runs in its own process via main CLI.
