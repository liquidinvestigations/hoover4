"""Pipeline text readers select the latest version without FINAL."""

import re
from pathlib import Path

import pytest

TASKS = Path(__file__).resolve().parents[2] / "tasks"

#: These stages read text versions.
PIPELINE_READERS = [
    ("P4", TASKS / "P4_extract_entities" / "activities.py"),
    ("P5", TASKS / "P5_chunk_embed" / "activities.py"),
    ("P6", TASKS / "P6_index_data" / "activities.py"),
]

@pytest.mark.parametrize("stage,path", PIPELINE_READERS, ids=[s for s, _ in PIPELINE_READERS])
def test_stage_selects_latest_text_version(stage, path):
    source = path.read_text()
    assert "FROM text_content" in source
    assert not re.search(r"FROM text_content(?: AS \w+)? FINAL", source)
    assert "argMax(" in source
    assert "version)" in source
