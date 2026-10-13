"""Process stored PDF source ranges with bounded activity and workflow histories."""

import dataclasses
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from tasks.heartbeat import HEARTBEAT_TIMEOUT
from tasks.failure_chain import is_cancellation, exception_chain
from tasks.P3_parse_files.batch_runner import (
    FileResult, StageBatchParams, COMMON_QUEUE, OCR_PDF_QUEUE,
    stage_failure_results, stage_timeout_seconds,
)

PDF_CURSOR_PATCH = "pdf-part-cursor-v1"
PDF_PART_WINDOW = 100
PDF_HISTORY_EVENTS = 2000
PDF_HISTORY_BYTES = 4 * 1024 * 1024


def is_pdf_identity_change(exc: BaseException) -> bool:
    """Keep source and setting changes out of per-document error completion."""
    return any(getattr(cause, "type", "") in ("PdfSourceChanged", "PdfSettingsChanged")
               for cause in exception_chain(exc))


@dataclass
class PdfSource:
    item_hash: str
    file_path: str
    file_size_bytes: int
    source_kind: str
    segmentation: int
    source_digest: str
    part_count: int
    page_count: int
    languages: list[str] = field(default_factory=list)
    settings_version_us: int = 0
    settings_version_precise: bool = False


@dataclass
class PdfPartCursorParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    op_id: str
    engine: str
    source: PdfSource
    after: int = 0


@dataclass
class PdfPartProgress:
    after: int = 0
    completed: int = 0
    done: bool = False
    result: FileResult | None = None


@dataclass
class FrozenPdfStageParams(StageBatchParams):
    languages: list[str] = field(default_factory=list)


@dataclass
class PdfPartGroupParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    op_id: str
    engine: str
    sources: list[PdfSource] = field(default_factory=list)
    source_index: int = 0
    after: int = 0
    completed: int = 0
    results: list[FileResult] = field(default_factory=list)
    history_events: int = PDF_HISTORY_EVENTS
    history_bytes: int = PDF_HISTORY_BYTES


@workflow.defn
class PdfPartGroup:
    """Process one engine with stable source identities and language settings."""

    @workflow.run
    async def run(self, params: PdfPartGroupParams) -> list[FileResult]:
        while params.source_index < len(params.sources):
            source = params.sources[params.source_index]
            try:
                progress = await workflow.execute_activity(
                    "run_ocr_pdf_part_cursor",
                    PdfPartCursorParams(params.collectionname, params.collection_dataset,
                                        params.plan_hash, params.op_id, params.engine,
                                        source, params.after),
                    result_type=PdfPartProgress,
                    start_to_close_timeout=timedelta(seconds=stage_timeout_seconds(
                        "run_ocr_pdf_parts_batch", [source.file_size_bytes] * min(
                            PDF_PART_WINDOW, max(1, source.part_count - params.after)))),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=0),
                    task_queue=OCR_PDF_QUEUE,
                )
            except ActivityError as exc:
                if is_cancellation(exc) or is_pdf_identity_change(exc):
                    raise
                progress = PdfPartProgress(done=True, result=stage_failure_results(
                    "run_ocr_pdf_parts_batch", [source.item_hash], exc)[0])
            params = dataclasses.replace(params, after=progress.after,
                                         completed=params.completed + progress.completed)
            if progress.done or progress.result is not None:
                result = progress.result
                if result is None:
                    try:
                        result = await workflow.execute_activity(
                            "pdf_ocr_finalize_cursor",
                            PdfPartCursorParams(params.collectionname, params.collection_dataset,
                                                params.plan_hash, params.op_id, params.engine,
                                                source, params.after),
                            result_type=FileResult,
                            start_to_close_timeout=timedelta(seconds=stage_timeout_seconds(
                                "pdf_ocr_finalize_batch", [source.file_size_bytes])),
                            heartbeat_timeout=HEARTBEAT_TIMEOUT,
                            retry_policy=RetryPolicy(maximum_attempts=0),
                            task_queue=COMMON_QUEUE,
                        )
                    except ActivityError as exc:
                        if is_cancellation(exc) or is_pdf_identity_change(exc):
                            raise
                        result = stage_failure_results(
                            "pdf_ocr_finalize_batch", [source.item_hash], exc)[0]
                params = dataclasses.replace(params, source_index=params.source_index + 1,
                                             after=0, results=[*params.results, result])
            info = workflow.info()
            if params.source_index < len(params.sources) and (
                info.is_continue_as_new_suggested()
                or info.get_current_history_length() >= params.history_events
                or info.get_current_history_size() >= params.history_bytes
            ):
                workflow.continue_as_new(params)
        return params.results
