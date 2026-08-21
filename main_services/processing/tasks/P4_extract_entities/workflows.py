"""NLP stage workflow: extract entities for every text segment of a plan.

Runs entirely before indexing (``IndexDatasetPlan``): the indexing stage reads
the ``entity_hit`` rows and ``nlp_processed`` watermarks this stage writes.
"""

import logging
from asyncio import gather
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

log = logging.getLogger(__name__)


with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.plan_utils import FetchPlanHashesParams, fetch_plan_hashes
    from tasks.P3_parse_files.parse_common import record_errors_from_results
    from .activities import extract_entities_for_hashes
    from .params import (
        ExtractEntitiesForPlanParams,
        ExtractEntitiesParams,
        ScanRegexEntitiesForPlanParams,
        ScanRegexEntitiesParams,
    )
    from .scan_regex_entities import REGEX_TASK_QUEUE, scan_regex_entities_for_hashes

NLP_TASK_QUEUE = "processing-nlp-queue"


@dataclass
class ScheduledChunk:
    """One scheduled NER chunk: hashes, start time and future kept together so
    results never rely on positional alignment across parallel lists."""

    hashes: list[str]
    started: datetime
    future: Any


@workflow.defn
class ExtractEntitiesForPlan:
    """Extract named entities for all text content of one processing plan."""
    @workflow.run
    async def run(self, params: ExtractEntitiesForPlanParams) -> str:
        NLP_CHUNK_SIZE = 100
        NLP_TIMEOUT = timedelta(minutes=30)

        plan_hashes = await workflow.execute_activity(
            fetch_plan_hashes,
            FetchPlanHashesParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        chunks: list[ScheduledChunk] = []
        for chunk_start in range(0, len(plan_hashes), NLP_CHUNK_SIZE):
            chunk_hashes = plan_hashes[chunk_start:chunk_start+NLP_CHUNK_SIZE]
            chunks.append(ScheduledChunk(
                hashes=chunk_hashes,
                started=workflow.now(),
                future=workflow.execute_activity(
                    extract_entities_for_hashes,
                    ExtractEntitiesParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, hashes=chunk_hashes),
                    start_to_close_timeout=NLP_TIMEOUT,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                    task_queue=NLP_TASK_QUEUE,
                ),
            ))
        results = await gather(*[c.future for c in chunks], return_exceptions=True)

        # A failed chunk (retries already exhausted by the activity) becomes one
        # processing_errors row per hash in the chunk, so every document that
        # missed entity extraction is individually visible as a failure.
        failed_results = []
        failed_task_ids = []
        failed_starts = []
        failed_hashes = []
        for res, chunk in zip(results, chunks):
            if isinstance(res, Exception):
                for item_hash in chunk.hashes:
                    failed_results.append(res)
                    failed_task_ids.append("P4_ExtractEntities")
                    failed_starts.append(chunk.started)
                    failed_hashes.append(item_hash)
        await record_errors_from_results(
            failed_results,
            task_ids=failed_task_ids,
            starts=failed_starts,
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            item_hashes=failed_hashes,
        )

        log.info(f"[P4] Done: entity extraction for plan {params.collection_dataset} {params.plan_hash}")
        return f"extracted entities for {params.plan_hash}"


@workflow.defn
class ScanRegexEntitiesForPlan:
    """Scan every text segment of one processing plan for regex entities.

    A sibling of `ExtractEntitiesForPlan`, not a successor: it writes tables no other
    stage touches, so the two run concurrently and neither waits on the other.
    """

    @workflow.run
    async def run(self, params: ScanRegexEntitiesForPlanParams) -> str:
        SCAN_CHUNK_SIZE = 100
        SCAN_TIMEOUT = timedelta(minutes=30)

        plan_hashes = await workflow.execute_activity(
            fetch_plan_hashes,
            FetchPlanHashesParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                plan_hash=params.plan_hash,
            ),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        chunks: list[ScheduledChunk] = []
        for chunk_start in range(0, len(plan_hashes), SCAN_CHUNK_SIZE):
            chunk_hashes = plan_hashes[chunk_start:chunk_start + SCAN_CHUNK_SIZE]
            chunks.append(ScheduledChunk(
                hashes=chunk_hashes,
                started=workflow.now(),
                future=workflow.execute_activity(
                    scan_regex_entities_for_hashes,
                    ScanRegexEntitiesParams(
                        collectionname=params.collectionname,
                        collection_dataset=params.collection_dataset,
                        plan_hash=params.plan_hash,
                        hashes=chunk_hashes,
                    ),
                    start_to_close_timeout=SCAN_TIMEOUT,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                    task_queue=REGEX_TASK_QUEUE,
                ),
            ))
        results = await gather(*[c.future for c in chunks], return_exceptions=True)

        failed_results = []
        failed_task_ids = []
        failed_starts = []
        failed_hashes = []
        for res, chunk in zip(results, chunks):
            if isinstance(res, Exception):
                for item_hash in chunk.hashes:
                    failed_results.append(res)
                    failed_task_ids.append("P4_ScanRegexEntities")
                    failed_starts.append(chunk.started)
                    failed_hashes.append(item_hash)
        await record_errors_from_results(
            failed_results,
            task_ids=failed_task_ids,
            starts=failed_starts,
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            item_hashes=failed_hashes,
        )

        log.info(f"[P4] Done: regex entity scan for plan {params.collection_dataset} {params.plan_hash}")
        return f"scanned regex entities for {params.plan_hash}"
