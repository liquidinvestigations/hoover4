import re
from pathlib import Path

from tasks.P3_parse_files.parse_mime import LOCAL_DETECTORS
from tasks.P_admin.stage_eligibility import KNOWN_TASK_NAMES
from tasks.text_sources import OCR_ENGINES


PROCESSING_ROOT = Path(__file__).parents[2]


def _source(relative_path: str) -> str:
    return (PROCESSING_ROOT / relative_path).read_text()


def test_known_task_names_match_the_current_error_writers():
    p3 = _source("tasks/P3_parse_files/workflows.py")
    p3_pdf = _source("tasks/P3_parse_files/parse_pdf.py")
    p2 = _source("tasks/P2_execute_plan/workflows.py")
    p4 = _source("tasks/P4_extract_entities/workflows.py")
    p5 = _source("tasks/P5_chunk_embed/workflows.py")
    p6 = _source("tasks/P6_index_data/workflows.py")

    writer_names = set(re.findall(r"task_ids\.append\(['\"]([^'\"]+)['\"]\)", p3))
    writer_names.update(re.findall(r"failed_task_ids\.append\(['\"]([^'\"]+)['\"]\)", p4))
    writer_names.update(re.findall(r"failed_task_ids\.append\(['\"]([^'\"]+)['\"]\)", p5))
    writer_names.update(re.findall(r'"(P6_Index[^\"]+)"', p6))
    writer_names.update(re.findall(r'"(P3_ParseSingleFile)"', p2))

    assert 'f"run_ocr_and_store[{engine}]"' in p3
    assert 'f"run_ocr_pdf_and_store[{engine}]"' in p3_pdf
    writer_names.update(f"run_ocr_and_store[{engine}]" for engine in OCR_ENGINES)
    writer_names.update(f"run_ocr_pdf_and_store[{engine}]" for engine in OCR_ENGINES)

    assert 'f"detector_error_{name}"' in p3
    writer_names.update(
        f"detector_error_{name}" for name in LOCAL_DETECTORS + ("tika",)
    )
    writer_names.add("detector_error_unknown")
    assert '"parse_error_tika"' in p3
    writer_names.add("parse_error_tika")

    assert writer_names == KNOWN_TASK_NAMES
