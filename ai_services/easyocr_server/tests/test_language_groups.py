"""The installed language groups, the worker's copy of them, and what /health reports.

Run with the repository root mounted, because the parity test reads the worker module.
`EASYOCR_TEST_MODEL_DIR` names a folder with the baked weights. Without it, the load
test is skipped.
"""

import ast
import os
from pathlib import Path

import pytest

from language_groups import (BAKED_READERS, INSTALLED_GROUPS, UNLOADABLE, installed_languages,
                             loadable_languages)

REPO_ROOT = Path(os.environ.get("REPO_ROOT") or Path(__file__).resolve().parents[3])
WORKER_MODULE = REPO_ROOT / "main_services" / "processing" / "tasks" / "automatic_ocr.py"


def _worker_groups() -> dict:
    """`EASY_SCRIPT_GROUPS` of the worker, read without importing the worker."""
    tree = ast.parse(WORKER_MODULE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(target, "id", "") == "EASY_SCRIPT_GROUPS" for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("EASY_SCRIPT_GROUPS is not in %s" % WORKER_MODULE)


def test_the_worker_plans_with_the_installed_groups():
    assert {**_worker_groups(), "HanT": ("ch_tra",)} == INSTALLED_GROUPS


def test_a_code_belongs_to_one_group_and_every_group_is_baked():
    codes = [code for group in INSTALLED_GROUPS.values() for code in group]
    assert len(codes) == len(set(codes)) == len(installed_languages())
    baked = {code for languages in BAKED_READERS for code in languages}
    assert baked == set(loadable_languages()) == set(codes) - UNLOADABLE


def test_the_package_reads_every_installed_code():
    from easyocr.config import all_lang_list

    assert set(installed_languages()) <= set(all_lang_list)


def test_health_reports_the_installed_groups(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    del fastapi
    monkeypatch.setenv("EASYOCR_BAKED_DIR", "")
    import easyocr_server

    monkeypatch.setattr(easyocr_server, "_use_gpu", lambda: False)
    health = easyocr_server.health()
    assert health["status"] == "healthy"
    assert health["languages_supported"] == installed_languages()
    assert health["languages_available"] == loadable_languages()


def test_a_request_for_a_code_without_models_is_refused(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import HTTPException

    import easyocr_server

    for languages in ("sa", "hi+sa", "xx"):
        request = easyocr_server.OcrRequest(image_b64="AA==", languages=languages)
        with pytest.raises(HTTPException) as refused:
            easyocr_server.ocr(request, None)
        assert refused.value.status_code == 400


def test_a_code_without_a_character_file_is_unloadable():
    import easyocr

    folder = Path(easyocr.__file__).parent / "character"
    missing = {code for code in installed_languages() if not (folder / f"{code}_char.txt").exists()}
    assert missing == UNLOADABLE - {"ta"}


@pytest.mark.skipif(not os.environ.get("EASYOCR_TEST_MODEL_DIR"),
                    reason="EASYOCR_TEST_MODEL_DIR names no folder with baked weights")
@pytest.mark.parametrize("languages", [("en",), ("de",), ("ru",), ("rs_cyrillic",), ("ar",),
                                       ("hi",), ("ch_tra",), ("ja",), ("th",)] + list(BAKED_READERS))
def test_an_available_request_loads_without_a_download(languages):
    import easyocr

    folder = os.environ["EASYOCR_TEST_MODEL_DIR"]
    easyocr.Reader(list(languages), gpu=False, model_storage_directory=folder,
                   user_network_directory=folder, download_enabled=False, verbose=False)


@pytest.mark.skipif(not os.environ.get("EASYOCR_TEST_MODEL_DIR"),
                    reason="EASYOCR_TEST_MODEL_DIR names no folder with baked weights")
@pytest.mark.parametrize("code", sorted(UNLOADABLE))
def test_an_unloadable_code_does_not_load(code):
    import easyocr

    folder = os.environ["EASYOCR_TEST_MODEL_DIR"]
    with pytest.raises((FileNotFoundError, RuntimeError)):
        easyocr.Reader([code], gpu=False, model_storage_directory=folder,
                       user_network_directory=folder, download_enabled=True, verbose=False)
