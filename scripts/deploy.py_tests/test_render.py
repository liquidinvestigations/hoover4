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


def _env(fixture_name):
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        return deploy.render_main_env(_config(fixture_name))


def test_settings_defaults():
    env = _env("settings-defaults.ini")

    assert env["NUM_HISTORY_SHARDS"] == "128"
    assert env["CASSANDRA_MEM_LIMIT"] == "16000M"
    assert env["CASSANDRA_MEM_RESERVATION"] == "5000M"
    assert env["CASSANDRA_CPUS"] == "8"
    assert env["CASSANDRA_HEAP"] == "8G"
    assert env["CASSANDRA_HEAP_NEW"] == "800M"
    assert env["CASSANDRA_JVM_EXTRA_OPTS"] == "-XX:MaxDirectMemorySize=2G"
    assert env["CASSANDRA_CHUNK_CACHE_MB"] == "512"
    assert "CASSANDRA_MALLOC_ARENAS" not in env
    assert env["TEMPORAL_MEM_LIMIT"] == "8000M"
    assert env["TEMPORAL_CPUS"] == "8"
    assert env["DEFAULT_NAMESPACE_RETENTION"] == "168h"
    assert env["TESSERACT_CPU_CONCURRENCY"] == "2"
    assert env["TESSERACT_CPU_QUEUE_DEPTH"] == "8"
    assert env["TESSERACT_CPU_MEM_LIMIT"] == "6144M"
    assert "TESSERACT_THREADS_PER_PAGE" not in env
    assert "TESSERACT_CPU_CPUS" not in env
    assert env["CONTAINER_LOG_MAX_SIZE"] == "100m"
    assert env["CONTAINER_LOG_MAX_FILES"] == "5"
    assert env["HOOVER4_COMMON_MAX_CACHED_WORKFLOWS"] == "100"


def test_cassandra_heap_new_follows_the_cpus():
    assert _env("cassandra-heap-new.ini")["CASSANDRA_HEAP_NEW"] == "600M"


def test_cassandra_memory_limit_below_the_sum_is_refused():
    with pytest.raises(deploy.DeployError) as refused:
        _env("cassandra-memory-refused.ini")

    message = str(refused.value)
    assert "cassandra_mem_limit = 10000M" in message
    assert "cassandra_heap = 8G" in message
    assert "cassandra_direct_memory = 2G" in message


def test_rate_limit_goes_into_the_generated_dynamic_config():
    import yaml

    tracked = (REPO_ROOT / "main_services/ops/docker/temporal-dynamicconfig/docker.yaml")
    tracked_text = tracked.read_text()
    generated = yaml.safe_load(deploy.render_temporal_dynamic_config(
        _config("temporal-rate-limit.ini"), tracked_text))

    assert generated["history.persistenceMaxQPS"] == [{"value": 3000}]
    assert "frontend.persistenceMaxQPS" not in generated
    for key, value in yaml.safe_load(tracked_text).items():
        assert generated[key] == value


def test_no_rate_limit_keeps_the_tracked_dynamic_config():
    import yaml

    tracked_text = (REPO_ROOT / "main_services/ops/docker/temporal-dynamicconfig/"
                    "docker.yaml").read_text()
    generated = deploy.render_temporal_dynamic_config(
        _config("settings-defaults.ini"), tracked_text)

    assert yaml.safe_load(generated) == yaml.safe_load(tracked_text)


RESEARCH = "compose/research-agents.yaml"
RESEARCH_INTERNET = "compose/research-agents-internet.yaml"


@pytest.mark.parametrize(
    ("fixture_name", "agents", "internet"),
    [
        pytest.param("provider-off.ini", False, False, id="no-provider"),
        pytest.param("provider-on-internet-off.ini", True, False, id="provider-internet-off"),
        pytest.param("provider-on-internet-on.ini", True, True, id="provider-internet-on"),
    ],
)
def test_research_agents_follow_the_llm_provider(fixture_name, agents, internet):
    cfg = _config(fixture_name)
    overlays = deploy.selected_overlays(cfg, "main")
    services = {svc for svc, _port in deploy.expected_ports(cfg, "main")}

    assert (RESEARCH in overlays) is agents
    assert (RESEARCH_INTERNET in overlays) is internet
    for name in deploy.RESEARCH_AGENT_SERVICES:
        assert (name in services) is agents
    assert "compose/agents.yaml" in overlays
    with mock.patch.object(deploy, "fail", side_effect=AssertionError):
        deploy.preflight_compose_yaml(cfg, "main")


def test_research_agents_are_removed_with_no_provider():
    rt = mock.Mock()
    deploy.stop_disabled_research_agents(_config("provider-off.ini"), rt)
    removed = [c.args[0][-1] for c in rt.run.call_args_list]
    assert removed == list(deploy.RESEARCH_AGENT_SERVICES)

    rt = mock.Mock()
    deploy.stop_disabled_research_agents(_config("provider-on-internet-off.ini"), rt)
    rt.run.assert_not_called()


def test_tesseract_concurrency_sets_the_queue_depth():
    env = _env("tesseract-concurrency.ini")

    assert env["TESSERACT_CPU_CONCURRENCY"] == "24"
    assert env["TESSERACT_CPU_QUEUE_DEPTH"] == "96"
    warning = deploy.ocr_concurrency_warning(_config("tesseract-concurrency.ini"))
    assert warning is not None and "ocr_concurrency = 4" in warning


