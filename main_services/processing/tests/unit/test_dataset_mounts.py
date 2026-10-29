"""Tests for the HOOVER4_DATASET_MOUNTS parser.

The cases are in ``tasks/dataset_mounts_cases.json``. The Rust copy of the parser in
``website/backend/src/dataset_mounts.rs`` reads the same file.
"""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from tasks import dataset_mounts
from tasks.dataset_mounts import DatasetMountsError, parse_dataset_mounts

_CASES = json.loads(
    (Path(dataset_mounts.__file__).parent / "dataset_mounts_cases.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", _CASES, ids=[case["id"] for case in _CASES])
def test_shared_case(case):
    if case.get("error"):
        with pytest.raises(DatasetMountsError):
            parse_dataset_mounts(case["value"], case["legacy_path"])
        return
    parsed = parse_dataset_mounts(case["value"], case["legacy_path"])
    assert [asdict(mount) for mount in parsed] == case["mounts"]


def test_the_environment_reader_uses_both_variables(monkeypatch):
    monkeypatch.delenv("HOOVER4_DATASET_MOUNTS", raising=False)
    monkeypatch.setenv("DATASETS_MOUNT_PATH", "/corpus")
    assert [m.path for m in dataset_mounts.dataset_mounts()] == ["/corpus"]
    monkeypatch.setenv(
        "HOOVER4_DATASET_MOUNTS", '[{"name":"uploads","path":"/uploads","writable":true}]')
    assert dataset_mounts.dataset_mounts() == [
        dataset_mounts.DatasetMount("uploads", "/uploads", True)]
