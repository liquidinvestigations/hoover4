"""The operator settings registry, the saved revisions and the apply operations (k3s/platform/operator/settings.py)."""
import json
import multiprocessing
import os
import threading
from pathlib import Path

import pytest

from conftest import FIXTURES, REPO, operator_settings
import compose
import config
import zone_ini

S = operator_settings()
SCOPE = 'hoover:main'


@pytest.fixture
def state(tmp_path):
    return S.State(tmp_path / 'operator')


# The registry -------------------------------------------------------------------------------------------------------

def test_registry_covers_every_ini_tuning_and_switch():
    deploy = compose.deploy_module(REPO)
    ini = {s.ini for s in S.REGISTRY.values() if s.ini}
    for section, keys in deploy.DEFAULTS.items():
        for key in keys:
            if key.endswith('_port'):
                continue
            assert ((section, key) in ini) != ((section, key) in S.EXCLUDED), (section, key)
    assert set(S.EXCLUDED) <= {(s, k) for s, keys in deploy.DEFAULTS.items() for k in keys}


def test_registry_holds_the_cluster_controls_and_the_new_worker_variables():
    env = {s.env for s in S.REGISTRY.values() if s.env}
    assert {'HOOVER4_PARSER_SANDBOX', 'HOOVER4_SLOT_TUNER', 'HOOVER4_TUNER_TARGET_MEMORY', 'HOOVER4_TUNER_TARGET_CPU',
            'HOOVER4_ADMIN_GROUPS'} <= env
    keys = set(S.REGISTRY)
    assert {'budget.worker_pods', 'zone.enabled', 'app.collabora', 'app.hoover', 'cpu.oversubscription',
            'volume.temporal-cassandra', 'memory.deployment/collabora.collabora-online'} <= keys


def test_every_setting_states_type_scope_services_and_apply_mode():
    for setting in S.REGISTRY.values():
        assert setting.scope in ('hoover', 'zone', 'cluster')
        assert setting.apply in ('restart', 'reconcile', 'expand', 'fixed', 'schedule')
        assert setting.services
        assert setting.check(setting.default) == setting.default.lower() if setting.kind == 'bool' else True
        if setting.default != '' or not setting.empty:
            setting.check(setting.default)


def test_defaults_give_an_ini_that_deploy_accepts(tmp_path):
    values = S.effective(SCOPE, {})
    text = zone_ini.render(S.ini_values(values), [{'name': 'testdata', 'path': '/testdata', 'writable': False}], True)
    path = tmp_path / 'hoover4.ini'
    path.write_text(text)
    deploy, cfg, env, services = compose.load(path, REPO)
    assert env['MANTICORE_MEM_LIMIT'] == '32G'
    derived = zone_ini.derive(zone_ini.BUDGET)
    assert cfg.get('main_services', 'common_workers') == derived[('main_services', 'common_workers')]


def test_values_are_checked():
    with pytest.raises(S.SettingsError, match='must be a size'):
        S.check_values(SCOPE, {'main_services.worker_mem_limit': 'lots'})
    with pytest.raises(S.SettingsError, match='must be one of'):
        S.check_values(SCOPE, {'main_services.pdf_ocr_provider': 'paper'})
    with pytest.raises(S.SettingsError, match='is not a setting'):
        S.check_values(SCOPE, {'main_services.mcp_browser_port': '1'})
    with pytest.raises(S.SettingsError, match='belongs to the zone scope'):
        S.check_values(SCOPE, {'app.xwiki': 'false'})
    assert S.check_values(SCOPE, {'main_services.internet_tools_enabled': 'TRUE'}) == {'main_services.internet_tools_enabled': 'true'}


def test_budget_suggestions_yield_to_overrides():
    values = S.effective(SCOPE, {'budget.worker_memory_mib': '12288'})
    assert values['main_services.worker_mem_limit'] == '12288M'
    values = S.effective(SCOPE, {'budget.worker_memory_mib': '12288', 'main_services.worker_mem_limit': '10000M'})
    assert values['main_services.worker_mem_limit'] == '10000M'


# Saving ---------------------------------------------------------------------------------------------------------------