def _settings(**main_values):
    cfg = _config("settings-defaults.ini")
    cfg.values["main_services"].update(main_values)
    return cfg


def test_empty_tesseract_memory_limit_follows_the_concurrency():
    cfg = _settings(tesseract_cpu_mem_limit="", tesseract_cpu_concurrency="3")

    assert deploy.render_tesseract_env(cfg)["TESSERACT_CPU_MEM_LIMIT"] == "7168M"


def test_set_tesseract_memory_limit_wins_over_the_formula():
    cfg = _settings(tesseract_cpu_mem_limit="5000M", tesseract_cpu_concurrency="3")

    assert deploy.render_tesseract_env(cfg)["TESSERACT_CPU_MEM_LIMIT"] == "5000M"


@pytest.mark.parametrize("key", ["cassandra_cpus", "temporal_cpus", "tesseract_cpu_cpus"])
def test_cpu_key_above_the_host_is_refused(key):
    cfg = _settings(**{key: "9"})

    with mock.patch.object(deploy.os, "cpu_count", return_value=8), \
            mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        with pytest.raises(deploy.DeployError) as refused:
            deploy.render_main_env(cfg)

    message = str(refused.value)
    assert "%s = 9" % key in message
    assert "8 CPUs" in message


def test_cpu_key_at_the_host_count_is_accepted():
    cfg = _settings(cassandra_cpus="8", temporal_cpus="8", tesseract_cpu_cpus="8")

    with mock.patch.object(deploy.os, "cpu_count", return_value=8), \
            mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(cfg)

    assert env["TESSERACT_CPU_CPUS"] == "8"


def test_tesseract_overlay_maps_the_rendered_variables():
    text = (REPO_ROOT / "main_services/ops/docker/compose/tesseract-cpu.yaml").read_text()

    assert "OCR_CONCURRENCY=${TESSERACT_CPU_CONCURRENCY:-2}" in text
    assert "OCR_QUEUE_DEPTH=${TESSERACT_CPU_QUEUE_DEPTH:-8}" in text
    assert "OMP_THREAD_LIMIT" in text


def _compose_documents():
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!override", lambda loader, node: None)
    Loader.add_constructor("!reset", lambda loader, node: None)
    docker_dir = REPO_ROOT / "main_services/ops/docker"
    paths = [docker_dir / "docker-compose.yaml"] + sorted((docker_dir / "compose").glob("*.yaml"))
    return [(path.name, yaml.load(path.read_text(), Loader=Loader)) for path in paths]


def _ai_compose_documents():
    import yaml

    ai_dir = REPO_ROOT / "ai_services"
    paths = [ai_dir / "docker-compose.yaml"] + sorted((ai_dir / "compose").glob("*.yaml"))
    return [("ai_services/" + path.name, yaml.safe_load(path.read_text())) for path in paths]


def test_every_service_rotates_its_logs():
    expected = {
        "driver": "json-file",
        "options": {
            "max-size": "${CONTAINER_LOG_MAX_SIZE:-100m}",
            "max-file": "${CONTAINER_LOG_MAX_FILES:-5}",
        },
    }
    checked = 0
    for name, document in _compose_documents():
        for service, definition in document["services"].items():
            if "image" not in definition and "build" not in definition:
                continue  # an override of a service another file defines
            assert definition.get("logging") == expected, "%s: %s" % (name, service)
            checked += 1
    assert checked >= 16

    ai_checked = 0
    for name, document in _ai_compose_documents():
        for service, definition in (document.get("services") or {}).items():
            assert definition.get("logging") == expected, "%s: %s" % (name, service)
            ai_checked += 1
    assert ai_checked == 3


def test_gpu_tier_env_carries_the_log_rotation():
    env = deploy.render_ai_env(_config("settings-defaults.ini"))

    assert env["CONTAINER_LOG_MAX_SIZE"] == "100m"
    assert env["CONTAINER_LOG_MAX_FILES"] == "5"


def test_cassandra_service_settings():
    documents = dict(_compose_documents())
    cassandra = documents["docker-compose.yaml"]["services"]["temporal-cassandra"]

    assert cassandra["cap_add"] == ["SYS_NICE"]
    assert cassandra["deploy"]["resources"]["limits"]["memory"] == "${CASSANDRA_MEM_LIMIT:-16000M}"
    assert "JVM_EXTRA_OPTS=${CASSANDRA_JVM_EXTRA_OPTS:--XX:MaxDirectMemorySize=2G}" in \
        cassandra["environment"]


@pytest.mark.parametrize("template_name", ["hoover4.ini.development", "hoover4.ini.release"])
def test_templates_render_the_new_settings(template_name):
    cfg = deploy.Config(REPO_ROOT / template_name)
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(cfg)

    assert env["NUM_HISTORY_SHARDS"] == "128"
    assert env["CASSANDRA_HEAP_NEW"] == "800M"
    assert env["DEFAULT_NAMESPACE_RETENTION"] == "168h"
    assert env["TESSERACT_CPU_MEM_LIMIT"] == "6144M"
    assert deploy.temporal_retention_command(cfg)[-3:] == [
        "168h", "--address", "temporal:7233"]
