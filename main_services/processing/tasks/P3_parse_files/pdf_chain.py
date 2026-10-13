"""Run PDF preparation, bounded part lists, and variant completion for one group."""

import asyncio
import dataclasses

from tasks.P3_parse_files.batch_runner import FileResult
from tasks.text_sources import OCR_ENGINES


def part_lists(items, limit: int):
    """Distribute source parts over a bounded number of sequential activity lists."""
    count = min(max(1, limit), len(items))
    return [items[index::count] for index in range(count)] if count else []


async def run_pdf_chain(files, run_stage, engines=None):
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
    for file, result in zip(sources, await run_stage("pdf_prepare_batch", sources)):
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