def test_save_creates_revisions_and_changes_no_service(state):
    calls = []
    assert state.revision() == 0
    revision = state.save(0, {SCOPE: {'main_services.common_workers': '5'}})
    assert revision == 1 and state.revision() == 1
    assert state.effective(SCOPE)['main_services.common_workers'] == '5'
    assert state.active() is None
    assert state.applied()['revision'] == 0
    assert calls == []
    revision = state.save(1, {SCOPE: {'main_services.common_workers': None}})
    assert state.overrides(revision) == {}
    assert state.overrides(1) == {SCOPE: {'main_services.common_workers': '5'}}


def test_stale_revision_is_refused(state):
    state.save(0, {SCOPE: {'main_services.common_workers': '5'}})
    with pytest.raises(S.StaleRevision, match='Load them again'):
        state.save(0, {SCOPE: {'main_services.common_workers': '6'}})
    assert state.effective(SCOPE)['main_services.common_workers'] == '5'


def test_concurrent_saves_in_threads_keep_one_winner(state):
    results = []

    def save(n):
        try:
            results.append(state.save(0, {SCOPE: {'main_services.common_workers': str(n)}}))
        except S.StaleRevision:
            results.append('stale')
    threads = [threading.Thread(target=save, args=(n,)) for n in range(1, 9)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r for r in results if r != 'stale') == [1]
    assert results.count('stale') == 7


def _save_in_process(folder, n, queue):
    module = operator_settings()
    try:
        queue.put(module.State(folder).save(0, {SCOPE: {'main_services.common_workers': str(n)}}))
    except module.StaleRevision:
        queue.put('stale')


def test_concurrent_saves_in_processes_keep_one_winner(state):
    queue = multiprocessing.Queue()
    processes = [multiprocessing.Process(target=_save_in_process, args=(state.folder, n, queue)) for n in range(1, 7)]
    for p in processes:
        p.start()
    for p in processes:
        p.join()
    results = [queue.get() for _ in processes]
    assert results.count(1) == 1 and results.count('stale') == 5
    assert state.revision() == 1


def test_an_interrupted_write_keeps_the_previous_file(state, monkeypatch):
    state.save(0, {SCOPE: {'main_services.common_workers': '5'}})
    before = (state.folder / 'desired.json').read_text()

    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(S.os, 'replace', fail)
    with pytest.raises(OSError):
        state.save(1, {SCOPE: {'main_services.common_workers': '6'}})
    monkeypatch.undo()
    assert (state.folder / 'desired.json').read_text() == before
    assert S.State(state.folder).effective(SCOPE)['main_services.common_workers'] == '5'


def test_suggestions_keep_saved_overrides(state):
    state.save(0, {SCOPE: {'budget.worker_pods': '2'}})
    state.suggest(SCOPE, {'budget.worker_pods': '6', 'budget.worker_cpus': '8'})
    assert state.revision() == 1
    assert state.effective(SCOPE)['budget.worker_pods'] == '2'
    assert state.effective(SCOPE)['budget.worker_cpus'] == '4'
    assert state.suggestions(SCOPE) == {'budget.worker_pods': '6', 'budget.worker_cpus': '8'}


# Seeding from a Compose ini -------------------------------------------------------------------------------------------

def test_seed_once_from_the_source_ini_keeps_existing_overrides(state):
    source = config.read_source_ini(FIXTURES / 'source-tuned.ini', check_paths=False)
    assert source.dropped == ['[main_services] serena_enabled']
    state.save(0, {SCOPE: {'main_services.common_workers': '7'}})
    revision = state.seed(SCOPE, source)
    assert revision == 2
    values = state.effective(SCOPE)
    assert values['main_services.common_workers'] == '7'
    assert values['main_services.worker_mem_limit'] == '12000M'
    assert values['main_services.internet_tools_enabled'] == 'true'
    assert values['main_services.temporal_history_shards'] == '64'
    assert values['operations.export_collection_cap'] == '1'
    assert values['ai_services.llm_enabled'] == 'true'
    assert 'main_services.mcp_metasearch_port' not in state.overrides()[SCOPE]
    assert state.seed(SCOPE, source) is None
    assert state.revision() == 2


def test_seed_refuses_an_invalid_value_before_it_writes(state, tmp_path):
    path = tmp_path / 'bad.ini'
    path.write_text((FIXTURES / 'source-tuned.ini').read_text().replace('common_workers = 3', 'common_workers = three'))
    source = config.read_source_ini(path, check_paths=False)
    with pytest.raises(S.SettingsError, match='common_workers'):
        state.seed(SCOPE, source)
    assert state.revision() == 0


