"""Canonical stage identities, their output versions, and the names of their stored errors.

A stage version names the contract of the output that a stage stores. A change that
makes a stage store different output for the same input raises its version in the same
commit, and adds or updates the processing update step that brings existing datasets to
the new output (`.agents/rules/processing-versions.md`).

Some stages already carry a storage marker that their own writer compares, such as the
table reader version or the PDF segmentation version. Those markers stay where they are,
because stored rows and workflow inputs use them. `STAGE_VERSIONS` reads them, so this
file names every version in one place without moving a stored identity.

`processing_errors.task_name` holds several names for one stage: earlier activity names,
detector names, and names with an engine in brackets. `canonical_stage` maps each of them
to one stage identity. The retry entitlement of failed files is keyed by that identity
and its version.
"""

from typing import Dict, Optional

from tasks.P4_extract_entities.completion import NER_STAGE_VERSION
from tasks.P3_parse_files.ocr_detection import OCR_DETECTION_VERSION
from tasks.P3_parse_files.scan_virus import SCAN_VERSION
from tasks.P3_parse_files.table_formats import READER_VERSION
from tasks.text_sources import OCR_PAGE_RULE_VERSION, PDF_SEGMENTATION_VERSION, PDF_TEXT_LAYER_VERSION

#: The output version of the folder count values that `build_vfs_nodes` writes.
VFS_SUBTREE_STATS_VERSION = 1

#: Each canonical stage and the version of the output it stores.
STAGE_VERSIONS: Dict[str, int] = {
    "detect": 2,
    "virus_scan": SCAN_VERSION,
    "archive": 3,
    "email": 1,
    "plaintext": 1,
    "tika": 1,
    "office_xml": 1,
    "table": READER_VERSION,
    "pdf": PDF_SEGMENTATION_VERSION,
    "pdf_preview": 1,
    "image_preview": 2,
    "image_pdf": 2,
    "image_metadata": 1,
    "ocr_image": 2,
    "ocr_pdf": 2,
    "ocr_detection": OCR_DETECTION_VERSION,
    "ocr_plan": 1,
    "pdf_text_layer": PDF_TEXT_LAYER_VERSION,
    "audio": 1,
    "video": 1,
    "entities": NER_STAGE_VERSION,
    "regex": 1,
    "embed": 1,
    "index_text": 3,
    "index_vectors": 2,
    "index_terms": 3,
    "vfs_stats": VFS_SUBTREE_STATS_VERSION,
}

#: Stored error names without an engine, and their stage.
_ERROR_STAGES: Dict[str, str] = {
    "automatic_ocr": "ocr_plan",
    "automatic_ocr_batch": "ocr_plan",
    "run_automatic_ocr_files": "ocr_plan",
    "verify_automatic_ocr_files": "ocr_plan",
    "verify_ingested_automatic_ocr": "ocr_plan",
    "detect_ocr_text": "ocr_detection",
    "detector_error_file": "detect",
    "detector_error_magika": "detect",
    "detector_error_extension": "detect",
    "detector_error_content_sniff": "detect",
    "detector_error_unknown": "detect",
    "detector_error_tika": "tika",
    "parse_error_tika": "tika",
    "tika_text_batch": "tika",
    "archive_scan": "archive",
    "email_scan": "email",
    "extract_plaintext_chunks": "plaintext",
    "parse_office_xml_and_store": "office_xml",
    "parse_table_and_store": "table",
    "pdf_process": "pdf",
    "make_pdf_preview": "pdf_preview",
    "make_image_preview": "image_preview",
    "parse_image_metadata_and_store": "image_metadata",
    "parse_audio_metadata_and_store": "audio",
    "video_process": "video",
    "P4_ExtractEntities": "entities",
    "P4_ScanRegexEntities": "regex",
    "P5_ChunkEmbed": "embed",
    "P6_IndexTextPages": "index_text",
    "P6_IndexVectors": "index_vectors",
}

#: Stored error name prefixes that carry an OCR engine in brackets, and their stage.
_ENGINE_ERROR_STAGES = (
    ("run_ocr_and_store[", "ocr_image"),
    ("run_ocr_pdf_and_store[", "ocr_pdf"),
    ("make_image_pdf[", "image_pdf"),
)


def canonical_stage(task_name: str) -> Optional[str]:
    """The stage identity of a stored error name, or None for an unknown name."""
    if task_name in _ERROR_STAGES:
        return _ERROR_STAGES[task_name]
    for prefix, stage in _ENGINE_ERROR_STAGES:
        if (task_name.startswith(prefix) and task_name.endswith("]")
                and len(task_name) > len(prefix) + 1):
            return stage
    return None


def register_stage_versions() -> int:
    """Insert each `(stage, version)` pair of the code that the table lacks.

    A stage without any row gets `baseline = 1`. Returns the number of inserted rows. A
    pair that exists keeps its first time, so a restart without a version change writes
    nothing.
    """
    from datetime import datetime, timezone

    from database.clickhouse import get_global_client, insert_durable

    with get_global_client() as client:
        known = {(stage, int(version)) for stage, version in client.query(
            "SELECT stage, version FROM stage_versions FINAL").result_rows}
        stages_with_rows = {stage for stage, _ in known}
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        rows = [[stage, version, 0 if stage in stages_with_rows else 1, now]
                for stage, version in sorted(STAGE_VERSIONS.items())
                if (stage, version) not in known]
        if rows:
            insert_durable(client, "stage_versions", rows,
                           column_names=["stage", "version", "baseline", "first_seen_at"])
    return len(rows)
