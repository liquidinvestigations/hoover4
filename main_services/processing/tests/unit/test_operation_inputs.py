"""Operation re-runs retain only the inputs that affect the next execution."""

import pytest

from database.operation_inputs import MissingOperationInput, project_inputs


def test_registry_path_replaces_stored_dataset_detail(monkeypatch):
    monkeypatch.setattr(
        "database.operation_inputs.registry_dataset_path", lambda _: "/new"
    )
    assert project_inputs(
        "add_dataset", "collection", "collection_dataset",
        '{"dataset_path":"/old","dataset_name":"x","failed_documents":3}',
    ) == {"dataset_path": "/new"}


def test_registry_path_survives_invalid_stored_json(monkeypatch):
    monkeypatch.setattr(
        "database.operation_inputs.registry_dataset_path", lambda _: "/new"
    )
    assert project_inputs("add_dataset", "collection", "collection_dataset", "not json") == {
        "dataset_path": "/new"
    }


def test_language_re_run_discards_progress_fields():
    assert project_inputs(
        "change_ocr_languages", "collection", "collection_dataset",
        '{"tesseract_languages":"eng","added":["x"],"stage":"done"}',
    ) == {"tesseract_languages": "eng"}


def test_retry_requires_a_selector_key():
    with pytest.raises(MissingOperationInput, match="task_name or hash"):
        project_inputs(
            "retry_failed_files", "collection", "collection_dataset",
            '{"task_name":"","hash":""}',
        )


def test_optional_export_destination_can_be_absent():
    assert project_inputs(
        "export_collection", "collection", "",
        '{"stores":{},"phase":"x"}',
    ) == {}