def test_seed_leaves_out_an_empty_value_which_selects_the_default(state, tmp_path):
    # An empty ini value selects the deploy.py default, as the local hoover4.ini of the workstation writes worker_mem_limit =.
    path = tmp_path / 'empty.ini'
    path.write_text((FIXTURES / 'source-tuned.ini').read_text().replace('worker_mem_limit = 12000M', 'worker_mem_limit ='))
    source = config.read_source_ini(path, check_paths=False)
    state.seed(SCOPE, source)
    assert 'main_services.worker_mem_limit' not in state.overrides()[SCOPE]
    assert state.effective(SCOPE)['main_services.worker_mem_limit'] == S.effective(SCOPE, {})['main_services.worker_mem_limit']


# Applying -------------------------------------------------------------------------------------------------------------

def recorder(log, fail_at=None):
    def step(name):
        def run(op, overrides):
            log.append((name, op.desired_revision, json.dumps(overrides, sort_keys=True)))
            if fail_at and fail_at[0] == name and fail_at[1] > 0:
                fail_at[1] -= 1
                raise RuntimeError(f'{name} failed')
            return [f'service-{name}']
        return run
    return {name: step(name) for name in ('render', 'stores', 'workers')}


def test_apply_pins_its_revision_and_a_later_save_waits(state):
    state.save(0, {SCOPE: {'main_services.common_workers': '5'}})
    op = state.start_apply('abc123', ['render', 'stores', 'workers'])
    state.save(1, {SCOPE: {'main_services.common_workers': '9'}})
    log = []
    done = state.run(recorder(log))
    assert done.status == 'succeeded'
    assert {entry[1] for entry in log} == {1}
    assert all('"5"' in entry[2] for entry in log)
    applied = state.applied()
    assert applied['revision'] == 1 and applied['source_revision'] == 'abc123' and applied['operation'] == op.id
    assert state.revision() == 2 and state.active() is None
    second = state.start_apply('def456', ['render'])
    state.run(recorder([]))
    assert state.applied()['revision'] == 2
    assert state.applied()['previous']['revision'] == 1
    assert second.desired_revision == 2


def test_an_interrupted_apply_resumes_at_its_step_after_a_restart(state):
    state.save(0, {SCOPE: {'main_services.common_workers': '5'}})
    op = state.start_apply('abc123', ['render', 'stores', 'workers'])
    log = []
    failed = state.run(recorder(log, fail_at=['stores', 1]))
    assert failed.status == 'failed' and failed.error.startswith('stores: RuntimeError')
    assert [s['status'] for s in failed.steps] == ['done', 'failed', 'pending']
    assert failed.changed == ['service-render']
    assert state.applied()['revision'] == 0
    state.save(1, {SCOPE: {'main_services.common_workers': '9'}})
    with pytest.raises(S.OperationActive):
        state.start_apply('abc123', ['render'])
    restarted = S.State(state.folder)
    assert restarted.active().id == op.id
    # A failed operation waits for an explicit retry. A runner restart alone does not run it.
    assert restarted.run(recorder(log)).status == 'failed'
    assert restarted.retry(op.id, actor='admin').status == 'queued'
    with pytest.raises(S.SettingsError):
        restarted.retry(op.id)
    done = restarted.run(recorder(log))
    assert done.status == 'succeeded' and done.attempts == 2
    assert [entry[0] for entry in log] == ['render', 'stores', 'stores', 'workers']
    assert {entry[1] for entry in log} == {1}
    assert restarted.applied()['revision'] == 1
    assert restarted.revision() == 2


def test_a_failed_operation_can_be_abandoned_without_applying(state):
    state.save(0, {SCOPE: {'main_services.common_workers': '5'}})
    op = state.start_apply('abc', ['render'])
    state.run(recorder([], fail_at=['render', 1]))
    state.abandon(op.id, actor='operator')
    assert state.operation(op.id).status == 'abandoned'
    assert state.active() is None and state.applied()['revision'] == 0


