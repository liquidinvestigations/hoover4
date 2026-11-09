"""The effective OCR languages, from the case file the website tests read too."""

import json
from pathlib import Path

import pytest

from tasks import dataset_config
from tasks.dataset_config import OCR_KEYS, SettingRow, resolve_ocr_languages

_FILE = json.loads(
    (Path(__file__).resolve().parents[2] / "tasks" / "ocr_resolution_cases.json").read_text())


def _rows(spec: dict, index: int) -> dict:
    return {OCR_KEYS[engine][index]: SettingRow(value, deleted, version, True)
            for engine, (value, deleted, version) in spec.items()}


@pytest.mark.parametrize("case", _FILE["cases"], ids=[c["name"] for c in _FILE["cases"]])
def test_resolution_matches_the_shared_case(case):
    resolved = resolve_ocr_languages(_rows(case["dataset"], 0), _rows(case["collection"], 1),
                                     _FILE["installation"])
    for engine, (value, source, version) in case["expected"].items():
        assert (resolved[engine].value, resolved[engine].source,
                resolved[engine].version_us) == (value, source, version), engine


def test_worker_settings_read_the_collection_default(monkeypatch):
    """`get_dataset_settings` and the OCR passes use the resolved value."""
    stored = {
        "c_ds": {},
        "c": {"ocr.default.tesseract.languages": SettingRow("ron", False, 5, True),
              "ocr.default.easyocr.languages": SettingRow("", False, 5, True)},
    }

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("database.clickhouse.get_global_client", lambda: Client())
    monkeypatch.setattr(dataset_config, "_latest_rows",
                        lambda _client, key, keys=(): {k: v for k, v in stored[key].items()
                                                       if not keys or k in keys})
    monkeypatch.setattr(dataset_config, "collection_of_dataset", lambda cd: "c" if cd == "c_ds" else "")
    dataset_config.invalidate()
    try:
        assert dataset_config.tesseract_languages("c_ds") == "ron"
        assert dataset_config.easyocr_passes("c_ds") == []
    finally:
        dataset_config.invalidate()


def test_the_target_ledger_uses_the_same_resolution(monkeypatch):
    from tasks import ocr_targets

    rows = {
        "c_ds": {"ocr.tesseract.languages": SettingRow("fra", True, 90, True)},
        "c": {"ocr.default.tesseract.languages": SettingRow("ron", False, 50, True)},
    }
    monkeypatch.setattr(dataset_config, "latest_setting_rows",
                        lambda key, keys: {k: v for k, v in rows.get(key, {}).items() if k in keys})
    monkeypatch.setattr(dataset_config, "collection_of_dataset", lambda cd: "c")
    settings = ocr_targets.language_settings("c_ds")
    assert settings["tesseract"].value == "ron"
    assert settings["tesseract"].version == ocr_targets.SettingVersion(90, True)
    assert settings["easyocr"].value == dataset_config.DEFAULTS["ocr.easyocr.languages"]


def test_the_installation_defaults_are_fixed(monkeypatch):
    """No setting renders them, so an earlier environment value changes nothing."""
    import importlib.util

    monkeypatch.setenv("TESSERACT_LANGUAGES", "fra")
    monkeypatch.setenv("EASYOCR_LANGUAGES", "ru")
    spec = importlib.util.spec_from_file_location("dataset_config_copy", dataset_config.__file__)
    copy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(copy)
    assert copy.installation_ocr_defaults() == {"tesseract": "eng", "easyocr": "en"}
