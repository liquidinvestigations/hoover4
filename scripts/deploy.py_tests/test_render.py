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


PACK_KEYS = ("AGENT_PACKS_CHAT", "AGENT_PACKS_SUBAGENT", "AGENT_PACKS_PLANNER",
             "AGENT_PACKS_ORGANIZER")


def test_agent_packs_default_to_all():
    env = _env("settings-defaults.ini")
    assert [env[key] for key in PACK_KEYS] == ["all"] * 4


def test_a_narrowed_agent_pack_value_is_rendered_and_an_empty_one_is_all():
    env = _env("agent-packs.ini")
    assert env["AGENT_PACKS_CHAT"] == "collections,catalogue,conversation"
    assert env["AGENT_PACKS_SUBAGENT"] == "all"
    assert env["AGENT_PACKS_PLANNER"] == "all"


def test_both_research_agents_receive_the_pack_keys():
    agents = dict(_compose_documents())["research-agents.yaml"]["services"]
    for name in ("hoover4-internal-search-agent", "hoover4-full-research-agent"):
        environment = agents[name]["environment"]
        for key in PACK_KEYS:
            assert f"{key}=${{{key}:-all}}" in environment, (name, key)


def test_the_subagent_budgets_default_to_6_and_300():
    env = _env("settings-defaults.ini")
    assert (env["AGENT_SUBAGENT_MAX_PER_TURN"], env["AGENT_PLAN_RUN_BUDGET"]) == ("6", "300")


def test_a_set_subagent_budget_is_rendered_and_an_empty_one_is_the_default():
    env = _env("agent-budgets.ini")
    assert (env["AGENT_SUBAGENT_MAX_PER_TURN"], env["AGENT_PLAN_RUN_BUDGET"]) == ("4", "300")


def test_the_worker_receives_the_subagent_budgets():
    main = dict(_compose_documents())["docker-compose.yaml"]["services"]
    environment = main["hoover4-worker"]["environment"]
    for key, default in (("AGENT_SUBAGENT_MAX_PER_TURN", 6), ("AGENT_PLAN_RUN_BUDGET", 300)):
        assert f"{key}=${{{key}:-{default}}}" in environment, key


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
    assert [env[key] for key in PACK_KEYS] == ["all"] * 4
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
    if name in ("ai_models_cache", "vllm_huggingface_cache", "easyocr_models_cache"):
        return "cache"
    if name in ("temporal_cassandra", "temporal_elasticsearch"):
        return "temporal"
    return "data"


def test_reset_class_of_each_row_is_unchanged():
    for row in deploy.VOLUMES:
        assert row.reset_class == _class_before_folders(row.name), row.name


ENV = {"CASSANDRA_VERSION": "3.11.9", "ELASTICSEARCH_VERSION": "7.17.27"}


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


PROBE_KEYS = ("AGENT_MAX_PAGE_TOKENS", "AGENT_COMPLETION_RESERVE_TOKENS",
              "AGENT_CATALOGUE_MATCH_COUNT")


def test_absent_probe_keys_render_empty():
    env = _env("settings-defaults.ini")
    assert [env[key] for key in PROBE_KEYS] == ["", "", ""]


def test_the_probe_keys_are_rendered():
    env = _env("agent-probe-keys.ini")
    assert [env[key] for key in PROBE_KEYS] == ["12000", "8192", "8"]


@pytest.mark.parametrize("key, value", [
    ("agent_catalogue_match_count", "5"),
    ("agent_catalogue_match_count", "13"),
    ("agent_max_page_tokens", "0"),
    ("agent_completion_reserve_tokens", "many"),
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
