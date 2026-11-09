"""Render tests for the deployment configuration."""

import builtins
import configparser
import importlib.util
import json
import os
import re
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

SAMPLES = ("hoover4.ini.release", "hoover4.ini.development")


def _template(name="hoover4.ini.development"):
    """Return the Config of a tracked sample."""
    return deploy.Config(REPO_ROOT / name)


@pytest.mark.parametrize("same_image", [True, False])
def test_stale_image_detection_compares_complete_identifiers(same_image):
    image_id = "142351ea5fcf" + "7" * 52
    latest_id = image_id if same_image else "8" * 64
    rt = mock.Mock()

    def run(args, **kwargs):
        if args[0] == "ps":
            identifier = image_id if "--no-trunc" in args else image_id[:12]
            return subprocess.CompletedProcess(args, 0, f"service image:local {identifier}\n", "")
        if args[:2] == ["image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, latest_id + "\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    rt.run.side_effect = run
    with mock.patch.object(deploy, "compose_command", return_value=["compose", "up"]), \
         mock.patch.object(deploy, "run_or_fail") as recreate:
        deploy.podman_stale_image_fix(deploy.Config(None), "main", rt, [])
    removals = [call for call in rt.run.call_args_list if call.args[0][0] == "rm"]
    assert len(removals) == (0 if same_image else 1)
    assert recreate.call_count == (0 if same_image else 1)


def _render(fixture_name):
    cfg = _config(fixture_name)
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
                "EMBEDDINGS_URL": "",
                "RERANK_URL": "",
                "OCR_EASYOCR_URL": "",
            },
            id="gpu-off-leftovers",
        ),
        pytest.param(
            "ner-none.ini",
            {
                "NER_URL": "",
                "EMBEDDINGS_URL": "http://127.0.0.1:21961/v1",
                "RERANK_URL": "http://127.0.0.1:21961/v1",
            },
            id="ner-disabled",
        ),
        pytest.param(
            "embeddings-off.ini",
            {
                "NER_URL": "http://127.0.0.1:21961/v1",
                "EMBEDDINGS_URL": "",
                "RERANK_URL": "",
                "EMBEDDINGS_DIM": "384",
            },
            id="embeddings-disabled",
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
            "llm-selfhosted-tier.ini",
            {
                "LLM_BASE_URL": "http://127.0.0.1:21960/v1",
                "LLM_MODEL": "dgemma",
                "LLM_PROVIDER_NAME": "selfhosted",
            },
            id="llm-selfhosted-tier",
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
    cfg = deploy.Config(FIXTURES / fixture_name)
    cfg.values["main_services"].update({
        "manticore_mem_limit": "32G",
        "manticore_vectors_mem_limit": "32G",
    })
    return cfg


def test_disabled_reranker_preserves_embeddings_and_disables_model():
    cfg = _config("gpu-on.ini")
    cfg.values["ai_services"]["reranker_enabled"] = "false"
    with mock.patch.object(deploy, "Config", return_value=cfg):
        env, _ = _render("gpu-on.ini")
    assert env["EMBEDDINGS_URL"]
    assert env["RERANK_URL"] == ""
    assert deploy.render_ai_env(cfg)["AI_SERVER_ENABLE_RERANKER"] == "false"


def test_manticore_memory_limits_are_required_and_rendered():
    cfg = _config("settings-defaults.ini")
    cfg.values["main_services"].pop("manticore_mem_limit")
    with pytest.raises(deploy.DeployError, match="manticore_mem_limit.*32G"):
        deploy.render_main_env(cfg)

    cfg = _config("settings-defaults.ini")
    cfg.values["main_services"]["manticore_vectors_mem_limit"] = ""
    with pytest.raises(deploy.DeployError, match="manticore_vectors_mem_limit.*32G"):
        deploy.render_main_env(cfg)

    cfg = _config("settings-defaults.ini")
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(cfg)
    assert env["MANTICORE_MEM_LIMIT"] == "32G"
    assert env["MANTICORE_VECTORS_MEM_LIMIT_BYTES"] == "34359738368"


def test_scanner_and_ui_memory_limits_are_validated_and_rendered():
    cfg = _config("settings-defaults.ini")
    settings = {
        "regex_scanner_mem_limit": "4G",
        "temporal_ui_mem_limit": "512M",
        "clickhouse_ui_mem_limit": "512M",
        "clickhouse_monitoring_mem_limit": "768M",
    }
    cfg.values["main_services"].update(settings)
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(cfg)
    for key, value in settings.items():
        assert env[key.upper()] == value

    for key in settings:
        for bad in ("", "0M", "not-a-size"):
            invalid = _config("settings-defaults.ini")
            invalid.values["main_services"][key] = bad
            with pytest.raises(deploy.DeployError, match=key):
                deploy.render_main_env(invalid)


def test_scanner_and_ui_compose_limits_use_rendered_names():
    documents = dict(_compose_documents())
    main = documents["docker-compose.yaml"]["services"]
    scanner = documents["regex-entity-scanner.yaml"]["services"]
    expected = (
        (scanner["hoover4-regex-entity-scanner"], "REGEX_SCANNER_MEM_LIMIT"),
        (main["temporal-ui"], "TEMPORAL_UI_MEM_LIMIT"),
        (main["ch-ui"], "CLICKHOUSE_UI_MEM_LIMIT"),
        (main["clickhouse-monitoring"], "CLICKHOUSE_MONITORING_MEM_LIMIT"),
    )
    for service, key in expected:
        assert service["mem_limit"].startswith("${" + key + ":-")
        assert service["memswap_limit"] == service["mem_limit"]


def test_ner_and_embeddings_with_the_gpu_tier_off_are_not_refused(capsys, tmp_path):
    """NER and embeddings default to on. With the GPU tier off, their endpoints are empty
    and the file is still valid."""
    env = _env("gpu-off-leftovers.ini")
    assert (env["NER_URL"], env["EMBEDDINGS_URL"], env["RERANK_URL"]) == ("", "", "")
    path = tmp_path / "gpu-off.ini"
    path.write_text((FIXTURES / "gpu-off-leftovers.ini").read_text(encoding="utf-8")
                    + "\n[storage]\nvolumes_path = /srv/hoover4-volumes\n", encoding="utf-8")
    text = path.read_text(encoding="utf-8").replace(
        "[main_services]\n",
        "[main_services]\nmanticore_mem_limit = 32G\nmanticore_vectors_mem_limit = 16G\n")
    path.write_text(text, encoding="utf-8")
    code, out, _err = _run(["--check"], path, capsys)
    assert code == 0, out
    assert "configuration valid" in out


def test_the_ai_server_switch_turns_both_endpoints_off():
    cfg = _config("gpu-on.ini")
    cfg.values["ai_services"]["ai_server_enabled"] = "false"
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda h: h):
        env = deploy.render_main_env(cfg)
    assert (env["NER_URL"], env["EMBEDDINGS_URL"], env["RERANK_URL"]) == ("", "", "")


def test_removed_provider_variables_are_not_rendered():
    env = _env("gpu-on.ini")
    for name in ("NER_PROVIDER", "EMBEDDINGS_PROVIDER", "EMBEDDINGS_CPU_PORT", "GPU_FALLBACK",
                 "LLM_MODEL_COMPACTION", "CASSANDRA_VERSION", "ELASTICSEARCH_VERSION",
                 "TEMPORAL_VERSION", "TEMPORAL_UI_VERSION", "GARAGE_VERSION",
                 "GARAGE_IMAGE_DIGEST"):
        assert name not in env, name
    ai_env = deploy.render_ai_env(_config("gpu-on.ini"))
    for name in ("EMBEDDINGS_MODEL", "EMBEDDINGS_DIM", "RERANKER_MODEL",
                 "AI_SERVER_ENABLE_HALF_PRECISION", "AI_SERVER_ENABLE_TORCH_COMPILE"):
        assert name not in ai_env, name


def test_selfhosted_llm_requires_ai_tier():
    with mock.patch.object(deploy, "fail") as fail:
        deploy.preflight_llm_without_tier(_config("llm-selfhosted.ini"), "main")

    fail.assert_called_once()
    assert "[ai_services] llm_enabled = true but [ai_services] enabled = false" in \
        fail.call_args.args[0]
    with mock.patch.object(deploy, "fail") as fail:
        deploy.preflight_llm_without_tier(_config("llm-selfhosted-tier.ini"), "main")
    fail.assert_not_called()


def test_the_llm_preflight_refuses_a_check_of_the_main_side(capsys, tmp_path):
    cfg_path = FIXTURES / "llm-selfhosted.ini"
    text = cfg_path.read_text(encoding="utf-8").replace(
        "[main_services]\n",
        "[main_services]\nmanticore_mem_limit = 32G\nmanticore_vectors_mem_limit = 16G\n")
    path = tmp_path / "llm-without-tier.ini"
    path.write_text(text + "\n[storage]\nvolumes_path = /srv/hoover4-volumes\n",
                    encoding="utf-8")
    code, out, err = _run(["--check"], path, capsys)
    assert code == 1
    assert "[ai_services] llm_enabled = true but [ai_services] enabled = false" in out + err


@pytest.mark.parametrize(
    "template_name",
    [
        pytest.param("hoover4.ini.development", id="development-template"),
        pytest.param("hoover4.ini.release", id="release-template"),
    ],
)
def test_disabled_template_skips_gpu_ner(template_name):
    cfg = _template(template_name)

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


#: The chat run is the one run kind, with one pack key.
PACK_KEYS = ("AGENT_PACKS_CHAT",)


#: The default is every available pack.
PACK_DEFAULTS = ["all"]


def test_agent_packs_default_to_all():
    env = _env("settings-defaults.ini")
    assert [env[key] for key in PACK_KEYS] == PACK_DEFAULTS
    assert not {"AGENT_PACKS_SUBAGENT", "AGENT_PACKS_PLANNER", "AGENT_PACKS_ORGANIZER"} & set(env)


def test_a_narrowed_agent_pack_value_is_rendered_and_an_empty_one_is_all(capsys):
    env = _env("agent-packs.ini")
    assert env["AGENT_PACKS_CHAT"] == "collections,catalogue,conversation"
    assert "AGENT_PACKS_PLANNER" not in env
    assert "agent_packs_subagent" not in capsys.readouterr().err


def test_both_research_agents_receive_the_pack_keys():
    agents = dict(_compose_documents())["research-agents.yaml"]["services"]
    for name in ("hoover4-internal-search-agent", "hoover4-full-research-agent"):
        environment = agents[name]["environment"]
        for key in PACK_KEYS:
            assert f"{key}=${{{key}:-all}}" in environment, (name, key)
        assert not any(line.startswith("AGENT_PACKS_SUBAGENT=") for line in environment)


@pytest.mark.parametrize("fixture_name", sorted(
    p.name for p in FIXTURES.glob("*.ini") if p.name != "cassandra-memory-refused.ini"))
def test_no_rendered_env_holds_a_retired_agent_key(fixture_name):
    env = _env(fixture_name)
    for key in ("LLM_CLASSIFIER_URL", "AGENT_MAX_PAGE_TOKENS",
                "AGENT_COMPLETION_RESERVE_TOKENS"):
        assert key not in env, (fixture_name, key)


def test_no_research_agent_receives_a_retired_agent_key():
    agents = dict(_compose_documents())["research-agents.yaml"]["services"]
    for name in ("hoover4-internal-search-agent", "hoover4-full-research-agent"):
        for line in agents[name]["environment"]:
            assert not line.startswith(("LLM_CLASSIFIER_URL=", "AGENT_MAX_PAGE_TOKENS=",
                                        "AGENT_COMPLETION_RESERVE_TOKENS=")), (name, line)


def test_the_retired_plan_budget_is_not_rendered():
    assert "AGENT_PLAN_RUN_BUDGET" not in _env("settings-defaults.ini")


def test_the_worker_receives_no_plan_budget():
    main = dict(_compose_documents())["docker-compose.yaml"]["services"]
    environment = main["hoover4-worker"]["environment"]
    assert not any("AGENT_PLAN_RUN_BUDGET" in value for value in environment)
    assert not any("AGENT_SUBAGENT_MAX_PER_TURN" in value for value in environment)


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
    env, _ = _render(fixture_name)
    assert env["HOOVER4_INTERNET_TOOLS_ENABLED"] == (
        "false" if fixture_name == "provider-on-internet-off.ini" else "true"
    )
    overlays = deploy.selected_overlays(cfg, "main")
    services = {svc for svc, _port in deploy.expected_ports(cfg, "main")}

    assert (RESEARCH in overlays) is agents
    assert (RESEARCH_INTERNET in overlays) is internet
    for name in deploy.RESEARCH_AGENT_SERVICES:
        assert (name in services) is agents
    assert "compose/agents.yaml" in overlays
    with mock.patch.object(deploy, "fail", side_effect=AssertionError):
        deploy.preflight_compose_yaml(cfg, "main")


def test_research_agents_need_the_gpu_tier_with_the_model_servers():
    assert not deploy.research_agents_enabled(_config("llm-selfhosted.ini"))
    assert deploy.research_agents_enabled(_config("llm-selfhosted-tier.ini"))


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


def _ocr_pdf(**main_values):
    cfg = _config("ocr-pdf-slots.ini")
    cfg.values["main_services"].update(main_values)
    return cfg


def _ocr_pdf_env(**main_values):
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        return deploy.render_main_env(_ocr_pdf(**main_values))


