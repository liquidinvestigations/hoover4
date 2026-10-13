"""Create image PDF previews from stored OCR words without another OCR request."""

import base64
import dataclasses
import json
import re

from temporalio import activity

from tasks.heartbeat import with_heartbeat
from tasks.P3_parse_files.batch_runner import StageBatchParams, BatchResult, run_batch
from tasks.task_timing import SkippedOutcome
from tasks.text_sources import MIN_OCR_IMAGE_PX


def qualifying_words(text: str) -> int:
    """Count stored OCR words with at least two letters or digits."""
    return len(re.findall(r"[^\W_]{2,}", text, re.UNICODE))


def make_image_pdf(params: StageBatchParams, file):
    from database.clickhouse import get_collection_client
    from tasks.ocr_pdf_client import build_ocr_pdf, service_configured
    from tasks.P3_parse_files.parse_ocr_pdf import _passes_for
    from tasks.P3_parse_files.pdf_parts import live_hashes, store_part, write_row, variant_result
    from tasks.P3_parse_files.image_preview import read_preview_bytes
    from tasks.P3_parse_files.image_loader import image_dimensions
    from tasks.ocr_targets import record_ocr_skips
    if not service_configured():
        return SkippedOutcome("pdf_builder_disabled")
    with get_collection_client(params.collectionname) as client:
        if file.item_hash not in live_hashes(client, params.collection_dataset, [file.item_hash]):
            return SkippedOutcome("pdf_source_removed")
        rows = client.query(
            "SELECT languages, raw_json FROM raw_ocr_results FINAL "
            "WHERE collection_dataset = {cd:String} AND image_hash = {h:String} "
            "AND engine = {en:String}", parameters={"cd": params.collection_dataset,
                                                   "h": file.item_hash, "en": params.engine},
        ).result_rows
        raw = {languages: json.loads(payload) for languages, payload in rows}
        image = None
        incomplete = False
        for languages in _passes_for(params.engine, params.collection_dataset):
            result = variant_result(client, params.collection_dataset, file.item_hash, params.engine, languages)
            if result and result["source_kind"] == "image" and result["text_complete"]:
                continue
            payload = raw.get(languages)
            if payload is None:
                skips = client.query(
                    "SELECT reason FROM ocr_skips WHERE collection_dataset = {cd:String} "
                    "AND file_hash = {h:String} AND stage = 'image' AND engine = {en:String} "
                    "AND languages = {la:String}", parameters={"cd": params.collection_dataset,
                    "h": file.item_hash, "en": params.engine, "la": languages}).result_rows
                if skips:
                    record_ocr_skips(client, params.collection_dataset, file.item_hash,
                                     "image_pdf", params.engine, [languages], "image_ocr_skipped", params.op_id)
                    continue
                incomplete = True
                continue
            if qualifying_words(payload.get("text", "")) < 5:
                record_ocr_skips(client, params.collection_dataset, file.item_hash,
                                 "image_pdf", params.engine, [languages], "image_pdf_too_few_words", params.op_id)
                continue
            if image is None:
                image = read_preview_bytes(client, params.collection_dataset, file.item_hash)
                if image is None:
                    with open(file.file_path, "rb") as handle:
                        image = handle.read()
            dimensions = image_dimensions(image)
            if dimensions and min(dimensions) < MIN_OCR_IMAGE_PX:
                record_ocr_skips(client, params.collection_dataset, file.item_hash,
                                 "image_pdf", params.engine, [languages], "image_pdf_too_small", params.op_id)
                continue
            words = payload.get("words")
            if not isinstance(words, list):
                raise RuntimeError("Image PDF requires stored OCR word boxes")
            outcome = build_ocr_pdf(collectionname=params.collectionname,
                collection_dataset=params.collection_dataset, pdf_hash=file.item_hash,
                engine=params.engine, languages=languages, mode="image", words=words,
                source_b64=base64.b64encode(image).decode("ascii"))
            part = dataclasses.replace(file, source_kind="image", part_index=1, first_page=1, last_page=1)
            store_part(client, params, part, languages, key=outcome.dest_key, size=outcome.size_bytes, pages=[])
            write_row(client, "pdf_ocr_results", dict(collection_dataset=params.collection_dataset,
                      pdf_hash=file.item_hash, engine=params.engine, languages=languages,
                      source_kind="image", form="overlay", blob_key=outcome.dest_key,
                      blob_hash=outcome.blob_hash, page_count=1, size_bytes=outcome.size_bytes,
                      run_time_ms=outcome.run_time_ms, part_count=1, text_complete=1))
    if incomplete:
        return SkippedOutcome("image_ocr_incomplete")
    return "image_pdf_complete"


@activity.defn
@with_heartbeat
def make_image_pdf_batch(params: StageBatchParams) -> BatchResult:
    """Create the image PDF variants that have stored OCR word boxes."""
    return run_batch("make_image_pdf_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=lambda f: make_image_pdf(params, f),
                     task_name="make_image_pdf")