def test_one_runner_at_a_time(state):
    state.start_apply('abc', ['render'])
    entered, release = threading.Event(), threading.Event()

    def slow(op, overrides):
        entered.set()
        release.wait(10)
        return []
    worker = threading.Thread(target=state.run, args=({'render': slow},))
    worker.start()
    entered.wait(10)
    with pytest.raises(S.RunnerBusy):
        S.State(state.folder).run({'render': slow})
    release.set()
    worker.join()
    assert state.applied()['revision'] == 0 or state.active() is None


def test_fixed_and_growing_settings_after_the_first_apply(state):
    state.save(0, {SCOPE: {'main_services.temporal_history_shards': '64', 'volume.clickhouse-data': '40Gi'}})
    state.start_apply('abc', ['render'])
    state.run(recorder([]))
    with pytest.raises(S.SettingsError, match='fixed after the first apply'):
        state.save(1, {SCOPE: {'main_services.temporal_history_shards': '128'}})
    with pytest.raises(S.SettingsError, match='A volume only grows'):
        state.save(1, {SCOPE: {'volume.clickhouse-data': '20Gi'}})
    assert state.save(1, {SCOPE: {'volume.clickhouse-data': '80Gi'}}) == 2


def test_state_files_hold_no_temporary_files(state):
    state.save(0, {SCOPE: {'main_services.common_workers': '5'}})
    state.start_apply('abc', ['render'])
    state.run(recorder([]))
    leftovers = [p for p in Path(state.folder).rglob('*.tmp')]
    assert leftovers == []
    assert os.stat(state.folder / 'desired.json').st_size > 0


# The Apply plan of the portal and the runner ---------------------------------------------------------------------------