def test_empty_builder_keys_follow_the_tesseract_concurrency():
    env = _ocr_pdf_env()

    assert env["OCR_PDF_CONCURRENCY"] == "24"
    assert env["OCR_PDF_QUEUE_DEPTH"] == "24"
    assert env["HOOVER4_OCR_PDF_CONCURRENCY"] == "24"
    assert env["OCR_PDF_MEM_LIMIT"] == "14336M"
    assert deploy.ocr_concurrency_warning(_ocr_pdf()) is None


def test_set_builder_keys_win():
    env = _ocr_pdf_env(ocr_pdf_concurrency="6", ocr_pdf_queue_depth="3")

    assert env["OCR_PDF_CONCURRENCY"] == "6"
    assert env["OCR_PDF_QUEUE_DEPTH"] == "3"
    assert env["HOOVER4_OCR_PDF_CONCURRENCY"] == "6"
    assert env["OCR_PDF_MEM_LIMIT"] == "8000M"


def test_builder_has_two_slots_without_tesseract():
    env = _ocr_pdf_env(tesseract_cpu_enabled="false")

    assert env["OCR_PDF_CONCURRENCY"] == "2"
    assert env["OCR_PDF_QUEUE_DEPTH"] == "2"
    assert env["HOOVER4_OCR_PDF_CONCURRENCY"] == "2"
    assert env["OCR_PDF_MEM_LIMIT"] == "8000M"


def test_set_builder_memory_limit_wins_and_warns_below_the_formula():
    env = _ocr_pdf_env(ocr_pdf_mem_limit="9000M")

    assert env["OCR_PDF_MEM_LIMIT"] == "9000M"
    warning = deploy.ocr_concurrency_warning(_ocr_pdf(ocr_pdf_mem_limit="9000M"))
    assert warning is not None
    assert "ocr_pdf_mem_limit = 9000M is below 14336M" in warning


def test_builder_slots_above_the_tesseract_admission_warn():
    warning = deploy.ocr_concurrency_warning(_ocr_pdf(ocr_concurrency="100"))

    assert warning is not None
    assert "ocr_concurrency + ocr_pdf_concurrency = 124 is above the 120 requests" in warning


def test_zero_builder_slots_are_refused():
    with pytest.raises(deploy.DeployError) as refused:
        _ocr_pdf_env(ocr_pdf_concurrency="0")
    assert "ocr_pdf_concurrency must be at least 1" in str(refused.value)


def test_compose_maps_the_builder_variables():
    builder = (REPO_ROOT / "main_services/ops/docker/compose/ocr-pdf.yaml").read_text()
    worker = (REPO_ROOT / "main_services/ops/docker/docker-compose.yaml").read_text()

    assert "OCR_PDF_CONCURRENCY=${OCR_PDF_CONCURRENCY:-2}" in builder
    assert "OCR_PDF_QUEUE_DEPTH=${OCR_PDF_QUEUE_DEPTH:-4}" in builder
    assert '"HOOVER4_OCR_PDF_CONCURRENCY=${HOOVER4_OCR_PDF_CONCURRENCY:-}"' in worker


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
        # The render does not refuse. Only a command that starts containers does.
        deploy.render_main_env(cfg)
        refusals = deploy.cpu_host_refusals(cfg)

    assert len(refusals) == 1
    assert "%s = 9" % key in refusals[0]
    assert "8 CPUs" in refusals[0]


def test_cpu_key_at_the_host_count_is_accepted():
    cfg = _settings(cassandra_cpus="8", temporal_cpus="8", tesseract_cpu_cpus="8")

    with mock.patch.object(deploy.os, "cpu_count", return_value=8), \
            mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(cfg)
        assert deploy.cpu_host_refusals(cfg) == []

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
    # The tracked files only. A checkout that has run deploy.py also holds the generated
    # dataset mount overlay, which the dataset mount tests read on their own.
    paths = [docker_dir / "docker-compose.yaml"] + sorted(
        path for path in (docker_dir / "compose").glob("*.yaml")
        if path.name != deploy.DATASET_MOUNTS_OVERLAY.name)
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
    assert ai_checked == 4


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
    cfg = _template(template_name)
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(cfg)

    assert env["NUM_HISTORY_SHARDS"] == "128"
    assert env["CASSANDRA_HEAP_NEW"] == "800M"
    assert env["DEFAULT_NAMESPACE_RETENTION"] == "168h"
    assert env["TESSERACT_CPU_MEM_LIMIT"] == "6144M"
    assert env["OCR_PDF_CONCURRENCY"] == "2"
    assert env["OCR_PDF_MEM_LIMIT"] == "8000M"
    assert [env[key] for key in PACK_KEYS] == PACK_DEFAULTS
    assert deploy.temporal_retention_command(cfg)[-3:] == [
        "168h", "--address", "temporal:7233"]


# ---- volume folders ---------------------------------------------------------------

def _storage(path):
    cfg = _config("storage-volumes-path.ini")
    cfg.values["storage"]["volumes_path"] = str(path)
    return cfg


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("", "is empty", id="empty"),
        pytest.param("hoover4-volumes", "is not an absolute path", id="relative"),
    ],
)
def test_unusable_volumes_path_is_refused(value, expected):
    cfg = _storage(value)

    with pytest.raises(deploy.DeployError) as refused:
        deploy.volumes_path(cfg)
    assert "[storage] volumes_path" in str(refused.value)
    assert expected in str(refused.value)
    with pytest.raises(deploy.DeployError):
        deploy.create_volume_folders(cfg, "main")
    assert any("[storage] volumes_path" in p for p in deploy.start_refusals(cfg, "ai"))


