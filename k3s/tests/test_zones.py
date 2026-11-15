"""The openDesk waves of the zone installer and the measured CPU requests of the zone render."""
import sys

import pytest
import yaml

from conftest import K3S

sys.path.insert(0, str(K3S / 'zones'))
import cpu_requests  # noqa: E402
import zone  # noqa: E402

# The entry list of helmfile-defaults.yaml.gotmpl of openDesk v1.19.1, in its order.
UPSTREAM = ['opendesk-migrations-pre', 'opendesk-services', 'services-external', 'nubus', 'open-xchange', 'nextcloud',
            'collabora', 'cryptpad', 'jitsi', 'element', 'neoboard', 'openproject', 'xwiki', 'notes',
            'opendesk-openproject-bootstrap', 'opendesk-migrations-post']


def defaults(entries):
    return 'helmfiles:\n' + ''.join(f'  - path: "helmfile/apps/{e}/helmfile-defaults.yaml.gotmpl"\n    values: *values\n'
                                    for e in entries)


def test_the_waves_cover_every_entry_of_the_release_in_its_order():
    assert zone.upstream_entries(defaults(UPSTREAM)) == UPSTREAM
    assert zone.wave_problems(UPSTREAM) == []
    # The applications run in one wave, after the services and Nubus.
    assert len(zone.OPENDESK_WAVES[3]) == 10 and zone.OPENDESK_WAVES[2] == ('nubus',)


def test_the_installed_release_matches_the_waves():
    path = zone.OPENDESK / 'helmfile-defaults.yaml.gotmpl'
    if not path.exists():
        pytest.skip('the openDesk release is not unpacked in this checkout')
    assert zone.upstream_entries(path.read_text()) == UPSTREAM


def test_a_new_moved_or_removed_entry_fails_loudly():
    problems = zone.wave_problems(UPSTREAM[:5] + ['newapp'] + UPSTREAM[5:])
    assert problems == ['the openDesk release has the sub-helmfile newapp, which no wave of zone.py OPENDESK_WAVES names']
    assert zone.wave_problems([e for e in UPSTREAM if e != 'xwiki']) == [
        'zone.py OPENDESK_WAVES names xwiki, which the openDesk release does not have']
    moved = ['nubus'] + [e for e in UPSTREAM if e != 'nubus']
    assert any('runs nubus before opendesk-migrations-pre' in p for p in zone.wave_problems(moved))


def test_an_entry_syncs_when_a_release_is_new_or_not_deployed(tmp_path, monkeypatch):
    app = tmp_path / 'helmfile/apps/element'
    app.mkdir(parents=True)
    (app / 'helmfile-child.yaml.gotmpl').write_text(
        'repositories:\n  - name: "element-repo"\n\nreleases:\n  - name: {{ . | quote }}\n    chart: x\n'
        '  - name: "element"\n    chart: x\n  - name: "matrix-neodatefix-bot-bootstrap"\n    chart: x\n\ncommonLabels:\n'
        '  deployStage: "050"\n')
    monkeypatch.setattr(zone, 'OPENDESK', tmp_path)
    assert zone.entry_releases('element') == ['element', 'matrix-neodatefix-bot-bootstrap']
    assert zone.entry_command('element', {}) == 'sync'
    assert zone.entry_command('element', {'element': 'deployed'}) == 'apply'
    assert zone.entry_command('element', {'element': 'deployed', 'matrix-neodatefix-bot-bootstrap': 'failed'}) == 'sync'
    assert zone.entry_command('element', {'element': 'deployed', 'matrix-neodatefix-bot-bootstrap': 'deployed'}) == 'apply'


def test_a_failed_entry_runs_once_more_after_its_repair_and_logs_the_cause(monkeypatch, capsys):
    runs, repaired = [], []
    monkeypatch.setattr(zone, 'entry_releases', lambda entry: ['nubus', 'ums'])
    states = iter([{}, {'nubus': 'failed'}, {'nubus': 'failed'}])
    monkeypatch.setattr(zone, 'helm_releases', lambda z: next(states))
    monkeypatch.setattr(zone, 'run_entry', lambda z, e, c: runs.append(c) or ((1, 'Error: timed out waiting') if len(runs) == 1 else (0, '')))
    monkeypatch.setattr(zone, 'repair', lambda z, e, r: repaired.append((e, r)))
    zone.install_entry('zone-a', 'nubus')
    assert runs == ['sync', 'sync'] and repaired == [('nubus', {'nubus': 'failed'})]
    assert '"step": "helmfile-retry"' in capsys.readouterr().out


def test_a_second_failure_stops_the_install(monkeypatch):
    monkeypatch.setattr(zone, 'entry_releases', lambda entry: ['xwiki'])
    monkeypatch.setattr(zone, 'helm_releases', lambda z: {'xwiki': 'failed'})
    monkeypatch.setattr(zone, 'run_entry', lambda z, e, c: (1, 'Error: xwiki timed out'))
    monkeypatch.setattr(zone, 'repair', lambda z, e, r: None)
    with pytest.raises(SystemExit, match='xwiki failed twice: Error: xwiki timed out'):
        zone.install_entry('zone-a', 'xwiki')


def test_the_zone_pod_policy_adds_no_pod_count_spread():
    policy = next(d for d in yaml.safe_load_all((K3S / 'zones/manifests/zone-pods.yaml').read_text())
                  if d['kind'] == 'MutatingAdmissionPolicy')
    assert 'topologySpreadConstraints' not in policy['spec']['mutations'][0]['jsonPatch']['expression']


