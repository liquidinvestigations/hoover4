"""Render tests for the deployment configuration."""

import importlib.util
import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest


REPO_ROOT = Path(os.environ.get("REPO_ROOT", "/repo"))
FIXTURES = Path(__file__).parent / "fixtures"


def _load_deploy():
    spec = importlib.util.spec_from_file_location("deploy_under_test", REPO_ROOT / "deploy.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


deploy = _load_deploy()


def _render(fixture_name):
    cfg = deploy.Config(FIXTURES / fixture_name)
    writes = []

    def record_write(path, content):
        writes.append((path, content))
        return True

    with (
        mock.patch.object(
            deploy.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0),
        ),
        mock.patch.object(deploy.shutil, "which", return_value="docker"),
        mock.patch.object(deploy, "_write_if_changed", side_effect=record_write),
        mock.patch.object(deploy, "port_is_free", return_value=True),
        mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host),
    ):
        env = deploy.render_main_env(cfg)
        deploy.write_env_file(Path("/rendered/main.env"), env)

    return env, writes


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        pytest.param(
            "gpu-on.ini",
            {
                "NER_URL": "http://127.0.0.1:21961/v1",
                "NER_URL_FALLBACK": "http://hoover4-ner-spacy:8000/v1",
                "EMBEDDINGS_URL": "http://127.0.0.1:21961/v1",
                "RERANK_URL": "http://127.0.0.1:21961/v1",
                "OCR_EASYOCR_URL": "http://127.0.0.1:21962/ocr",
            },
            id="gpu-on",
        ),
        pytest.param(
            "gpu-off-leftovers.ini",
            {
                "NER_URL": "",
                "NER_URL_FALLBACK": "",
                "EMBEDDINGS_URL": "",
                "RERANK_URL": "",
                "OCR_EASYOCR_URL": "",
            },
            id="gpu-off-leftovers",
        ),
        pytest.param(
            "ner-none.ini",
            {"NER_URL": "", "NER_PROVIDER": "none"},
            id="ner-none",
        ),
        pytest.param(
            "ner-spacy.ini",
            {"NER_URL": "http://hoover4-ner-spacy:8000/v1"},
            id="ner-spacy",
        ),
        pytest.param(
            "llm-selfhosted.ini",
            {
                "LLM_BASE_URL": "",
                "LLM_MODEL": "",
                "LLM_PROVIDER_NAME": "",
            },
            id="llm-selfhosted",
        ),
        pytest.param(
            "llm-cloud.ini",
            {"LLM_BASE_URL": "https://api.example.test/v1"},
            id="llm-cloud",
        ),
    ],
)
def test_render_matches_fixture(fixture_name, expected):
    env, writes = _render(fixture_name)

    for key, value in expected.items():
        assert env[key] == value
    assert writes
    assert writes[0][0] == Path("/rendered/main.env")
    assert "NER_URL=" in writes[0][1]


def _config(fixture_name):
    return deploy.Config(FIXTURES / fixture_name)


def test_gpu_ner_requires_ai_tier():
    with mock.patch.object(deploy, "fail") as fail:
        deploy.preflight_ner_gpu_without_tier(_config("gpu-off-leftovers.ini"), "main")

    fail.assert_called_once()
    assert "ner_provider = none" in fail.call_args.args[0]
    assert "[ai_services] enabled = true" in fail.call_args.args[0]


def test_ner_none_does_not_require_ai_tier():
    with mock.patch.object(deploy, "fail") as fail:
        deploy.preflight_ner_gpu_without_tier(_config("ner-none.ini"), "main")

    fail.assert_not_called()


def test_gpu_embeddings_do_not_require_ai_tier():
    cfg = _config("ner-none.ini")
    assert cfg.get("main_services", "embeddings_provider") == "gpu"

    with mock.patch.object(deploy, "fail") as fail:
        deploy.preflight_ner_gpu_without_tier(cfg, "main")

    fail.assert_not_called()


def test_selfhosted_llm_requires_ai_tier():
    with mock.patch.object(deploy, "fail") as fail:
        deploy.preflight_llm_selfhosted_without_tier(_config("llm-selfhosted.ini"), "main")

    fail.assert_called_once()


@pytest.mark.parametrize(
    "template_name",
    [
        pytest.param("hoover4.ini.development", id="development-template"),
        pytest.param("hoover4.ini.release", id="release-template"),
    ],
)
def test_disabled_template_skips_gpu_ner(template_name):
    cfg = deploy.Config(REPO_ROOT / template_name)

    with mock.patch.object(deploy, "fail") as fail:
        deploy.preflight_ner_gpu_without_tier(cfg, "main")

    fail.assert_not_called()
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(cfg)
    assert env["NER_URL"] == ""