def test_folder_that_cannot_be_created_halts(tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    cfg = _storage(blocker / "volumes")

    with pytest.raises(deploy.DeployError) as refused:
        deploy.create_volume_folders(cfg, "main")

    assert str(blocker / "volumes") in str(refused.value)


def test_folders_of_the_side_are_created(tmp_path):
    root = tmp_path / "parent" / "volumes"
    cfg = _storage(root)
    cfg.values["main_services"]["serena_enabled"] = "false"

    deploy.create_volume_folders(cfg, "main")

    created = sorted(p.name for p in root.iterdir())
    expected = sorted(row.name for row in deploy.VOLUMES if row.side == "main")
    assert created == expected


def test_volumes_path_is_rendered_on_both_sides():
    cfg = _config("storage-volumes-path.ini")
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        main_env = deploy.render_main_env(cfg)
    ai_env = deploy.render_ai_env(cfg)

    assert main_env["HOOVER4_VOLUMES_PATH"] == "/srv/hoover4-volumes"
    assert ai_env["HOOVER4_VOLUMES_PATH"] == "/srv/hoover4-volumes"
    assert main_env["HOOVER4_OPS_BACKUP_DIR"] == "/srv/hoover4-volumes/ops_backups"


def test_set_backup_dir_wins_over_the_volume_folder():
    cfg = _config("storage-volumes-path.ini")
    cfg.values["main_services"]["ops_backup_dir"] = "/srv/backups"
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(cfg)

    assert env["HOOVER4_OPS_BACKUP_DIR"] == "/srv/backups"


VOLUMES_SOURCE = "${HOOVER4_VOLUMES_PATH:?deploy.py renders it from [storage] volumes_path}/"
BACKUP_SOURCE = "${HOOVER4_OPS_BACKUP_DIR:?deploy.py renders it from [storage] volumes_path}"


def _all_compose_documents():
    """(side of the file, file name, document) for every compose file of both sides."""
    out = []
    for name, document in _compose_documents():
        out.append(("serena" if name == "serena.yaml" else "main", name, document))
    for name, document in _ai_compose_documents():
        out.append(("ai", name, document))
    return out


def _mounts():
    """(side, file, service, source, target) of every volume mount in every file."""
    out = []
    for side, name, document in _all_compose_documents():
        for service, definition in (document.get("services") or {}).items():
            for entry in definition.get("volumes") or []:
                source, target = entry.split(":", 1) if ":" in entry else (entry, "")
                if entry.startswith("${") and "}" in entry:
                    # The variable can hold a colon, so the source ends after the `}`.
                    closing = entry.index("}")
                    source = entry[:closing + 1] + entry[closing + 1:].split(":", 1)[0]
                    target = entry[len(source) + 1:]
                out.append((side, name, service, source, target))
    return out


def test_no_compose_file_declares_a_top_level_volume():
    for _side, name, document in _all_compose_documents():
        assert "volumes" not in document, name


def test_no_service_mounts_a_named_volume():
    for side, name, service, source, _target in _mounts():
        named = not source.startswith(("/", ".", "$", "~"))
        assert not named, "%s: %s mounts the named volume %s" % (name, service, source)


def test_every_volume_mount_has_a_row_and_every_row_a_mount():
    mounted = set()
    for side, name, service, source, _target in _mounts():
        if source.startswith(VOLUMES_SOURCE):
            mounted.add((source[len(VOLUMES_SOURCE):], side))
        elif source == BACKUP_SOURCE:
            mounted.add(("ops_backups", side))
        else:
            assert "HOOVER4_VOLUMES_PATH" not in source, (name, service, source)

    rows = {(row.name, row.side) for row in deploy.VOLUMES}
    assert mounted == rows
    assert len(rows) == len(deploy.VOLUMES)


def test_row_image_is_the_image_of_its_service():
    images = {}
    for side, _name, document in _all_compose_documents():
        for service, definition in (document.get("services") or {}).items():
            if "image" in definition:
                images[(service, "main" if side == "serena" else side)] = definition["image"]

    for row in deploy.VOLUMES:
        side = "main" if row.side == "serena" else row.side
        assert images[(row.image_service, side)] == row.image, row.name


def test_elasticsearch_folder_is_where_the_process_writes():
    targets = {(service, target) for _s, _n, service, source, target in _mounts()
               if source == VOLUMES_SOURCE + "temporal_elasticsearch"}
    assert targets == {("temporal-elasticsearch", "/usr/share/elasticsearch/data")}
    row = [r for r in deploy.VOLUMES if r.name == "temporal_elasticsearch"][0]
    assert (row.uid, row.gid) == (1000, 0)


def _class_before_folders(name):
    """The class each volume had under the volume-removing reset code."""
    if name == "serena_state":
        return "protected"
    if name in ("ai_models_cache", "dgemma_model", "dgemma_cache", "easyocr_models_cache",
                "chat_model", "chat_cache"):
        return "cache"
    if name in ("temporal_cassandra", "temporal_elasticsearch"):
        return "temporal"
    return "data"


def test_reset_class_of_each_row_is_unchanged():
    for row in deploy.VOLUMES:
        assert row.reset_class == _class_before_folders(row.name), row.name


#: A rendered environment for the owner commands. Their images are literals.
ENV = {}


def test_image_variables_are_resolved():
    assert deploy.resolve_image(deploy.CASSANDRA_IMAGE, ENV) == "cassandra:3.11.9"
    assert deploy.resolve_image("${VLLM_IMAGE:-vllm/x:1}", {}) == "vllm/x:1"
    with pytest.raises(deploy.DeployError):
        deploy.resolve_image("${MISSING}", {})


def test_owner_commands_with_a_stand_in_runtime(tmp_path):
    cfg = _storage(tmp_path)
    rt = mock.Mock()
    rt.run.return_value = subprocess.CompletedProcess([], 0)

    deploy.set_volume_owners(cfg, "main", rt, ENV)

    commands = [c.args[0] for c in rt.run.call_args_list]
    assert ["run", "--rm", "--user", "0", "--entrypoint", "chown",
            "-v", "%s/temporal_cassandra:/d" % tmp_path, "cassandra:3.11.9",
            "999:999", "/d"] in commands
    assert ["run", "--rm", "--user", "0", "--entrypoint", "chown",
            "-v", "%s/temporal_elasticsearch:/d" % tmp_path, "elasticsearch:7.17.27",
            "1000:0", "/d"] in commands
    for command in commands:
        if command[5] == "sh":
            assert "/auth.json.seed:ro" in command[9]
            assert "if [ ! -e /d/auth.json ]" in command[-1]
            assert "chmod 600 /d/auth.json" in command[-1]
            assert "chown 999:999 /d /d/auth.json" in command[-1]
    changed = sorted(c[7].split(":")[0].rsplit("/", 1)[1] for c in commands)
    assert changed == sorted(r.name for r in deploy.VOLUMES
                             if r.side == "main" and r.uid != 0)


def test_owner_command_failure_halts(tmp_path):
    rt = mock.Mock()
    rt.run.return_value = subprocess.CompletedProcess([], 1, "", "no such image")

    with pytest.raises(deploy.DeployError) as refused:
        deploy.set_volume_owners(_storage(tmp_path), "main", rt, ENV)
    assert "no such image" in str(refused.value)


def _filled(tmp_path, side="main"):
    cfg = _storage(tmp_path)
    for row in deploy.side_volumes(cfg, side):
        folder = tmp_path / row.name
        folder.mkdir(exist_ok=True)
        (folder / "file").write_text("x")
    (tmp_path / "not-a-volume").mkdir()
    (tmp_path / "not-a-volume" / "file").write_text("x")
    return cfg


def _emptied(rt, tmp_path):
    out = []
    for call in rt.run.call_args_list:
        command = call.args[0]
        assert command[:6] == ["run", "--rm", "--user", "0", "--entrypoint", "sh"]
        assert command[-2:] == ["-c", "find /d -mindepth 1 -delete"]
        folder = command[7].rsplit(":", 1)[0]
        assert folder.startswith(str(tmp_path) + "/")
        out.append(folder.rsplit("/", 1)[1])
    return sorted(out)


@pytest.mark.parametrize(
    ("classes", "expected"),
    [
        pytest.param(deploy.RESET_CLASSES, {"data", "temporal"}, id="reset"),
        pytest.param(deploy.RESET_CACHES_CLASSES, {"data", "temporal", "cache"},
                     id="reset-caches"),
        pytest.param(deploy.RESET_TEMPORAL_CLASSES, {"temporal"}, id="reset-temporal"),
    ],
)
def test_reset_empties_the_folders_of_its_classes(tmp_path, classes, expected):
    cfg = _filled(tmp_path)
    rt = mock.Mock()
    rt.run.return_value = subprocess.CompletedProcess([], 0)

    deploy.empty_volume_folders(cfg, "main", rt, ENV, classes, "reset")

    assert _emptied(rt, tmp_path) == sorted(
        r.name for r in deploy.side_volumes(cfg, "main") if r.reset_class in expected)
    garage = [c.args[0] for c in rt.run.call_args_list if "garage_data:/d" in c.args[0][7]]
    if "data" in expected:
        assert garage[0][8] == "cassandra:3.11.9"


def test_reset_skips_an_empty_folder(tmp_path):
    cfg = _storage(tmp_path)
    (tmp_path / "clickhouse_data").mkdir()
    rt = mock.Mock()

    deploy.empty_volume_folders(cfg, "main", rt, ENV, deploy.RESET_CLASSES, "reset")

    rt.run.assert_not_called()


# ---- which command refuses on which key ---------------------------------------------

def _run_main(argv, cfg, cpus=1):
    with mock.patch.object(deploy, "load_config", return_value=cfg), \
            mock.patch.object(deploy.shutil, "which", return_value="docker"), \
            mock.patch.object(deploy.os, "cpu_count", return_value=cpus), \
            mock.patch.object(deploy, "container_reachable_host", side_effect=lambda h: h), \
            mock.patch.object(deploy, "run_preflights"), \
            mock.patch.object(deploy, "_write_if_changed", return_value=False), \
            mock.patch.object(deploy, "compose_down") as down, \
            mock.patch.object(deploy, "compose_reset") as reset, \
            mock.patch.object(deploy, "compose_reset_temporal") as reset_temporal, \
            mock.patch.object(deploy, "compose_up") as up:
        code = deploy.main(argv)
    return code, {"down": down, "reset": reset, "reset_temporal": reset_temporal, "up": up}


def test_print_env_warns_and_prints(capsys):
    cfg = _storage("")
    code, _calls = _run_main(["--print-env"], cfg)

    captured = capsys.readouterr()
    assert code == 0
    assert "warning: [storage] volumes_path is empty" in captured.err
    assert "warning: [main_services] cassandra_cpus = 8" in captured.err
    assert "HOOVER4_VOLUMES_PATH=\n" in captured.out


def test_down_runs_with_unusable_keys():
    code, calls = _run_main(["--down"], _storage(""))

    assert code == 0
    calls["down"].assert_called_once()


def test_down_environment_has_a_stand_in_path():
    env = deploy.down_environment(_storage(""))
    assert env["HOOVER4_VOLUMES_PATH"] == deploy.DOWN_VOLUMES_PATH_STANDIN
    assert env["HOOVER4_OPS_BACKUP_DIR"].startswith(deploy.DOWN_VOLUMES_PATH_STANDIN)
    assert deploy.down_environment(_storage("/srv/hoover4-volumes")) is None


@pytest.mark.parametrize(
    ("argv", "call"),
    [
        pytest.param(["--reset"], "reset", id="reset"),
        pytest.param(["--reset", "--reset-caches"], "reset", id="reset-caches"),
        pytest.param(["--reset-temporal"], "reset_temporal", id="reset-temporal"),
    ],
)
def test_reset_refuses_the_path_and_not_the_cpu_keys(argv, call):
    code, calls = _run_main(argv, _storage("/srv/hoover4-volumes"))
    assert code == 0
    calls[call].assert_called_once()

    with pytest.raises(deploy.DeployError) as refused:
        _run_main(argv, _storage(""), cpus=64)
    assert "[storage] volumes_path" in str(refused.value)


def test_start_refuses_the_cpu_keys(tmp_path):
    with pytest.raises(deploy.DeployError) as refused:
        _run_main([], _storage(tmp_path))
    assert "cassandra_cpus = 8" in str(refused.value)
    assert not any(tmp_path.iterdir())


def test_start_refuses_the_path():
    with pytest.raises(deploy.DeployError) as refused:
        _run_main([], _storage(""), cpus=64)
    assert "[storage] volumes_path" in str(refused.value)


PROBE_KEYS = ("AGENT_CATALOGUE_MATCH_COUNT",)


def test_absent_probe_keys_render_empty():
    env = _env("settings-defaults.ini")
    assert [env[key] for key in PROBE_KEYS] == [""]


def test_the_probe_keys_are_rendered():
    env = _env("agent-probe-keys.ini")
    assert [env[key] for key in PROBE_KEYS] == ["8"]


@pytest.mark.parametrize("key, value", [
    ("agent_catalogue_match_count", "5"),
    ("agent_catalogue_match_count", "13"),
])
def test_an_out_of_range_probe_key_is_refused(key, value):
    cfg = deploy.Config(FIXTURES / "agent-probe-keys.ini")
    cfg.values["main_services"][key] = value
    with pytest.raises(deploy.DeployError) as refused:
        deploy.agent_probe_env(cfg)
    assert key in str(refused.value)


def test_both_research_agents_receive_the_probe_keys():
    agents = dict(_compose_documents())["research-agents.yaml"]["services"]
    for name in ("hoover4-internal-search-agent", "hoover4-full-research-agent"):
        environment = agents[name]["environment"]
        for key in PROBE_KEYS:
            assert f"{key}=${{{key}:-}}" in environment, (name, key)


# ---- the agent model calls ------------------------------------------------------------

#: The worker's timeout variables and the agent services' model variables.
WORKER_TIMEOUT_VARS = ("HOOVER4_AGENT_QUEUE_WAIT_SECONDS",
                       "HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS",
                       "HOOVER4_BOARD_REASON_REQUEST_SECONDS")
AGENT_MODEL_VARS = ("LLM_REQUEST_TIMEOUT_SECONDS", "AGENT_MAX_OUTPUT_TOKENS", "LLM_STREAMING",
                    "LLM_SEND_TEMPERATURE")
#: The thinking switch is the `server_settings` row `llm_thinking`, so no key renders it.
REMOVED_THINKING_VARS = ("AGENT_THINKING", "AGENT_TOOL_TURN_THINKING")


def _model_env(fixture_name="settings-defaults.ini", section="main_services", **values):
    cfg = _config(fixture_name)
    cfg.values[section].update(values)
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        return deploy.render_main_env(cfg)


def test_empty_agent_model_keys_keep_the_code_defaults():
    env = _model_env()
    assert [env[name] for name in WORKER_TIMEOUT_VARS] == ["", "", ""]
    assert "HOOVER4_CHAT_RUN_TIMEOUT_SECONDS" not in env
    assert "HOOVER4_PLAN_RUN_TIMEOUT_SECONDS" not in env
    assert env["LLM_REQUEST_TIMEOUT_SECONDS"] == ""
    assert env["AGENT_MAX_OUTPUT_TOKENS"] == ""
    assert env["LLM_STREAMING"] == "true"


def test_set_timeout_keys_land_in_their_variables():
    env = _model_env(
        agent_queue_wait_seconds="5400", title_request_timeout_seconds="120",
        board_reason_request_seconds="600", llm_request_timeout_seconds="3600",
        agent_max_output_tokens="32768")
    assert [env[name] for name in WORKER_TIMEOUT_VARS] == ["5400", "120", "600"]
    assert env["LLM_REQUEST_TIMEOUT_SECONDS"] == "3600"
    assert env["AGENT_MAX_OUTPUT_TOKENS"] == "32768"


@pytest.mark.parametrize("values", [
    {}, {"agent_thinking": "on", "agent_tool_turn_thinking": "true"}])
def test_no_thinking_variable_renders(values):
    env = _model_env(**values)
    for name in REMOVED_THINKING_VARS:
        assert name not in env, name


@pytest.mark.parametrize("key, value", [
    ("title_request_timeout_seconds", "0"),
    ("board_reason_request_seconds", "ten minutes"),
    ("agent_queue_wait_seconds", "an hour"),
    ("llm_request_timeout_seconds", "1.5"),
    ("agent_max_output_tokens", "-1"),
])
def test_a_bad_agent_model_number_is_refused(key, value):
    with pytest.raises(deploy.DeployError) as refused:
        _model_env(**{key: value})
    assert key in str(refused.value)


def test_the_agent_tool_slots_render_when_set():
    env = _model_env(agent_tool_concurrency="16")
    assert env["HOOVER4_AGENT_TOOL_CONCURRENCY"] == "16"
    env = _model_env()
    assert "HOOVER4_AGENT_TOOL_CONCURRENCY" not in env


@pytest.mark.parametrize("value, rendered", [("", "true"), ("true", "true"), ("false", "false")])
def test_llm_streaming_renders_true_unless_turned_off(value, rendered):
    env = _model_env(llm_streaming=value)
    assert env["LLM_STREAMING"] == rendered


LLM_ENABLED_ENV = {
    "LLM_PROVIDER_NAME": "selfhosted",
    "LLM_BASE_URL": "http://10.9.9.9:21960/v1",
    "LLM_MODEL": "dgemma",
    "LLM_SEND_TEMPERATURE": "false",
    "CHAT_CLASSIFIER_URL": "http://10.9.9.9:21963",
    "LLM_QUALITY_BASE_URL": "http://10.9.9.9:21964/v1",
    "LLM_QUALITY_MODEL": "ornith",
    "LLM_VISION_MODELS": "ornith",
    "LLM_API_KEY_FILE_HOST": "/srv/keys/vllm",
}


def _llm_cfg(enabled, tier):
    cfg = _config("settings-defaults.ini")
    cfg.values["ai_services"].update(enabled=tier, llm_enabled=enabled, host="10.9.9.9",
                                     vllm_api_key_file="/srv/keys/vllm")
    return cfg


def test_enabled_model_servers_render_every_endpoint_from_ai_services():
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(_llm_cfg("true", "true"))
    assert {key: env[key] for key in LLM_ENABLED_ENV} == LLM_ENABLED_ENV


def test_the_ports_of_ai_services_move_the_endpoints():
    cfg = _llm_cfg("true", "true")
    cfg.values["ai_services"].update(vllm_port="9001", vllm_structured_port="9002",
                                     chat_vllm_port="9003")
    env = deploy.render_llm_env(cfg)
    assert env["LLM_BASE_URL"] == "http://10.9.9.9:9001/v1"
    assert env["CHAT_CLASSIFIER_URL"] == "http://10.9.9.9:9002"
    assert env["LLM_QUALITY_BASE_URL"] == "http://10.9.9.9:9003/v1"


@pytest.mark.parametrize(("enabled", "tier"), [("false", "true"), ("false", "false"),
                                               ("true", "false")])
def test_disabled_model_servers_render_no_endpoint(enabled, tier):
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(_llm_cfg(enabled, tier))
    for name in deploy.LLM_ENDPOINT_VARS:
        assert env[name] == "", name
    assert env["LLM_SEND_TEMPERATURE"] == "false"
    assert "LLM_API_KEY_FILE_HOST" not in env
    assert not any(value.startswith("https://") for value in env.values()
                   if isinstance(value, str))


@pytest.mark.parametrize("fixture_name", ["llm-selfhosted.ini", "provider-off.ini"])
def test_no_model_servers_get_no_chat_classifier(fixture_name):
    assert _env(fixture_name)["CHAT_CLASSIFIER_URL"] == ""


def test_a_retired_cloud_provider_file_is_refused():
    with pytest.raises(deploy.DeployError) as refused:
        deploy.Config(SCHEMA / "retired-cloud-provider.ini")
    message = str(refused.value)
    assert "[ai_services] llm_selfhosted is removed. Use [ai_services] llm_enabled." in message
    assert "[llm_provider.nvidia] is removed. hoover4 uses only its self-hosted model " \
        "servers." in message
    assert "test-cloud-model" not in message and "api.example.test" not in message


#: The removed model settings of plan table D2, D2a and G9, with the text each one gets.
REMOVED_MODEL_SETTINGS = {
    "[ai_services] llm_selfhosted": "Use [ai_services] llm_enabled.",
    "[ai_services] chat_llm_selfhosted": "Use [ai_services] llm_enabled.",
    "[ai_services] hf_token_file": "No setting replaces it. Delete it.",
    "[llm_provider.selfhosted]": "Use [ai_services] llm_enabled.",
    "[llm_provider.nvidia]": "hoover4 uses only its self-hosted model servers.",
    "[llm_provider.moonshot]": "hoover4 uses only its self-hosted model servers.",
}


def test_every_removed_model_setting_is_refused_with_its_replacement():
    path = SCHEMA / "removed-model-settings.ini"
    with pytest.raises(deploy.DeployError) as refused:
        deploy.Config(path)
    message = str(refused.value)
    fixed = [line.split("=")[0].strip() for line in path.read_text().splitlines()
             if line.startswith(("vllm_", "chat_vllm_"))]
    assert len(fixed) == 31
    assert "has %d configuration problems" % (len(fixed) + len(REMOVED_MODEL_SETTINGS)) \
        in message
    for key in fixed:
        assert ("[ai_services] %s is removed. deploy.py sets this value for the supported "
                "model servers. Delete it." % key) in message
    for label, text in REMOVED_MODEL_SETTINGS.items():
        assert "%s is removed. %s" % (label, text) in message
    for port in ("vllm_port", "vllm_structured_port", "chat_vllm_port", "vllm_api_key_file"):
        assert port in deploy.DEFAULTS["ai_services"]


#: The settings that the fixed services and models replace, with the text each one gets.
REMOVED_SERVICE_SETTINGS = {
    "[main_services] garage_capacity": "Use [storage] garage_capacity.",
    "[main_services] ner_provider": "Use [ai_services] ner_enabled.",
    "[main_services] embeddings_provider": "Use [ai_services] embeddings_enabled.",
    "[main_services] testdata_dir": "Use a [dataset_mount.<name>] section",
    "[main_services] datasets_mount_path": "Use a [dataset_mount.<name>] section",
    "[cluster]": "Give the registry address to main_services/ops/publish-images.sh",
}
NO_REPLACEMENT = (
    "[ai_services] embeddings_model", "[ai_services] embeddings_dim",
    "[ai_services] reranker_model", "[ai_services] half_precision",
    "[ai_services] torch_compile", "[main_services] embeddings_cpu_port",
    "[main_services] gpu_fallback", "[main_services] agent_compaction_model",
    "[main_services] cassandra_version", "[main_services] elasticsearch_version",
    "[main_services] temporal_version", "[main_services] temporal_ui_version",
    "[main_services] garage_version", "[main_services] garage_image_digest",
)


def test_every_removed_service_setting_is_refused_with_its_replacement():
    path = SCHEMA / "removed-service-settings.ini"
    with pytest.raises(deploy.DeployError) as refused:
        deploy.Config(path)
    message = str(refused.value)
    assert "has %d configuration problems" % (
        len(REMOVED_SERVICE_SETTINGS) + len(NO_REPLACEMENT)) in message
    for label, text in REMOVED_SERVICE_SETTINGS.items():
        assert "%s is removed. %s" % (label, text) in message
    for label in NO_REPLACEMENT:
        assert "%s is removed. No setting replaces it. Delete it." % label in message
    for value in ("small-model", "corpus-7f3a", "registry-9c2e", "866bd13e"):
        assert value not in message
    assert "temporal_history_shards" in deploy.DEFAULTS["main_services"]


#: The OCR language settings that automatic OCR replaces, with the start of each text.
REMOVED_OCR_SETTINGS = {
    "[main_services] tesseract_languages": "Automatic OCR chooses the Tesseract model",
    "[ai_services] easyocr_languages": "Automatic OCR chooses the EasyOCR languages",
    "[operations] change_ocr_languages_cap": "A new OCR language change is refused",
}


def test_the_ocr_language_settings_are_refused_and_not_rendered():
    with pytest.raises(deploy.DeployError) as refused:
        deploy.Config(SCHEMA / "removed-ocr-settings.ini")
    message = str(refused.value)
    assert "has %d configuration problems" % len(REMOVED_OCR_SETTINGS) in message
    for label, text in REMOVED_OCR_SETTINGS.items():
        assert "%s is removed. %s" % (label, text) in message
    for value in ("en+ru", "eng+deu"):
        assert value not in message
    for source in ("settings-defaults.ini", "gpu-on.ini"):
        env = _env(source)
        assert "TESSERACT_LANGUAGES" not in env and "EASYOCR_LANGUAGES" not in env
        assert "change_ocr_languages=" not in env["HOOVER4_OPERATION_CAPS"]
        assert "EASYOCR_LANGUAGES" not in deploy.render_ai_env(_config(source))


def test_the_moved_garage_capacity_is_rendered_from_storage():
    cfg = _config("settings-defaults.ini")
    assert _env("settings-defaults.ini")["GARAGE_CAPACITY"] == "300G"
    cfg.values["storage"]["garage_capacity"] = "2T"
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda h: h):
        assert deploy.render_main_env(cfg)["GARAGE_CAPACITY"] == "2T"
    assert deploy.REMOVED_SETTINGS[("main_services", "garage_capacity")] == (
        "Use [storage] garage_capacity.")