TABLE = {'factor': 0.5, 'measured': {'source': 'zone create of 2026-11-14'},
         'measuredSite': {'source': 'store start of 2026-11-14'},
         'zone': {'statefulset/xwiki': {'startPeak': '4408m', 'baseline': '41m', 'request': '2230m'}},
         'site': {'statefulset/temporal-cassandra': {'startPeak': '1132m', 'baseline': '301m', 'request': '720m'}}}


def workload(name, containers):
    return {'kind': 'StatefulSet', 'metadata': {'name': name},
            'spec': {'template': {'metadata': {}, 'spec': {'containers': containers}}}}


def test_the_request_is_halfway_between_the_baseline_and_the_start_peak():
    assert cpu_requests.request_of(4408, 41, 0.5) == 2230
    assert cpu_requests.request_of(100, 100, 0.5) == 100
    assert cpu_requests.request_of(3, 1, 0.5) == 10
    assert cpu_requests.request_of(1001, 1, 0.5) == 510


def test_the_render_writes_the_request_and_its_basis_on_the_pod():
    doc = workload('xwiki', [{'name': 'xwiki', 'resources': {'requests': {'cpu': '25m'}, 'limits': {'cpu': '8'}}},
                             {'name': 'sidecar', 'resources': {'requests': {'cpu': '30m'}}}])
    assert cpu_requests.apply(doc, 'statefulset/xwiki', 'zone', main='xwiki', table=TABLE)
    template = doc['spec']['template']
    containers = template['spec']['containers']
    # The pod requests the table value: the main container gets it less the request of the sidecar.
    assert containers[0]['resources']['requests']['cpu'] == '2200m' and containers[1]['resources']['requests']['cpu'] == '30m'
    assert template['metadata']['annotations'] == {
        'hoover.dev/cpu-start-peak': '4408m', 'hoover.dev/cpu-baseline': '41m',
        'hoover.dev/cpu-request-basis': 'baseline + 0.5 x (start peak - baseline), zone create of 2026-11-14'}


def test_null_metadata_annotations_and_resources_of_a_chart_render_are_filled():
    doc = workload('xwiki', [{'name': 'xwiki', 'resources': None}])
    doc['spec']['template']['metadata'] = {'annotations': None}
    assert cpu_requests.apply(doc, 'statefulset/xwiki', 'zone', table=TABLE)
    assert doc['spec']['template']['spec']['containers'][0]['resources'] == {'requests': {'cpu': '2230m'}}
    assert doc['spec']['template']['metadata']['annotations']['hoover.dev/cpu-baseline'] == '41m'


def test_an_unmeasured_workload_keeps_its_request_and_names_its_basis():
    doc = workload('other', [{'name': 'main', 'resources': {'requests': {'cpu': '25m'}}}])
    assert not cpu_requests.apply(doc, 'statefulset/other', 'zone', table=TABLE)
    assert doc['spec']['template']['spec']['containers'][0]['resources']['requests']['cpu'] == '25m'
    assert doc['spec']['template']['metadata']['annotations'] == {
        'hoover.dev/cpu-request-basis': 'no measurement: the request of the CPU policy'}


def test_the_table_of_the_source_is_consistent():
    table = cpu_requests.load()
    assert table['factor'] == 0.5
    for part in ('zone', 'hoover', 'site'):
        assert table.get(part), part
        for key, entry in table[part].items():
            peak, base = (cpu_requests.millicores(entry[k]) for k in ('startPeak', 'baseline'))
            assert cpu_requests.millicores(entry['request']) == cpu_requests.request_of(peak, base, table['factor']), key


def test_a_site_store_gets_the_request_and_the_basis_of_the_store_measurement():
    doc = workload('temporal-cassandra', [{'name': 'cassandra', 'resources': {'requests': {'cpu': '50m'}}}])
    assert cpu_requests.apply(doc, 'statefulset/temporal-cassandra', 'site', table=TABLE)
    assert doc['spec']['template']['spec']['containers'][0]['resources']['requests']['cpu'] == '720m'
    assert doc['spec']['template']['metadata']['annotations']['hoover.dev/cpu-request-basis'] == \
        'baseline + 0.5 x (start peak - baseline), store start of 2026-11-14'


def test_the_shared_stores_carry_their_measured_request():
    sys.path.insert(0, str(K3S / 'hoover' / 'stores'))
    import hoover
    items = [workload('temporal-cassandra', [{'name': 'cassandra', 'resources': {'requests': {'cpu': '50m'}}}]),
             {'kind': 'Service', 'metadata': {'name': 'temporal-cassandra'}}]
    table = cpu_requests.TABLE
    cpu_requests.TABLE = TABLE
    try:
        hoover.site_cpu(items)
    finally:
        cpu_requests.TABLE = table
    assert items[0]['spec']['template']['spec']['containers'][0]['resources']['requests']['cpu'] == '720m'


def test_the_runtime_classes_carry_the_measured_overhead():
    classes = {d['metadata']['name']: d for d in yaml.safe_load_all((K3S / 'cluster/runtimeclasses.yaml').read_text()) if d}
    measured = cpu_requests.load()['runtimeOverhead']
    for name in ('gvisor', 'kata'):
        entry = measured[name]
        idle, start = (cpu_requests.millicores(entry[k]) for k in ('idle', 'start'))
        assert cpu_requests.millicores(entry['overhead']) == cpu_requests.request_of(start, idle, cpu_requests.load()['factor'])
        assert classes[name]['overhead']['podFixed'] == {'cpu': entry['overhead'], 'memory': entry['memoryOverhead']}