def apply_module():
    import importlib.util
    import sys
    if 'operator_apply' not in sys.modules:
        spec = importlib.util.spec_from_file_location('operator_apply', REPO / 'k3s/platform/operator/apply.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules['operator_apply'] = module
        spec.loader.exec_module(module)
    return sys.modules['operator_apply']


def test_the_apply_plan_names_one_step_for_each_changed_part(state):
    A = apply_module()
    site = config.parse((FIXTURES / 'single-node.ini').read_text().replace('@REPO@', str(REPO)))
    assert A.plan(state, site) == ['record']
    state.save(0, {SCOPE: {'main_services.common_workers': '5'}, 'zone:zone-a': {'app.xwiki': 'false', 'app.hoover': 'false',
               'backup.opendesk.enabled': 'true'}, 'cluster': {'cpu.oversubscription': '3'}})
    steps = A.plan(state, site)
    assert steps == sorted(steps, key=steps.index)
    assert set(steps) == {'hoover:main', 'apps:zone-a', 'schedule', 'zone:zone-a'}
    assert 'backups' in A.services(state, site) and 'xwiki' in A.services(state, site)
    log = []
    op = state.start_apply('abc', steps)
    runners = A.executors(site, '/dev/null', wait=lambda ns: log.append(ns))
    assert runners['schedule'](op, {}) == ['backups'] and runners['record'](op, {}) == []
    with pytest.raises(KeyError):
        runners['unknown:x']


def test_backup_policies_keep_their_ranges(state):
    with pytest.raises(S.SettingsError):
        state.save(0, {'zone:zone-a': {'backup.opendesk.copies': '1'}})
    with pytest.raises(S.SettingsError):
        state.save(0, {'zone:zone-a': {'backup.hoover.copies': '3'}})
    assert state.save(0, {'cluster': {'backup.platform.copies': '2'}}) == 1


# Scope-aware applied revisions ------------------------------------------------------------------------------------------

def single_site():
    return config.parse((FIXTURES / 'single-node.ini').read_text().replace('@REPO@', str(REPO)))


def remote_site():
    return config.parse((FIXTURES / 'remote.ini').read_text().replace('@REPO@', str(REPO)))


def test_gpu_runtime_applies_the_gpu_pool_and_no_zone(state, monkeypatch):
    A = apply_module()
    site = remote_site()
    state.save(0, {'cluster': {'gpu.runtime': 'runc'}})
    steps, by_scope = A.plan_scopes(state, site)
    assert steps == ['gpu-pool'] and by_scope == {'cluster': ['gpu-pool']}
    # A site whose GPU pool runs at an address outside the site changes no service.
    assert A.plan(state, single_site()) == ['record']
    commands = []
    monkeypatch.setattr(A, 'run_command', lambda argv, op, log: commands.append([str(a) for a in argv]))
    op = state.start_apply('abc', steps, by_scope)
    done = state.run(A.executors(site, '/dev/null'))
    assert done.status == 'succeeded'
    assert [c[1:] for c in commands] == [[str(REPO / 'k3s/platform/gpu/gpu_pool.py'), 'apply'],
                                          [str(REPO / 'k3s/platform/gpu/gpu_pool.py'), 'verify']]
    assert state.applied()['revision'] == 1 and op.scope_steps == {'cluster': ['gpu-pool']}


def test_a_failed_gpu_check_keeps_the_runtime_pending(state, monkeypatch):
    A = apply_module()
    site = remote_site()
    state.save(0, {'cluster': {'gpu.runtime': 'runc'}})

    def run_command(argv, op, log):
        if argv[-1] == 'verify':
            raise A.ApplyFailed('the GPU pool check ended in phase Failed')
    monkeypatch.setattr(A, 'run_command', run_command)
    steps, by_scope = A.plan_scopes(state, site)
    state.start_apply('abc', steps, by_scope)
    assert state.run(A.executors(site, '/dev/null')).status == 'failed'
    assert state.applied_revision('cluster') == 0
    assert A.changes(state, site) == {'cluster': {'gpu.runtime': ('runsc', 'runc')}}


def test_a_partly_finished_apply_records_the_finished_scopes_only(state):
    A = apply_module()
    site = single_site()
    state.save(0, {SCOPE: {'main_services.common_workers': '5'}, 'zone:zone-a': {'app.xwiki': 'false'}})
    steps, by_scope = A.plan_scopes(state, site)
    assert by_scope == {SCOPE: ['hoover:main'], 'zone:zone-a': ['apps:zone-a']}
    op = state.start_apply('abc', steps, by_scope)
    assert [x['name'] for x in op.steps] == ['apps:zone-a', 'hoover:main']
    calls = []

    def ok(op, overrides):
        calls.append('apps')
        return ['xwiki']

    def broken(op, overrides):
        raise RuntimeError('the rollout of the workers failed')
    failed = state.run({'apps:zone-a': ok, 'hoover:main': broken})
    assert failed.status == 'failed' and failed.applied_scopes == ['zone:zone-a']
    assert state.applied_revision('zone:zone-a') == 1 and state.applied_revision(SCOPE) == 0
    assert state.applied()['revision'] == 0
    # Only the unfinished scope stays pending in the portal.
    assert set(A.changes(state, site)) == {SCOPE}
    # A save during the operation stays a later desired revision after the retry succeeds.
    state.save(1, {SCOPE: {'main_services.common_workers': '7'}})
    state.retry(op.id)
    done = state.run({'apps:zone-a': ok, 'hoover:main': lambda op, o: []})
    assert done.status == 'succeeded' and calls == ['apps']
    assert state.applied()['revision'] == 1 and state.applied()['scopes'] == {}
    assert A.changes(state, site) == {SCOPE: {'main_services.common_workers': ('5', '7')}}


def test_scope_records_never_go_back(state):
    state.save(0, {SCOPE: {'main_services.common_workers': '5'}})
    state.save(1, {SCOPE: {'main_services.common_workers': '6'}})
    state.record_scopes([SCOPE], 2, 'deploy:a', 'abc')
    state.record_scopes([SCOPE], 1, 'deploy:b', 'abc')
    assert state.applied_revision(SCOPE) == 2 and state.applied_revision('cluster') == 0
    state.record_all(2, 'deploy:c', 'abc')
    assert state.applied()['revision'] == 2 and state.applied()['scopes'] == {}
    # A deployment that pinned an older revision does not undo a later Apply.
    state.record_all(1, 'deploy:d', 'abc')
    assert state.applied()['revision'] == 2 and state.applied()['operation'] == 'deploy:c'


def test_fixed_settings_use_the_applied_revision_of_their_scope(state):
    state.save(0, {SCOPE: {'main_services.temporal_history_shards': '64'}})
    state.record_scopes([SCOPE], 1, 'deploy:a', 'abc')
    with pytest.raises(S.SettingsError, match='fixed after the first apply'):
        state.save(1, {SCOPE: {'main_services.temporal_history_shards': '128'}})