#: The service images that the compose file and VOLUMES write as literals.
FIXED_SERVICE_IMAGES = {
    "temporal-cassandra": "cassandra:3.11.9",
    "temporal-elasticsearch": "elasticsearch:7.17.27",
    "temporal": "temporalio/auto-setup:1.23.1",
    "temporal-ui": "temporalio/ui:2.26.2",
    "garage": "dxflrs/garage:v2.3.0@sha256:"
              "866bd13ed2038ba7e7190e840482bc27234c4afaf77be8cfa439ae088c1e4690",
}


def test_the_service_images_are_literals_of_compose_and_volumes():
    services = dict(_compose_documents())["docker-compose.yaml"]["services"]
    for service, image in FIXED_SERVICE_IMAGES.items():
        assert services[service]["image"] == image, service
    assert services["garage-init"]["build"]["args"]["GARAGE_IMAGE"] == FIXED_SERVICE_IMAGES["garage"]
    volumes = {row.name: deploy.resolve_image(row.image, {}) for row in deploy.VOLUMES
               if row.side == "main"}
    assert volumes["temporal_cassandra"] == FIXED_SERVICE_IMAGES["temporal-cassandra"]
    assert volumes["temporal_elasticsearch"] == FIXED_SERVICE_IMAGES["temporal-elasticsearch"]
    assert volumes["garage_data"] == FIXED_SERVICE_IMAGES["temporal-cassandra"]
    dockerfile = (REPO_ROOT / "main_services/ops/docker/garage/Dockerfile").read_text()
    assert "ARG GARAGE_IMAGE=%s\n" % FIXED_SERVICE_IMAGES["garage"] in dockerfile


def test_the_chat_control_folder_is_rendered_only_when_set(tmp_path):
    env = _env("settings-defaults.ini")
    assert "HOOVER4_CHAT_CONTROL_DIR" not in env and "HOOVER4_CHAT_CONTROL_DIR_HOST" not in env
    cfg = _config("settings-defaults.ini")
    cfg.values["main_services"]["chat_control_dir"] = str(tmp_path)
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        env = deploy.render_main_env(cfg)
    assert env["HOOVER4_CHAT_CONTROL_DIR_HOST"] == str(tmp_path)
    assert env["HOOVER4_CHAT_CONTROL_DIR"] == "/control"


@pytest.mark.parametrize("value", ["relative/folder", "/no/such/folder"])
def test_a_chat_control_folder_that_is_not_an_absolute_folder_is_refused(value):
    cfg = _config("settings-defaults.ini")
    cfg.values["main_services"]["chat_control_dir"] = value
    with mock.patch.object(deploy, "fail", side_effect=SystemExit) as fail, \
            mock.patch.object(deploy, "container_reachable_host", side_effect=lambda host: host):
        with pytest.raises(SystemExit):
            deploy.render_main_env(cfg)
    assert "chat_control_dir" in fail.call_args.args[0]


def test_the_worker_receives_the_chat_classifier_and_the_control_folder():
    worker = dict(_compose_documents())["docker-compose.yaml"]["services"]["hoover4-worker"]
    assert "CHAT_CLASSIFIER_URL=${CHAT_CLASSIFIER_URL:-}" in worker["environment"]
    assert "HOOVER4_CHAT_CONTROL_DIR=${HOOVER4_CHAT_CONTROL_DIR:-}" in worker["environment"]
    assert "${HOOVER4_CHAT_CONTROL_DIR_HOST:-/dev/null}:/control:ro" in worker["volumes"]


@pytest.mark.parametrize("template_name", ["hoover4.ini.development", "hoover4.ini.release"])
def test_the_templates_carry_the_slots_and_the_provider_temperature_rule(template_name):
    cfg = _template(template_name)
    main = cfg.values["main_services"]
    assert [main[f"{tier}_concurrency"] for tier in
            ("chat_model", "chat_low_latency", "agent_tool")] == ["3", "4", "16"]
    assert "research_concurrency" not in main
    assert main["agent_queue_wait_seconds"] == "5400"
    assert main["llm_request_timeout_seconds"] == "3600"
    assert "chat_run_timeout_seconds" not in main and "plan_run_timeout_seconds" not in main
    assert main["agent_max_output_tokens"] == "32768"
    assert not any(section.startswith("llm_provider.") for section in cfg.values)


def test_the_worker_and_both_agents_receive_the_model_variables():
    documents = dict(_compose_documents())
    worker = documents["docker-compose.yaml"]["services"]["hoover4-worker"]["environment"]
    for name in WORKER_TIMEOUT_VARS:
        assert f"{name}=${{{name}:-}}" in worker, name
    assert "LLM_SEND_TEMPERATURE=${LLM_SEND_TEMPERATURE:-true}" in worker
    agents = documents["research-agents.yaml"]["services"]
    defaults = {"LLM_STREAMING": "true", "LLM_SEND_TEMPERATURE": "true"}
    for service in ("hoover4-internal-search-agent", "hoover4-full-research-agent"):
        environment = agents[service]["environment"]
        for name in AGENT_MODEL_VARS:
            assert f"{name}=${{{name}:-{defaults.get(name, '')}}}" in environment, (
                service, name)
        for name in REMOVED_THINKING_VARS:
            assert not any(line.startswith(f"{name}=") for line in environment), (
                service, name)


# ---- the model server ---------------------------------------------------------------

VLLM_DEFAULT_ENV = {
    "LLM_SERVED_NAME": "dgemma",
    "VLLM_PORT": "21960",
    "VLLM_STRUCTURED_PORT": "21963",
    "VLLM_BUILD_REPO": "https://github.com/mmastrac/djev-spark.git",
    "VLLM_BUILD_REF": "08b708e51bb8d9f4eba0e85b61dab0be7093d20e",
    "VLLM_GPU_FRACTION": "0.24",
    "VLLM_MAX_MODEL_LEN": "262144",
    "VLLM_MAX_NUM_SEQS": "4",
    "VLLM_KV_CACHE_GB": "6",
    "VLLM_HEADROOM_GB": "4",
    "VLLM_TRANSIENT_COPIES": "2",
    "VLLM_TORCH_MEM_FRACTION": "0.85",
    "VLLM_MEM_LIMIT": "40g",
    "VLLM_ATTENTION_BACKEND": "TRITON_ATTN",
    "VLLM_CANVAS": "256",
    "VLLM_CANVAS_SCHEDULE": "[[1, 2, 256], [3, 6, 128], [7, 32, 64]]",
    "VLLM_MAX_SAMPLES": "32",
    "VLLM_TOOL_PARSER": "gemma4",
    "VLLM_REASONING_PARSER": "gemma4",
    "VLLM_BASE_RELEASE": "v0.31.0",
    "VLLM_TLS_PORT": "0",
    "VLLM_TEST_PAGE": "1",
    "VLLM_CONSTRAINED": "1",
    "VLLM_ENGINE_SAMPLES": "1",
    "VLLM_USE_V2_MODEL_RUNNER": "1",
    "VLLM_MAX_JOBS": "4",
    "VLLM_FLASHINFER_NVCC_THREADS": "2",
    "CHAT_VLLM_PORT": "21964",
    "CHAT_VLLM_SERVED_NAME": "ornith",
    "CHAT_VLLM_GPU_FRACTION": "0.30",
    "CHAT_VLLM_MAX_MODEL_LEN": "262144",
    "CHAT_VLLM_MAX_NUM_SEQS": "4",
    "CHAT_VLLM_MEM_LIMIT": "48g",
    "CHAT_VLLM_ARGS": ("--kv-cache-dtype fp8 --enable-prefix-caching --enable-chunked-prefill "
                       "--reasoning-parser qwen3 --enable-auto-tool-choice "
                       "--tool-call-parser qwen3_coder --speculative-config "
                       '{"method":"mtp","num_speculative_tokens":3}'),
}

VLLM_DEFAULT_EXTRA_ARGS = (
    '--no-language-model-only --mm-processor-kwargs {"max_soft_tokens":1120} '
    '--limit-mm-per-prompt {"image":7} '
    '--default-chat-template-kwargs {"enable_thinking":true} '
    '--load-format fastsafetensors'
)


@pytest.mark.parametrize("source", ["settings-defaults.ini", "hoover4.ini.development",
                                    "hoover4.ini.release"])
def test_the_model_server_keys_render_their_defaults(source):
    cfg = (deploy.Config(FIXTURES / source) if source == "settings-defaults.ini"
           else _template(source))
    env = deploy.render_ai_env(cfg)

    assert {key: env[key] for key in VLLM_DEFAULT_ENV} == VLLM_DEFAULT_ENV
    assert env["VLLM_EXTRA_ARGS"] == VLLM_DEFAULT_EXTRA_ARGS
    assert "VLLM_IMAGE" not in env


def test_the_model_server_values_render_whether_or_not_the_servers_are_enabled():
    on = _llm_cfg("true", "true")
    off = _llm_cfg("false", "false")
    assert {key: deploy.render_ai_env(on)[key] for key in VLLM_DEFAULT_ENV} == \
        {key: deploy.render_ai_env(off)[key] for key in VLLM_DEFAULT_ENV} == VLLM_DEFAULT_ENV
    assert deploy.render_ai_env(on)["VLLM_API_KEY_FILE_HOST"] == "/srv/keys/vllm"


def test_the_fingerprint_changes_with_a_fixed_model_value(monkeypatch):
    cfg = _config("settings-defaults.ini")
    before = cfg.ai_fingerprint()
    monkeypatch.setitem(deploy.DGEMMA_ENV, "VLLM_KV_CACHE_GB", "7")
    assert cfg.ai_fingerprint() != before
    monkeypatch.setitem(deploy.DGEMMA_ENV, "VLLM_KV_CACHE_GB", "6")
    assert cfg.ai_fingerprint() == before
    monkeypatch.setattr(deploy, "MODEL_SERVERS",
                        (deploy.DGEMMA._replace(revision="0" * 40), deploy.ORNITH))
    assert cfg.ai_fingerprint() != before


