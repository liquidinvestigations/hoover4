"""Run PDF preparation, resumable part processing, and variant completion for one group."""

import asyncio
import dataclasses

from tasks.P3_parse_files.batch_runner import FileResult
from tasks.text_sources import OCR_ENGINES


def part_lists(items, limit: int):
    """Distribute source parts over a bounded number of sequential activity lists."""
    count = min(max(1, limit), len(items))
    return [items[index::count] for index in range(count)] if count else []


async def run_pdf_chain(files, run_stage, engines=None, *, cursor_context=None):
    """Return preparation and variant outcomes without moving text through workflows."""
    preparation = {}
    variants = {}
    originals = [file for file in files if file.source_kind == "original"]
    office = [file for file in files if file.source_kind == "preview"]
    sources = []
    for kind, stage, chosen in (("original", "pdf_metadata_batch", originals),
                                ("preview", "make_pdf_preview_batch", office)):
        for file, result in zip(chosen, await run_stage(stage, chosen)):
            preparation[file.item_hash] = result
            value = result.value if isinstance(result.value, dict) else {}
            if result.status != "ok" or value.get("defect"):
                continue
            sources.append(dataclasses.replace(file, page_count=int(value.get("page_count", 0)),
                           pdf_size_bytes=int(value.get("size_bytes", 0))))
    prepared = []
    jobs = []
    list_limit = 4
    available = {}
    prepare_stage = "pdf_prepare_compact_batch" if cursor_context else "pdf_prepare_batch"
    for file, result in zip(sources, await run_stage(prepare_stage, sources)):
        preparation[file.item_hash] = result
        if result.status != "ok":
            continue
        prepared.append(file)
        available[file.item_hash] = result.value or {}
        list_limit = int((result.value or {}).get("part_lists", 4))
        for part in (result.value or {}).get("parts", []):
            jobs.append(dataclasses.replace(file, **part))

    async def variant(engine):
        chosen = [file for file in prepared
                  if (engines is None or engine in engines.get(file.item_hash, []))
                  and (available[file.item_hash].get("has_ocr_pages")
                       or engine in available[file.item_hash].get("saved_engines", []))]
        if not chosen:
            return
        if cursor_context:
            from temporalio import workflow
            from temporalio.exceptions import ChildWorkflowError
            from tasks.P3_parse_files.batch_runner import stage_failure_results
            from tasks.failure_chain import is_cancellation
            from tasks.P3_parse_files.pdf_cursor import (
                PdfPartGroup, PdfPartGroupParams, PdfSource, is_pdf_identity_change,
            )
            compact = [PdfSource(file.item_hash, file.file_path,
                                 max(file.file_size_bytes, file.pdf_size_bytes),
                                 file.source_kind, available[file.item_hash]["segmentation"],
                                 available[file.item_hash]["source_digest"],
                                 available[file.item_hash]["part_count"],
                                 available[file.item_hash]["page_count"],
                                 available[file.item_hash]["languages"].get(engine, []),
                                 available[file.item_hash]["settings_versions"][engine]["version_us"],
                                 available[file.item_hash]["settings_versions"][engine]["is_precise"])
                       for file in chosen]
            try:
                groups = part_lists(compact, min(4, list_limit))
                completed = await asyncio.gather(*[
                    workflow.execute_child_workflow(
                        PdfPartGroup.run,
                        PdfPartGroupParams(cursor_context.collectionname, cursor_context.collection_dataset,
                                           cursor_context.plan_hash, cursor_context.op_id, engine, group),
                        id=f"pdf-cursor-{workflow.info().workflow_id}-{group[0].item_hash}-{engine}")
                    for group in groups], return_exceptions=True)
                results = []
                for group, outcome in zip(groups, completed):
                    if isinstance(outcome, ChildWorkflowError):
                        if is_cancellation(outcome) or is_pdf_identity_change(outcome):
                            raise outcome
                        results.extend(stage_failure_results("run_ocr_pdf_parts_batch",
                                       [source.item_hash for source in group], outcome))
                    elif isinstance(outcome, BaseException):
                        raise outcome
                    else:
                        results.extend(outcome)
            except ChildWorkflowError as exc:
                if is_cancellation(exc) or is_pdf_identity_change(exc):
                    raise
                results = stage_failure_results("run_ocr_pdf_parts_batch",
                                                [file.item_hash for file in chosen], exc)
            for result in results:
                variants[result.item_hash, engine] = result
            return
        selected = [part for part in jobs if any(file.item_hash == part.item_hash for file in chosen)]
        batches = part_lists(selected, list_limit)
        results = await asyncio.gather(*[run_stage("run_ocr_pdf_parts_batch", batch, engine)
                                        for batch in batches])
        failed = {}
        for batch in results:
            for result in batch:
                if result.status == "failed":
                    failed.setdefault(result.item_hash, result)
        final = [file for file in chosen if file.item_hash not in failed]
        for file, result in zip(final, await run_stage("pdf_ocr_finalize_batch", final, engine)):
            variants[file.item_hash, engine] = result
        for file_hash, result in failed.items():
            variants[file_hash, engine] = result

    await asyncio.gather(*[variant(engine) for engine in OCR_ENGINES])
    return preparation, variants
