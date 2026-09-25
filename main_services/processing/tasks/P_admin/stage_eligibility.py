"""Select Error rows whose failed stage is enabled for the dataset."""

import os

from tasks.dataset_config import easyocr_passes, tesseract_languages
from tasks.ocr_client import engine_configured
from tasks.ocr_pdf_client import engines_for_provider, service_configured


KNOWN_TASK_NAMES = frozenset(
    {
        "detector_error_file",
        "detector_error_magika",
        "detector_error_extension",
        "detector_error_content_sniff",
        "detector_error_tika",
        "parse_error_tika",
        "detector_error_unknown",
        "archive_scan",
        "email_scan",
        "extract_plaintext_chunks",
        "parse_office_xml_and_store",
        "parse_table_and_store",
        "pdf_process",
        "parse_image_metadata_and_store",
        "run_ocr_and_store[tesseract]",
        "run_ocr_and_store[easyocr]",
        "parse_audio_metadata_and_store",
        "video_process",
        "run_ocr_pdf_and_store[tesseract]",
        "run_ocr_pdf_and_store[easyocr]",
        "P4_ExtractEntities",
        "P4_ScanRegexEntities",
        "P5_ChunkEmbed",
        "P6_IndexTextPages",
        "P6_IndexVectors",
    }
)


def _ocr_has_languages(engine: str, collection_dataset: str) -> bool:
    if engine == "tesseract":
        return bool(tesseract_languages(collection_dataset).strip())
    if engine == "easyocr":
        return bool(easyocr_passes(collection_dataset))
    return False


def _task_engine(task_name: str, prefix: str) -> str:
    if not task_name.startswith(prefix) or not task_name.endswith("]"):
        return ""
    return task_name[len(prefix):-1]


def stage_is_off(task_name: str, collection_dataset: str) -> bool:
    """Return true only when configuration disables the stage that wrote `task_name`."""
    if task_name == "P4_ExtractEntities":
        return not (os.getenv("NER_URL") or "").strip()
    if task_name in ("P5_ChunkEmbed", "P6_IndexVectors"):
        return not (os.getenv("EMBEDDINGS_URL") or "").strip()

    engine = _task_engine(task_name, "run_ocr_and_store[")
    if engine in ("tesseract", "easyocr"):
        return not engine_configured(engine) or not _ocr_has_languages(
            engine, collection_dataset
        )

    engine = _task_engine(task_name, "run_ocr_pdf_and_store[")
    if engine in ("tesseract", "easyocr"):
        return (
            not service_configured()
            or engine not in engines_for_provider()
            or not _ocr_has_languages(engine, collection_dataset)
        )
    return False