def test_the_fingerprint_holds_no_key_file_path():
    cfg = _config("settings-defaults.ini")
    before = cfg.ai_fingerprint()
    cfg.values["ai_services"]["vllm_api_key_file"] = "/srv/keys/vllm"
    assert cfg.ai_fingerprint() == before
    env = deploy.render_ai_env(cfg)
    assert env["HOOVER4_CONFIG_FINGERPRINT"] == deploy.render_main_env(
        cfg, lambda host: host)["HOOVER4_CONFIG_FINGERPRINT"] == before


def test_the_model_server_folders_replace_the_huggingface_cache():
    rows = {row.name: row for row in deploy.VOLUMES if row.image_service == "hoover4-vllm"}
    assert sorted(rows) == ["dgemma_cache", "dgemma_model"]
    assert all(row.reset_class == "cache" for row in rows.values())
    assert "vllm_huggingface_cache" not in {row.name for row in deploy.VOLUMES}


def test_the_model_server_publishes_both_ports():
    cfg = _config("settings-defaults.ini")
    cfg.values["ai_services"].update(enabled="true", llm_enabled="true")
    ports = deploy.expected_ports(cfg, "ai")
    assert [port for svc, port in ports if svc == "hoover4-vllm"] == [21960, 21963]
    assert [port for svc, port in ports if svc == "hoover4-vllm-chat"] == [21964]
    overlays = deploy.selected_overlays(cfg, "ai")
    assert "compose/vllm.yaml" in overlays and "compose/vllm-chat.yaml" in overlays
    cfg.values["ai_services"]["llm_enabled"] = "false"
    overlays = deploy.selected_overlays(cfg, "ai")
    assert "compose/vllm.yaml" not in overlays and "compose/vllm-chat.yaml" not in overlays
    assert not [svc for svc, _port in deploy.expected_ports(cfg, "ai") if "vllm" in svc]


def test_the_chat_model_server_starts_after_the_healthy_dgemma_server():
    documents = dict(_ai_compose_documents())
    chat = documents["ai_services/vllm-chat.yaml"]["services"]["hoover4-vllm-chat"]
    assert chat["depends_on"] == {"hoover4-vllm": {"condition": "service_healthy"}}
    assert "healthcheck" in documents["ai_services/vllm.yaml"]["services"]["hoover4-vllm"]
    env = deploy.render_ai_env(_config("settings-defaults.ini"))
    used = set(re.findall(r"(?<!\$)\$\{([A-Z0-9_]+)", str(chat)))
    assert used - {"AI_BIND_IP", "VLLM_API_KEY_FILE_HOST"} <= set(env)


def test_the_model_server_service_reads_the_rendered_names():
    service = dict(_ai_compose_documents())["ai_services/vllm.yaml"]["services"]["hoover4-vllm"]
    env = deploy.render_ai_env(_config("settings-defaults.ini"))
    import re
    # `$${NAME}` is the shell's own variable, which compose does not interpolate.
    used = set(re.findall(r"(?<!\$)\$\{([A-Z0-9_]+)", str(service)))
    optional = {"AI_BIND_IP", "VLLM_API_KEY_FILE_HOST"}
    assert used - optional <= set(env), sorted(used - optional - set(env))
    assert service["image"] == "hoover4-vllm-dgemma:${VLLM_BASE_RELEASE}-${VLLM_BUILD_REF}"
    assert service["build"]["context"] == "${HOOVER4_REPO_ROOT}/ai_services/dgemma/vllm-image"
    assert service["build"]["args"] == {
        "VLLM_BASE_RELEASE": "${VLLM_BASE_RELEASE}",
        "VLLM_BUILD_REPO": "${VLLM_BUILD_REPO}",
        "VLLM_BUILD_REF": "${VLLM_BUILD_REF}"}
    assert service["ulimits"] == {"core": 0}


def _weights(folder, shards, index=True, revision=None):
    """Write a checkpoint folder. With a revision, write the download metadata that
    huggingface_hub writes for a `local_dir` download: commit, ETag and time."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text("{}")
    names = ["config.json"] + list(shards)
    if index:
        weight_map = {"w%d" % i: name for i, name in enumerate(shards)}
        (folder / "model.safetensors.index.json").write_text(
            deploy.json.dumps({"weight_map": weight_map}))
        names.append("model.safetensors.index.json")
    for name in shards:
        (folder / name).write_bytes(b"x")
    if revision:
        _metadata(folder, names, revision)


def _metadata(folder, names, revision):
    meta = folder / ".cache" / "huggingface" / "download"
    meta.mkdir(parents=True, exist_ok=True)
    for name in names:
        (meta / (name + ".metadata")).write_text("%s\n\"etag\"\n1793000000.0\n" % revision)


def test_complete_weights_are_found(tmp_path):
    _weights(tmp_path, ["a.safetensors", "b.safetensors"])
    assert deploy.weights_complete(tmp_path)


def test_weights_without_config_are_incomplete(tmp_path):
    _weights(tmp_path, ["a.safetensors"])
    (tmp_path / "config.json").unlink()
    assert not deploy.weights_complete(tmp_path)


def test_weights_with_a_missing_shard_are_incomplete(tmp_path):
    _weights(tmp_path, ["a.safetensors", "b.safetensors"])
    (tmp_path / "b.safetensors").unlink()
    assert not deploy.weights_complete(tmp_path)


def test_weights_with_an_empty_shard_are_incomplete(tmp_path):
    _weights(tmp_path, ["a.safetensors"])
    (tmp_path / "a.safetensors").write_bytes(b"")
    assert not deploy.weights_complete(tmp_path)


def test_an_empty_folder_has_no_weights(tmp_path):
    assert not deploy.weights_complete(tmp_path / "missing")


def test_the_download_is_pinned_and_mounts_no_token():
    cfg = _config("settings-defaults.ini")
    cmd = deploy.dgemma_download_command(cfg, "/v/dgemma_model", deploy.DGEMMA)
    assert cmd[:3] == ["run", "--rm", "--entrypoint"]
    assert "/v/dgemma_model:/models/weights" in cmd
    assert not any("hf_token" in part for part in cmd)
    assert "M=nvidia/diffusiongemma-26B-A4B-it-NVFP4" in cmd
    assert "R=ec4ff3df205028f4e81c954c2227f9312b3ec2ea" in cmd
    assert "hoover4-vllm-dgemma:v0.31.0-08b708e51bb8d9f4eba0e85b61dab0be7093d20e" in cmd
    assert "revision=os.environ['R']" in cmd[-1] and "token" not in cmd[-1]
    chat = deploy.dgemma_download_command(cfg, "/v/chat_model", deploy.ORNITH)
    assert "/v/chat_model:/models/weights" in chat
    assert "M=ornith-ai/Ornith-1.5-35B-A3B-NVFP4" in chat
    assert "R=94e431d9cc47fa1986a7a1a4e9a80f7f118b03aa" in chat
    assert "hf_token_file" not in deploy.DEFAULTS["ai_services"]


def test_the_enabled_model_servers_render_the_pinned_identities():
    assert deploy.DGEMMA == ("nvidia/diffusiongemma-26B-A4B-it-NVFP4",
                             "ec4ff3df205028f4e81c954c2227f9312b3ec2ea", "dgemma",
                             "dgemma_model")
    assert deploy.ORNITH == ("ornith-ai/Ornith-1.5-35B-A3B-NVFP4",
                             "94e431d9cc47fa1986a7a1a4e9a80f7f118b03aa", "ornith",
                             "chat_model")
    ai = deploy.render_ai_env(_llm_cfg("true", "true"))
    assert ai["LLM_SERVED_NAME"] == "dgemma" and ai["CHAT_VLLM_SERVED_NAME"] == "ornith"


def test_the_model_server_image_is_tagged_by_release_and_commit():
    cfg = _config("settings-defaults.ini")
    assert deploy.dgemma_image(cfg) == (
        "hoover4-vllm-dgemma:v0.31.0-08b708e51bb8d9f4eba0e85b61dab0be7093d20e")


def _ai_up(monkeypatch, build, present):
    """Run compose_up of the ai side with the model server overlay and the given images
    present. Returns the names of the images built and whether compose built."""
    cfg = _config("settings-defaults.ini")
    built, composed = [], []
    monkeypatch.setattr(deploy, "compose_files", lambda c, side: ["base.yaml"])
    monkeypatch.setattr(deploy, "selected_overlays", lambda c, side: ["compose/vllm.yaml"])
    monkeypatch.setattr(deploy, "ensure_dgemma_weights", lambda c, r, server: None)
    monkeypatch.setattr(deploy, "_image_exists", lambda r, image: image in present)

    def run(cmd, env=None):
        if "build" in cmd and "-t" in cmd:
            built.append(cmd[cmd.index("-t") + 1])
        elif "build" in cmd:
            composed.append(cmd)
    monkeypatch.setattr(deploy, "run_or_fail", run)
    rt = mock.Mock()
    rt.name, rt.engine = "docker", "/usr/bin/docker"
    rt.compose_prefix.return_value = ["docker", "compose"]
    deploy.compose_up(cfg, "ai", rt, build)
    return built, bool(composed)


def test_a_present_served_image_is_not_built_without_build(monkeypatch):
    cfg = _config("settings-defaults.ini")
    served = deploy.dgemma_image(cfg)
    assert _ai_up(monkeypatch, False, {served}) == ([], False)
    # A missing served image is built by compose, and no image is built by tag.
    assert _ai_up(monkeypatch, False, set()) == ([], True)
    assert _ai_up(monkeypatch, True, {served}) == ([], True)


def test_the_patches_of_the_model_server_image_are_in_the_build_folder():
    folder = deploy.REPO_ROOT / "ai_services" / "dgemma" / "vllm-image"
    dockerfile = (folder / "Dockerfile").read_text()
    assert "FROM vllm/vllm-openai:${VLLM_BASE_RELEASE}" in dockerfile
    for line in dockerfile.splitlines():
        if line.startswith("COPY ") and not line.startswith("COPY --from="):
            for name in line.split()[1:-1]:
                assert (folder / name).is_file(), line


DGEMMA_REVISION = "ec4ff3df205028f4e81c954c2227f9312b3ec2ea"


def test_weights_at_the_pinned_commit_start_no_download(tmp_path):
    cfg = _storage(tmp_path)
    _weights(tmp_path / "dgemma_model", ["a.safetensors"], revision=DGEMMA_REVISION)
    rt = mock.Mock()
    deploy.ensure_dgemma_weights(cfg, rt, deploy.DGEMMA)
    rt.run.assert_not_called()


@pytest.mark.parametrize("revision", [None, "0" * 40], ids=["no-metadata", "other-commit"])
def test_complete_weights_of_another_commit_are_downloaded_again(tmp_path, revision):
    cfg = _storage(tmp_path)
    folder = tmp_path / "dgemma_model"
    _weights(folder, ["a.safetensors"], revision=revision)
    other = tmp_path / "chat_model"
    _weights(other, ["c.safetensors"], revision="1" * 40)
    rt = mock.Mock()

    def download(cmd):
        # The pinned download replaces each file that differs and records the commit.
        assert "R=%s" % DGEMMA_REVISION in cmd
        _metadata(folder, ["config.json", "a.safetensors", "model.safetensors.index.json"],
                  DGEMMA_REVISION)
        return subprocess.CompletedProcess(cmd, 0)
    rt.run.side_effect = download
    deploy.ensure_dgemma_weights(cfg, rt, deploy.DGEMMA)
    rt.run.assert_called_once()
    assert (folder / "a.safetensors").read_bytes() == b"x"
    # The other server's folder is not touched.
    assert deploy.downloaded_revision(other, "c.safetensors") == "1" * 40


def test_one_file_of_another_commit_starts_the_download(tmp_path):
    folder = tmp_path / "dgemma_model"
    _weights(folder, ["a.safetensors", "b.safetensors"], revision=DGEMMA_REVISION)
    assert deploy.weights_match(folder, DGEMMA_REVISION)
    _metadata(folder, ["b.safetensors"], "0" * 40)
    assert deploy.weights_complete(folder)
    assert not deploy.weights_match(folder, DGEMMA_REVISION)


def test_an_interrupted_download_resumes_on_the_next_deploy(tmp_path):
    cfg = _storage(tmp_path)
    folder = tmp_path / "dgemma_model"
    _weights(folder, ["a.safetensors", "b.safetensors"], revision=DGEMMA_REVISION)
    (folder / "b.safetensors").unlink()
    partial = folder / ".cache" / "huggingface" / "download" / "b.safetensors.incomplete"
    partial.write_bytes(b"x")
    rt = mock.Mock()
    rt.run.return_value = subprocess.CompletedProcess([], 1)
    with pytest.raises(deploy.DeployError) as refused:
        deploy.ensure_dgemma_weights(cfg, rt, deploy.DGEMMA)
    assert "incomplete or at another commit" in str(refused.value)
    assert "--ai-services again" in str(refused.value)
    # The partial file and the complete shard stay for the next run.
    assert partial.exists() and (folder / "a.safetensors").exists()

    def resume(cmd):
        (folder / "b.safetensors").write_bytes(b"x")
        partial.unlink()
        return subprocess.CompletedProcess(cmd, 0)
    rt = mock.Mock()
    rt.run.side_effect = resume
    deploy.ensure_dgemma_weights(cfg, rt, deploy.DGEMMA)
    rt.run.assert_called_once()
    assert deploy.weights_match(folder, DGEMMA_REVISION)


def test_a_download_that_leaves_the_folder_incomplete_halts(tmp_path):
    cfg = _storage(tmp_path)
    rt = mock.Mock()
    rt.run.return_value = subprocess.CompletedProcess([], 0)
    with pytest.raises(deploy.DeployError) as refused:
        deploy.ensure_dgemma_weights(cfg, rt, deploy.DGEMMA)
    assert "incomplete" in str(refused.value)
    rt.run.assert_called_once()


def test_both_model_servers_get_their_weights_before_up(monkeypatch):
    cfg = _llm_cfg("true", "true")
    calls = []
    monkeypatch.setattr(deploy, "compose_files", lambda c, side: ["base.yaml"])
    monkeypatch.setattr(deploy, "ensure_dgemma_image", lambda c, r: calls.append("image"))
    monkeypatch.setattr(deploy, "ensure_dgemma_weights",
                        lambda c, r, server: calls.append(server.served_name))
    monkeypatch.setattr(deploy, "run_or_fail", lambda cmd, env=None: calls.append("up"))
    monkeypatch.setattr(deploy, "compose_command", lambda c, side, rt, args: args)
    rt = mock.Mock()
    rt.name = "docker"
    deploy.compose_up(cfg, "ai", rt, False)
    assert calls == ["image", "dgemma", "ornith", "up"]


def test_tika_config_limits_and_slots():
    import json
    cfg = _config("settings-defaults.ini")
    config = json.loads(deploy.render_tika_config(cfg))
    assert config["pipes"]["numClients"] == 4
    assert config["pipes"]["forkedJvmArgs"] == [
        "-Xmx1g",
        "-Djdk.xml.maxGeneralEntitySizeLimit=20000000",
        "-Djdk.xml.totalEntitySizeLimit=20000000",
    ]
    assert config["pipes"]["maxWaitForClientMillis"] == 60000
    assert config["server"]["allowPerRequestConfig"] is False
    limits = config["parse-context"]["output-limits"]
    assert limits == {"writeLimit": 20000000, "throwOnWriteLimit": True}
    assert limits["writeLimit"] * 4 + 1024 ** 2 < 100 * 1024 ** 2
    assert deploy.render_main_env(cfg)["HOOVER4_TIKA_CONCURRENCY"] == "4"
    assert "compose/tika.yaml" in deploy.selected_overlays(cfg, "main")


@pytest.mark.parametrize("key,value", [("tika_mem_limit", "4G"), ("tika_concurrency", "8")])
def test_tika_refuses_invalid_memory_or_slots(key, value):
    cfg = _config("settings-defaults.ini")
    cfg.values["main_services"][key] = value
    with pytest.raises(deploy.DeployError):
        deploy.render_main_env(cfg)


def test_clickhouse_memory_ratio_is_configurable():
    cfg = deploy.Config(None)
    cfg.values['main_services']['clickhouse_server_memory_ratio'] = '0.65'
    xml = deploy.render_clickhouse_config(cfg)
    assert '<max_server_memory_usage_to_ram_ratio>0.65</max_server_memory_usage_to_ram_ratio>' in xml
    assert '{{' not in xml


@pytest.mark.parametrize('ratio', ['0', '-1', '1.1', 'nan', 'inf', 'text'])
def test_invalid_clickhouse_memory_ratio_is_refused(ratio):
    cfg = deploy.Config(None)
    cfg.values['main_services']['clickhouse_server_memory_ratio'] = ratio
    with pytest.raises(deploy.DeployError):
        deploy.render_clickhouse_config(cfg)


def test_manticore_expansion_limit_is_rendered_and_validated(monkeypatch):
    monkeypatch.setattr(deploy, "container_reachable_host", lambda host: host)
    cfg = _config("settings-defaults.ini")
    assert deploy.render_main_env(cfg)["HOOVER4_MANTICORE_EXPANSION_LIMIT"] == "5000"
    cfg.values["main_services"]["manticore_expansion_limit"] = "0"
    assert deploy.render_main_env(cfg)["HOOVER4_MANTICORE_EXPANSION_LIMIT"] == "0"
    for value in ("-1", "invalid"):
        cfg.values["main_services"]["manticore_expansion_limit"] = value
        with pytest.raises(deploy.DeployError, match="manticore_expansion_limit"):
            deploy.render_main_env(cfg)


@pytest.mark.parametrize("size", ["1G", "2G", "4095M"])
def test_scanner_memory_below_four_gib_is_refused(size):
    cfg = _config("settings-defaults.ini")
    cfg.values["main_services"]["regex_scanner_mem_limit"] = size
    with pytest.raises(deploy.DeployError, match="regex_scanner_mem_limit.*at least 4G"):
        deploy.render_main_env(cfg)


@pytest.mark.parametrize("internet,tor,selected", [(True, True, True), (True, False, False), (False, True, False)])
def test_private_tor_requires_both_switches(internet, tor, selected):
    cfg = _config("settings-defaults.ini")
    cfg.values["main_services"]["internet_tools_enabled"] = str(internet).lower()
    cfg.values["main_services"]["web_tor_enabled"] = str(tor).lower()
    env = deploy.render_main_env(cfg)
    assert ("compose/web-tor.yaml" in deploy.selected_overlays(cfg, "main")) == selected
    assert bool(env["METASEARCH_TOR_ROUTES"]) == selected
    assert env["READ_PAGE_TOR_PROXIES"] == env["METASEARCH_TOR_ROUTES"]
    rt = mock.Mock()
    deploy.stop_disabled_internet_tools(cfg, rt)
    removals = [call.args[0][-1] for call in rt.run.call_args_list]
    assert ("hoover4-web-tor" in removals) == (not selected)


@pytest.mark.parametrize("key", ["browser_reader_tabs", "browser_search_tabs", "browser_queue_limit",
    "browser_read_timeout_seconds", "web_search_concurrency", "web_search_queue_limit",
    "web_search_queue_wait_seconds", "web_search_fetch_budget_seconds"])
def test_web_capacity_refuses_invalid_values(key):
    cfg = _config("settings-defaults.ini")
    for value in ("0", "-1", "1.5", "invalid"):
        cfg.values["main_services"][key] = value
        with pytest.raises(deploy.DeployError, match=key):
            deploy.render_main_env(cfg)


def test_web_configuration_and_private_tor_compose():
    import yaml
    cfg = _config("settings-defaults.ini")
    cfg.values["main_services"]["browser_reader_tabs"] = "7"
    cfg.values["main_services"]["browser_fetch_token_file"] = "/private/token"
    env = deploy.render_main_env(cfg)
    assert env["READER_TAB_SLOTS"] == "7"
    assert env["BROWSER_FETCH_TOKEN_FILE_HOST"] == "/private/token"
    compose = yaml.safe_load((REPO_ROOT / "main_services/ops/docker/compose/web-tor.yaml").read_text())
    service = compose["services"]["hoover4-web-tor"]
    assert not service.get("ports") and service.get("network_mode") != "host"
    assert service["read_only"] is True and service["init"] is True


def test_pdf_part_lists_and_office_preview_slots_have_independent_defaults():
    env = _ocr_pdf_env()
    assert env["HOOVER4_OCR_PDF_FILES_PER_BATCH"] == "4"
    assert env["HOOVER4_PDF_PREVIEW_CONCURRENCY"] == "2"
    changed = _ocr_pdf_env(ocr_pdf_files_per_batch="7", pdf_preview_concurrency="3")
    assert changed["HOOVER4_OCR_PDF_FILES_PER_BATCH"] == "7"
    assert changed["HOOVER4_PDF_PREVIEW_CONCURRENCY"] == "3"


@pytest.mark.parametrize("key", ["ocr_pdf_files_per_batch", "pdf_preview_concurrency"])
def test_pdf_activity_limits_refuse_zero(key):
    with pytest.raises(deploy.DeployError):
        _ocr_pdf_env(**{key: "0"})


# ---- dataset mounts -----------------------------------------------------------------

def _overlay(cfg):
    import yaml

    text = deploy.render_dataset_mounts_overlay(deploy.dataset_mounts(cfg))
    assert text.startswith(deploy.ENV_HEADER)
    return yaml.safe_load(text)["services"]


def _overlay_mounts(services, service):
    return [(v["source"], v["target"], v["read_only"]) for v in services[service]["volumes"]]


def _overlay_env(services, service):
    (entry,) = services[service]["environment"]
    key, value = entry.split("=", 1)
    assert key == "HOOVER4_DATASET_MOUNTS"
    return json.loads(value)


def _mount_sections(cfg, sections):
    for name, fields in sections.items():
        cfg.values["dataset_mount." + name] = dict(fields)
    return cfg


def _template_without_mounts():
    cfg = _template()
    for section in [s for s in cfg.values if s.startswith("dataset_mount.")]:
        del cfg.values[section]
    return cfg


def test_an_ini_without_mount_sections_is_refused():
    _refused(_template_without_mounts(), "no [dataset_mount.<name>] section")
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda h: h), \
            pytest.raises(deploy.DeployError, match="dataset_mount"):
        deploy.render_main_env(_template_without_mounts())


def test_the_testdata_mount_keeps_its_identity_and_names_the_corpus_folder():
    cfg = _template()
    services = _overlay(cfg)
    for service in deploy.DATASET_MOUNT_SERVICES:
        assert _overlay_mounts(services, service) == [
            ("/opt/hoover4-testdata", "/testdata", True)]
        assert _overlay_env(services, service) == [
            {"name": "testdata", "path": "/testdata", "writable": False}]
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda h: h):
        env = deploy.render_main_env(cfg)
    assert env["DATASETS_MOUNT_PATH"] == "/testdata"
    assert env["HOOVER4_TESTDATA_DIR"] == "/opt/hoover4-testdata"


def test_only_a_testdata_mount_names_the_corpus_folder(tmp_path):
    cfg = _mount_sections(_template_without_mounts(), {
        "corpus": {"host_path": str(tmp_path), "container_path": "/data", "writable": "false"}})
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda h: h):
        env = deploy.render_main_env(cfg)
    assert "HOOVER4_TESTDATA_DIR" not in env


def test_the_tracked_compose_files_hold_no_dataset_mount():
    for _side, name, service, source, target in _mounts():
        assert "TESTDATA" not in source and target.split(":")[0] != "/testdata", (name, service)


def test_two_explicit_mounts_render_their_modes_and_the_value(tmp_path):
    corpus = tmp_path / "corpus with space"
    uploads = tmp_path / "uploads"
    corpus.mkdir()
    uploads.mkdir()
    cfg = _mount_sections(_template_without_mounts(), {
        "corpus": {"host_path": str(corpus), "container_path": "/testdata", "writable": "false"},
        "uploads": {"host_path": str(uploads), "container_path": "/uploads", "writable": "true"},
    })
    services = _overlay(cfg)

    for service in deploy.DATASET_MOUNT_SERVICES:
        assert _overlay_mounts(services, service) == [
            (str(corpus), "/testdata", True), (str(uploads), "/uploads", False)]
        assert _overlay_env(services, service) == [
            {"name": "corpus", "path": "/testdata", "writable": False},
            {"name": "uploads", "path": "/uploads", "writable": True},
        ]
    with mock.patch.object(deploy, "container_reachable_host", side_effect=lambda h: h):
        assert deploy.render_main_env(cfg)["DATASETS_MOUNT_PATH"] == "/testdata"
    assert deploy.dataset_mount_refusals(cfg) == []


def test_a_dollar_sign_in_a_path_is_not_interpolated(tmp_path):
    cfg = _mount_sections(deploy.Config(None), {
        "corpus": {"host_path": "/srv/a$HOME:b", "container_path": "/data$x",
                   "writable": "false"},
    })
    services = _overlay(cfg)
    assert _overlay_mounts(services, "hoover4-worker") == [("/srv/a$$HOME:b", "/data$$x", True)]
    entry = services["hoover4-worker"]["environment"][0]
    assert '"path":"/data$$x"' in entry


def test_the_main_side_includes_the_overlay_last():
    cfg = _config("settings-defaults.ini")
    assert deploy.compose_files(cfg, "main")[-1] == str(deploy.DATASET_MOUNTS_OVERLAY)
    assert str(deploy.DATASET_MOUNTS_OVERLAY) not in deploy.compose_files(cfg, "ai")


def test_every_command_writes_the_overlay_before_compose_runs():
    written = []

    def record(path, content):
        written.append(path)
        return False

    cfg = _storage("/srv/hoover4-volumes")
    for argv in (["--down"], ["--reset"], ["--reset-temporal"]):
        written.clear()
        with mock.patch.object(deploy, "load_config", return_value=cfg), \
                mock.patch.object(deploy.shutil, "which", return_value="docker"), \
                mock.patch.object(deploy, "container_reachable_host", side_effect=lambda h: h), \
                mock.patch.object(deploy, "run_preflights") as preflights, \
                mock.patch.object(deploy, "_write_if_changed", side_effect=record), \
                mock.patch.object(deploy, "compose_down"), \
                mock.patch.object(deploy, "compose_reset"), \
                mock.patch.object(deploy, "compose_reset_temporal"):
            preflights.side_effect = lambda *a: written.append("preflights")
            deploy.main(argv)
        assert written.index(deploy.DATASET_MOUNTS_OVERLAY) < written.index("preflights"), argv


def test_every_other_mount_of_the_two_services_is_service_owned():
    targets = set()
    for side, _name, service, _source, target in _mounts():
        if side == "main" and service in deploy.DATASET_MOUNT_SERVICES:
            targets.add(target.split(":")[0])
    assert targets
    for target in targets:
        assert any(deploy._path_within(target, owned) for owned in deploy.SERVICE_OWNED_PATHS), target


def _refused(cfg, *expected):
    with pytest.raises(deploy.DeployError) as refused:
        deploy.dataset_mounts(cfg)
    for text in expected:
        assert text in str(refused.value)


@pytest.mark.parametrize(
    ("name", "fields", "expected"),
    [
        pytest.param("Corpus", {}, ("[dataset_mount.Corpus]", "[a-z0-9_]{1,32}"), id="name-case"),
        pytest.param("a" * 33, {}, ("[a-z0-9_]{1,32}",), id="name-length"),
        pytest.param("corpus", {"host_path": "srv/corpus"},
                     ("[dataset_mount.corpus] host_path", "not an absolute path"), id="host-relative"),
        pytest.param("corpus", {"container_path": "data"},
                     ("[dataset_mount.corpus] container_path", "normalized"), id="container-relative"),
        pytest.param("corpus", {"container_path": "/data/"},
                     ("[dataset_mount.corpus] container_path", "normalized"), id="container-trailing"),
        pytest.param("corpus", {"container_path": "/data/../app"},
                     ("[dataset_mount.corpus] container_path", "normalized"), id="container-dots"),
        pytest.param("corpus", {"container_path": "/app/data"},
                     ("[dataset_mount.corpus] container_path", "overlaps /app"), id="beneath-owned"),
        pytest.param("corpus", {"container_path": "/"},
                     ("[dataset_mount.corpus] container_path", "overlaps"), id="contains-owned"),
        pytest.param("corpus", {"container_path": "/mirror"},
                     ("[dataset_mount.corpus] container_path", "overlaps /mirror"), id="equals-owned"),
        pytest.param("corpus", {"writable": "maybe"},
                     ("[dataset_mount.corpus] writable", "boolean"), id="writable-not-boolean"),
        pytest.param("corpus", {"writable": ""},
                     ("[dataset_mount.corpus] writable", "missing or empty"), id="writable-missing"),
        pytest.param("corpus", {"mode": "ro"},
                     ("[dataset_mount.corpus] mode", "not a dataset mount field"), id="unknown-field"),
    ],
)
def test_each_mount_field_rule_refuses_its_case(tmp_path, name, fields, expected):
    values = {"host_path": str(tmp_path), "container_path": "/data", "writable": "false"}
    values.update(fields)
    _refused(_mount_sections(deploy.Config(None), {name: values}), *expected)


def test_a_missing_host_folder_is_refused_at_start(tmp_path):
    cfg = _mount_sections(_storage("/srv/hoover4-volumes"), {
        "corpus": {"host_path": str(tmp_path / "absent"), "container_path": "/data",
                   "writable": "false"}})
    deploy.dataset_mounts(cfg)
    problems = deploy.start_refusals(cfg, "main")
    assert any("[dataset_mount.corpus] host_path" in p and "not an existing folder" in p
               for p in problems)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param("/data", "/data", id="equal"),
        pytest.param("/data", "/data/inner", id="beneath"),
        pytest.param("/data/inner", "/data", id="contains"),
    ],
)
def test_overlapping_container_paths_are_refused(tmp_path, first, second):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    cfg = _mount_sections(deploy.Config(None), {
        "a": {"host_path": str(tmp_path / "a"), "container_path": first, "writable": "false"},
        "b": {"host_path": str(tmp_path / "b"), "container_path": second, "writable": "true"},
    })
    _refused(cfg, "[dataset_mount.a] container_path", "[dataset_mount.b] container_path", "overlap")


@pytest.mark.parametrize("layout", ["equal", "beneath", "contains", "symlink"])
def test_overlapping_host_folders_are_refused(tmp_path, layout):
    a = tmp_path / "a"
    a.mkdir()
    if layout == "equal":
        b = a
    elif layout == "beneath":
        b = a / "inner"
        b.mkdir()
    elif layout == "contains":
        b = a
        a = a / "inner"
        a.mkdir()
    else:
        b = tmp_path / "alias"
        b.symlink_to(a / "..")
    cfg = _mount_sections(deploy.Config(None), {
        "a": {"host_path": str(a), "container_path": "/data", "writable": "false"},
        "b": {"host_path": str(b), "container_path": "/uploads", "writable": "true"},
    })
    _refused(cfg, "[dataset_mount.a] host_path", "[dataset_mount.b] host_path", "overlap")


def test_the_write_probe_runs_in_both_services_for_each_writable_mount(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    cfg = _mount_sections(deploy.Config(None), {
        "a": {"host_path": str(tmp_path / "a"), "container_path": "/data", "writable": "false"},
        "b": {"host_path": str(tmp_path / "b"), "container_path": "/uploads", "writable": "true"},
    })
    rt = mock.Mock()
    rt.run.return_value = subprocess.CompletedProcess([], 0, "", "")
    deploy.verify_writable_dataset_mounts(cfg, rt)
    calls = [c.args[0] for c in rt.run.call_args_list]
    assert [(c[1], c[-1]) for c in calls] == [
        ("hoover4-worker", "/uploads"), ("hoover4-website", "/uploads")]

    rt.run.return_value = subprocess.CompletedProcess([], 1, "", "Permission denied")
    with pytest.raises(deploy.DeployError) as refused:
        deploy.verify_writable_dataset_mounts(cfg, rt)
    assert "[dataset_mount.b] host_path" in str(refused.value)
    assert "Permission denied" in str(refused.value)


def test_the_write_probe_creates_writes_and_removes_one_file(tmp_path):
    result = subprocess.run(["sh", "-c", deploy.DATASET_MOUNT_PROBE, "sh", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
    tmp_path.chmod(0o500)
    try:
        if os.geteuid() != 0:
            result = subprocess.run(["sh", "-c", deploy.DATASET_MOUNT_PROBE, "sh", str(tmp_path)],
                                    capture_output=True, text=True)
            assert result.returncode != 0
    finally:
        tmp_path.chmod(0o700)


UPLOAD_DEFAULT_ENV = {
    "HOOVER4_UPLOAD_MAX_BATCH_FILES": "10000",
    "HOOVER4_UPLOAD_MAX_BATCH_BYTES": "10737418240",
    "HOOVER4_UPLOAD_MAX_FILE_BYTES": "10737418240",
    "HOOVER4_UPLOAD_CHUNK_BYTES": "786432",
    "HOOVER4_UPLOAD_ABANDON_HOURS": "24",
}


@pytest.mark.parametrize("source", ["settings-defaults.ini", "hoover4.ini.development",
                                    "hoover4.ini.release"])
def test_the_upload_limits_render_their_defaults(source):
    cfg = _config(source) if source.endswith("defaults.ini") else _template(source)
    assert deploy.upload_env(cfg) == UPLOAD_DEFAULT_ENV
    assert "ingest_upload=2" in deploy.operation_caps_value(cfg).split(",")


def test_a_set_upload_limit_renders_and_a_bad_one_is_refused():
    cfg = _config("settings-defaults.ini")
    cfg.values["uploads"].update(chunk_bytes="1048576", abandon_hours="0")
    env = deploy.upload_env(cfg)
    assert (env["HOOVER4_UPLOAD_CHUNK_BYTES"], env["HOOVER4_UPLOAD_ABANDON_HOURS"]) == ("1048576", "0")
    for key, value in [("chunk_bytes", "0"), ("max_batch_files", "many"), ("abandon_hours", "-1")]:
        cfg = _config("settings-defaults.ini")
        cfg.values["uploads"][key] = value
        with pytest.raises(deploy.DeployError) as refused:
            deploy.upload_env(cfg)
        assert "[uploads] %s" % key in str(refused.value)


def test_the_upload_space_is_a_website_volume_with_the_data_reset_class():
    (row,) = [r for r in deploy.VOLUMES if r.name == deploy.UPLOAD_SPACE_VOLUME]
    assert (row.side, row.uid, row.gid, row.reset_class) == ("main", 0, 0, "data")
    mounts = [(service, target) for side, _n, service, source, target in _mounts()
              if source == VOLUMES_SOURCE + deploy.UPLOAD_SPACE_VOLUME]
    assert mounts == [("hoover4-website", "/upload-tmp")]
    assert "/upload-tmp" in deploy.SERVICE_OWNED_PATHS
    cfg = _mount_sections(_config("settings-defaults.ini"), {
        "inside": {"host_path": "/srv/x", "container_path": "/upload-tmp/x", "writable": "true"},
    })
    with pytest.raises(deploy.DeployError, match="overlaps /upload-tmp"):
        deploy.dataset_mounts(cfg)


def test_the_upload_limits_reach_the_website_and_the_worker():
    for _side, _name, document in _all_compose_documents():
        for service in ("hoover4-website", "hoover4-worker"):
            definition = (document.get("services") or {}).get(service)
            if not definition or "build" not in definition:
                continue
            names = {entry.split("=", 1)[0].strip('"') for entry in definition.get("environment") or []}
            assert set(UPLOAD_DEFAULT_ENV) <= names, service


def test_every_writable_compose_mount_prints_a_copy_note(tmp_path):
    cfg = _mount_sections(_storage(tmp_path), {
        "same": {"host_path": str(tmp_path / "same"), "container_path": "/same", "writable": "true"},
        "other": {"host_path": "/dev/shm", "container_path": "/other", "writable": "true"},
        "readonly": {"host_path": "/proc", "container_path": "/readonly", "writable": "false"},
    })
    notes = deploy.upload_space_notes(cfg)
    assert len(notes) == 2
    assert any("[dataset_mount.same]" in note and "copies" in note for note in notes)
    assert any("[dataset_mount.other]" in note and "copies" in note for note in notes)


@pytest.mark.parametrize("source", ["hoover4.ini.development", "hoover4.ini.release"])
def test_the_processing_updates_are_automatic_by_default(source):
    cfg = _template(source)
    assert cfg.get_bool("processing_updates", "automatic")
    caps = deploy.operation_caps_value(cfg).split(",")
    assert "update_dataset=2" in caps and "update_collection=2" in caps
    cfg.values["processing_updates"]["automatic"] = "false"
    assert not cfg.get_bool("processing_updates", "automatic")


# ---- configuration schema and the dry run -------------------------------------------

SCHEMA = FIXTURES / "schema"


def _refusal(path):
    with pytest.raises(deploy.DeployError) as refused:
        deploy.Config(path)
    return str(refused.value)


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        pytest.param("unknown-section.ini", ["[search_tuning] is not a known section."],
                     id="unknown-section"),
        pytest.param("unknown-key.ini", ["[main_services] mystery_key is not a known key.",
                                         "[uploads] max_folder_depth is not a known key."],
                     id="unknown-key"),
        pytest.param("removed-key.ini", [
            "[main_services] research_concurrency is removed. No setting replaces it.",
            "[main_services] agent_packs_subagent is removed. No setting replaces it.",
            "[main_services] agent_max_page_tokens is removed. No setting replaces it.",
        ], id="removed-key"),
        pytest.param("malformed-mount.ini", [
            "[dataset_mount] is not a valid dataset mount section.",
            "[dataset_mount.Bad-Name] is not a valid dataset mount section.",
        ], id="malformed-mount"),
        pytest.param("unknown-mount-key.ini",
                     ["[dataset_mount.corpus] mode is not a dataset mount key."],
                     id="unknown-mount-key"),
        pytest.param("inline-comment.ini", [
            "[main_services] proxy_username has a comment after its value.",
            "[main_services] proxy_groups has a comment after its value.",
            "[main_services] tika_concurrency has a comment after its value.",
            "[main_services] ocr_concurrency has a comment after its value.",
        ], id="inline-comment"),
        pytest.param("several-problems.ini", [
            "[DEFAULT] is not a known section.",
            "[main_services] mystery_key is not a known key.",
            "[main_services] research_concurrency is removed.",
            "[main_services] proxy_groups has a comment after its value.",
            "[search_tuning] is not a known section.",
            "[dataset_mount.corpus] mode is not a dataset mount key.",
        ], id="several-problems"),
        pytest.param("interpolation.ini",
                     ["[main_services] admin_base_url has a % sign that is not written as %%."],
                     id="interpolation"),
    ],
)
def test_the_parser_names_every_structural_problem(fixture_name, expected):
    message = _refusal(SCHEMA / fixture_name)
    assert "%d configuration problem" % len(expected) in message
    for line in expected:
        assert line in message, line
    for value in ("value-e81c", "alice", "note-7f3a", "note-9b21", "note-4c1d", "note-c41d", "note-d52e", "%zz"):
        assert value not in message


def test_the_problems_keep_the_order_of_the_file():
    message = _refusal(SCHEMA / "several-problems.ini")
    positions = [message.index(text) for text in (
        "[DEFAULT]", "mystery_key", "research_concurrency", "proxy_groups",
        "[search_tuning]", "[dataset_mount.corpus] mode")]
    assert positions == sorted(positions)


def test_a_default_section_does_not_fill_the_other_sections(tmp_path):
    with pytest.raises(deploy.DeployError):
        deploy.Config(SCHEMA / "several-problems.ini")
    path = tmp_path / "default-only.ini"
    path.write_text("[DEFAULT]\nvolumes_path = /srv/x\n\n[storage]\n", encoding="utf-8")
    assert "[DEFAULT] is not a known section." in _refusal(path)


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        pytest.param("duplicate-key.ini", "option 'redis_port' in section 'main_services' "
                     "already exists", id="duplicate-key"),
        pytest.param("duplicate-section.ini", "section 'main_services' already exists",
                     id="duplicate-section"),
    ],
)
def test_a_duplicate_is_a_parse_error(fixture_name, expected):
    message = _refusal(SCHEMA / fixture_name)
    assert message.startswith("cannot parse ")
    assert expected in message


def test_full_line_comments_and_marks_inside_a_value_are_accepted():
    cfg = deploy.Config(SCHEMA / "valid-gpu-off.ini")
    assert cfg.get("main_services", "admin_base_url") == (
        "https://hoover.example.test/admin#ops;view=all")


def test_an_omitted_key_keeps_its_default():
    cfg = deploy.Config(SCHEMA / "valid-gpu-off.ini")
    assert cfg.get("main_services", "agent_compaction_fraction") == ""
    assert cfg.get("main_services", "factcheck_api_key_file") == ""
    assert cfg.get("storage", "garage_capacity") == "300G"


class _Boundaries:
    """Replaces every boundary that changes the host or reaches a service. Each call is
    recorded and fails the run."""

    def __init__(self):
        self.calls = []
        self._real_open = builtins.open

    def _forbid(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError("dry run called %s" % name)
        return record

    def _open(self, file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            self.calls.append("open(%s, %s)" % (file, mode))
            raise AssertionError("dry run opened %s for writing" % file)
        return self._real_open(file, mode, *args, **kwargs)

    def patches(self):
        targets = [
            (deploy.subprocess, "run"), (deploy.subprocess, "Popen"),
            (deploy.subprocess, "check_output"), (deploy.subprocess, "call"),
            (deploy.shutil, "which"), (deploy.shutil, "rmtree"),
            (deploy.socket, "socket"), (deploy.socket, "create_connection"),
            (deploy.socket, "getaddrinfo"),
            (deploy.os, "makedirs"), (deploy.os, "mkdir"), (deploy.os, "chown"),
            (deploy.os, "chmod"), (deploy.os, "remove"), (deploy.os, "unlink"),
            (deploy.os, "system"),
            (Path, "mkdir"), (Path, "write_text"), (Path, "write_bytes"), (Path, "touch"),
            (Path, "unlink"),
            (deploy, "Runtime"), (deploy, "_write_if_changed"), (deploy, "write_env_file"),
            (deploy, "create_volume_folders"), (deploy, "write_dataset_mounts_overlay"),
            (deploy, "set_volume_owners"), (deploy, "ensure_network"),
            (deploy, "compose_up"), (deploy, "compose_down"), (deploy, "run_or_fail"),
            (deploy, "container_reachable_host"), (deploy, "local_ip_addresses"),
        ]
        patches = [mock.patch.object(owner, name, side_effect=self._forbid(name))
                   for owner, name in targets]
        patches.append(mock.patch("urllib.request.urlopen",
                                  side_effect=self._forbid("urlopen")))
        patches.append(mock.patch.object(builtins, "open", self._open))
        return patches


#: The files that a deployment renders. A dry run creates and changes none of them.
GENERATED = (
    deploy.MAIN_COMPOSE_DIR / ".env",
    deploy.AI_COMPOSE_DIR / ".env",
    deploy.DATASET_MOUNTS_OVERLAY,
    deploy.TEMPORAL_DYNAMIC_CONFIG_GENERATED,
    deploy.MAIN_COMPOSE_DIR / "nginx-proxy.conf",
    deploy.MAIN_COMPOSE_DIR / "clickhouse-server-config-override.xml",
    deploy.MAIN_COMPOSE_DIR / "tika" / "tika-config.json",
)


def _generated_state():
    return {path: (path.stat().st_mtime_ns if path.exists() else None) for path in GENERATED}


def _run(argv, ini_path, capsys):
    """Run deploy.main with `ini_path` as hoover4.ini and every boundary replaced."""
    boundaries = _Boundaries()
    before = _generated_state()
    with mock.patch.object(deploy, "INI_PATH", Path(ini_path)):
        patches = boundaries.patches()
        for patch in patches:
            patch.start()
        try:
            try:
                code = deploy.main(argv)
            except SystemExit as exc:
                code = exc.code
        finally:
            for patch in reversed(patches):
                patch.stop()
    assert boundaries.calls == []
    assert _generated_state() == before
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.mark.parametrize("fixture_name", ["valid-gpu-off.ini", "valid-gpu-on.ini"])
def test_check_accepts_a_valid_configuration(fixture_name, capsys):
    code, out, err = _run(["--check"], SCHEMA / fixture_name, capsys)
    assert (code, out) == (0, "configuration valid\n"), err


@pytest.mark.parametrize("name", ["hoover4.ini.release", "hoover4.ini.development"])
def test_check_accepts_a_sample_with_a_volumes_path(name, capsys, tmp_path):
    path = tmp_path / "hoover4.ini"
    path.write_text(re.sub(r"(?m)^volumes_path =$", "volumes_path = /srv/hoover4-volumes",
                           (REPO_ROOT / name).read_text(encoding="utf-8")),
                    encoding="utf-8")
    code, out, err = _run(["--check"], path, capsys)
    assert (code, out) == (0, "configuration valid\n"), err


def test_check_accepts_a_valid_configuration_from_the_gpu_host(capsys):
    code, out, _err = _run(["--check", "--ai-services"], SCHEMA / "valid-gpu-on.ini", capsys)
    assert (code, out) == (0, "configuration valid\n")


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        pytest.param("several-problems.ini", [
            "[DEFAULT] is not a known section.",
            "[main_services] mystery_key is not a known key.",
            "[main_services] research_concurrency is removed.",
            "[main_services] proxy_groups has a comment after its value.",
            "[search_tuning] is not a known section.",
            "[dataset_mount.corpus] mode is not a dataset mount key.",
        ], id="several-problems"),
        pytest.param("unknown-section.ini", ["[search_tuning] is not a known section."],
                     id="unknown-section"),
        pytest.param("duplicate-key.ini", ["redis_port"], id="duplicate-key"),
        pytest.param("bad-boolean.ini", ["[main_services] ocr_pdf_enabled must be a boolean"],
                     id="bad-boolean"),
        pytest.param("bad-port.ini", ["[main_services] redis_port must be a port"],
                     id="bad-port"),
        pytest.param("missing-manticore.ini", ["[main_services] manticore_mem_limit is required"],
                     id="missing-manticore"),
    ],
)
def test_check_returns_1_and_names_each_problem(fixture_name, expected, capsys):
    code, out, err = _run(["--check"], SCHEMA / fixture_name, capsys)
    assert code == 1
    assert "configuration valid" not in out
    for line in expected:
        assert line in err, line


def test_check_collects_problems_of_separate_steps(capsys, tmp_path):
    path = tmp_path / "hoover4.ini"
    path.write_text((SCHEMA / "valid-gpu-off.ini").read_text(encoding="utf-8")
                    .replace("volumes_path = /srv/hoover4-volumes", "volumes_path =")
                    .replace("[main_services]\n", "[main_services]\nproxy_username =\n"),
                    encoding="utf-8")
    code, _out, err = _run(["--check"], path, capsys)
    assert code == 1
    assert "has 2 configuration problems" in err
    assert "[storage] volumes_path is empty" in err
    assert "[main_services] proxy_username is empty" in err


def test_check_needs_hoover4_ini_and_reads_no_sample(capsys, tmp_path):
    with mock.patch.object(deploy, "Config", side_effect=AssertionError("Config read")):
        code, out, err = _run(["--check"], tmp_path / "hoover4.ini", capsys)
    assert code == 1
    assert out == ""
    assert "hoover4.ini not found" in err


@pytest.mark.parametrize("flag", ["--print-env", "--print-command", "--build", "--down",
                                  "--reset", "--reset-caches", "--reset-temporal"])
def test_check_refuses_another_action(flag, capsys):
    code, out, err = _run(["--check", flag], SCHEMA / "valid-gpu-off.ini", capsys)
    assert code == 2
    assert out == ""
    assert "--check cannot be used with %s" % flag in err


@pytest.mark.parametrize("argv", [["--print-env"], ["--print-command"],
                                  ["--print-env", "--ai-services"]])
def test_print_modes_refuse_an_invalid_schema(argv, capsys):
    with pytest.raises(deploy.DeployError) as refused:
        _run(argv, SCHEMA / "several-problems.ini", capsys)
    assert "[main_services] mystery_key is not a known key." in str(refused.value)
    assert "[search_tuning] is not a known section." in str(refused.value)


# ---- the tracked samples ------------------------------------------------------------

#: The values that both samples set over DEFAULTS.
SAMPLE_VALUES_OVER_DEFAULTS = {
    ("main_services", "manticore_mem_limit"): "32G",
    ("main_services", "manticore_vectors_mem_limit"): "32G",
    ("main_services", "indexing_workers"): "8",
    ("main_services", "chat_model_concurrency"): "3",
    ("main_services", "chat_low_latency_concurrency"): "4",
    ("main_services", "agent_tool_concurrency"): "16",
    ("main_services", "agent_queue_wait_seconds"): "5400",
    ("main_services", "title_request_timeout_seconds"): "120",
    ("main_services", "board_reason_request_seconds"): "600",
    ("main_services", "llm_request_timeout_seconds"): "3600",
    ("main_services", "agent_max_output_tokens"): "32768",
    ("main_services", "agent_compaction_fraction"): "0.80",
}

#: The keys in which the development sample differs from the release sample, as
#: (release value, development value).
DEVELOPMENT_DIFFERENCES = {
    ("main_services", "website_release_mode"): ("true", "false"),
    ("main_services", "serena_enabled"): ("false", "true"),
    ("main_services", "development_auth_backdoor_enabled"): ("false", "true"),
}

SAMPLE_DIVIDER = re.compile(r"# ---- .+ ----")
SAMPLE_KEY_LINE = re.compile(r"[a-z0-9_]+ =( \S.*)?")
SAMPLE_SECTION_LINE = re.compile(r"\[[a-z0-9_.]+\]")


def _sample_values(name):
    """Every (section, key) of a sample with its value, read as Config reads it."""
    parser = configparser.ConfigParser(inline_comment_prefixes=None, default_section="\n",
                                       interpolation=None)
    with open(REPO_ROOT / name, "r", encoding="utf-8") as fh:
        parser.read_file(fh)
    return {(section, key): parser.get(section, key).strip()
            for section in parser.sections() for key in parser.options(section)}


@pytest.mark.parametrize("name", SAMPLES)
def test_a_sample_uses_only_full_line_comments_and_one_comment_for_each_key(name):
    lines = (REPO_ROOT / name).read_text(encoding="utf-8").splitlines()
    assert ";" not in "\n".join(lines)
    for number, line in enumerate(lines, 1):
        assert (line == "" or line.startswith("# ") or SAMPLE_SECTION_LINE.fullmatch(line)
                or SAMPLE_KEY_LINE.fullmatch(line)), (number, line)
        if SAMPLE_KEY_LINE.fullmatch(line):
            assert "#" not in line, (number, line)
        if SAMPLE_KEY_LINE.fullmatch(line) or SAMPLE_SECTION_LINE.fullmatch(line):
            comments = 0
            while number - 2 - comments >= 0 and lines[number - 2 - comments].startswith("#"):
                comments += 1
            assert comments <= 1, (number, line)
        if SAMPLE_DIVIDER.fullmatch(line):
            # A blank line follows a divider, so the divider is not the comment of a key.
            assert number < len(lines) and lines[number] == "", (number, line)


@pytest.mark.parametrize("name", SAMPLES)
def test_every_sample_section_and_key_is_in_the_schema(name):
    values = _sample_values(name)
    sections = sorted({section for section, _key in values})
    for section in sections:
        assert deploy.Config._section_problem(section) is None, section
    for section, key in values:
        assert deploy.Config._key_problem(section, key) is None, (section, key)
    assert not [setting for setting in deploy.REMOVED_SETTINGS
                if setting in values or (setting[1] is None and setting[0] in sections)]
    mounts = [s for s in sections if s.startswith(deploy.DATASET_MOUNT_SECTION_PREFIX)]
    assert mounts == ["dataset_mount.testdata"]
    assert {key: values[(mounts[0], key)] for key in deploy.DATASET_MOUNT_KEYS} == {
        "host_path": "/opt/hoover4-testdata", "container_path": "/testdata",
        "writable": "false"}


@pytest.mark.parametrize("name", SAMPLES)
def test_a_sample_sets_every_key_of_the_schema(name):
    values = _sample_values(name)
    expected = {(section, key): value for section, keys in deploy.DEFAULTS.items()
                for key, value in keys.items()}
    expected.update(SAMPLE_VALUES_OVER_DEFAULTS)
    for setting, pair in DEVELOPMENT_DIFFERENCES.items():
        expected[setting] = pair[SAMPLES.index(name)]
    assert {setting: value for setting, value in values.items()
            if not setting[0].startswith(deploy.DATASET_MOUNT_SECTION_PREFIX)} == expected
    assert values[("main_services", "internet_tools_enabled")] == "false"
    assert values[("main_services", "web_tor_enabled")] == "true"
    assert values[("storage", "volumes_path")] == ""


def test_the_samples_differ_only_in_the_development_keys():
    release, development = (_sample_values(name) for name in SAMPLES)
    assert set(release) == set(development)
    assert {setting: (release[setting], development[setting]) for setting in release
            if release[setting] != development[setting]} == DEVELOPMENT_DIFFERENCES
