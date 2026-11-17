"""The openDesk waves of the zone installer, the measured CPU requests and the periodic tasks of the zone render."""
import json
import signal
import subprocess
import sys
import time

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


def test_the_request_lies_at_the_factor_between_the_baseline_and_the_start_peak():
    assert cpu_requests.request_of(4408, 41, 0.5) == 2230
    assert cpu_requests.request_of(4408, 41, 0.25) == 1140
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
    assert table['factor'] == 0.2
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


def test_the_runtime_classes_carry_the_overhead_of_the_formula():
    classes = {d['metadata']['name']: d for d in yaml.safe_load_all((K3S / 'cluster/runtimeclasses.yaml').read_text()) if d}
    measured = cpu_requests.load()['runtimeOverhead']
    for name in ('gvisor', 'kata'):
        entry = measured[name]
        assert cpu_requests.millicores(entry['overhead']) == cpu_requests.pod_fixed(name)
        assert classes[name]['overhead']['podFixed'] == {'cpu': entry['overhead'], 'memory': entry['memoryOverhead']}


OVERHEAD = {'runtimeOverhead': {'kubeletPerPod': 3.3, 'shimPerPod': 1.7, 'statsPeriodSeconds': 10,
                                'runscStatsCpuSeconds': 0.007, 'execCpuSeconds': 0.045}}


def test_the_fixed_overhead_is_the_kubelet_the_shim_and_the_statistics_of_the_sandbox():
    # 3.3 + 1.7 + 7 ms / 10 s = 5.7m, rounded up. Kata and runc have no runsc statistics call.
    assert cpu_requests.pod_fixed('gvisor', OVERHEAD) == 6
    assert cpu_requests.pod_fixed('kata', OVERHEAD) == 5


def test_the_runtime_cost_counts_the_containers_and_the_exec_probes_at_their_period():
    spec = {'containers': [
        {'name': 'a', 'readinessProbe': {'exec': {'command': ['true']}, 'periodSeconds': 10},
         'livenessProbe': {'exec': {'command': ['true']}, 'periodSeconds': 30},
         'startupProbe': {'exec': {'command': ['true']}, 'periodSeconds': 1}},
        {'name': 'b', 'readinessProbe': {'httpGet': {'path': '/', 'port': 80}, 'periodSeconds': 1}}],
        'initContainers': [{'name': 'side', 'restartPolicy': 'Always'}, {'name': 'once'}]}
    # 3 gVisor containers x 0.7m + 45 ms / 10 s + 45 ms / 30 s = 2.1 + 4.5 + 1.5 = 8.1m, rounded up. The startup probe
    # and the HTTP probe do not count.
    assert cpu_requests.runtime_cost(spec, 'gvisor', OVERHEAD) == 9
    # Kata collects the statistics in its shim, so only the exec probes count.
    assert cpu_requests.runtime_cost(spec, 'kata', OVERHEAD) == 6
    assert cpu_requests.runtime_cost({'containers': [{'name': 'a'}]}, 'runc', OVERHEAD) == 0


def test_the_render_adds_the_runtime_cost_once_to_the_main_container():
    table = dict(TABLE, **OVERHEAD)
    probe = {'exec': {'command': ['true']}, 'periodSeconds': 10}
    doc = workload('xwiki', [{'name': 'xwiki', 'readinessProbe': probe, 'resources': {'requests': {'cpu': '25m'}}}])
    assert cpu_requests.apply(doc, 'statefulset/xwiki', 'zone', table=table)
    # 2230m of the table, and 0.7m + 4.5m of the runtime, rounded up to 6m.
    assert doc['spec']['template']['spec']['containers'][0]['resources']['requests']['cpu'] == '2236m'
    assert doc['spec']['template']['metadata']['annotations']['hoover.dev/cpu-runtime'] == '6m'
    other = workload('other', [{'name': 'main', 'readinessProbe': probe, 'resources': {'requests': {'cpu': '25m'}}}])
    for _ in range(2):
        assert not cpu_requests.apply(other, 'statefulset/other', 'zone', table=table)
        assert other['spec']['template']['spec']['containers'][0]['resources']['requests']['cpu'] == '31m'
    # A store of the site without runtimeClassName runs with runc.
    runc = workload('other', [{'name': 'main', 'resources': {'requests': {'cpu': '25m'}}}])
    cpu_requests.apply(runc, 'statefulset/other', 'site', table=table)
    assert runc['spec']['template']['spec']['containers'][0]['resources']['requests']['cpu'] == '25m'
    # A zone pod with the runc label has no runsc statistics call.
    labelled = workload('other', [{'name': 'main', 'resources': {'requests': {'cpu': '25m'}}}])
    labelled['spec']['template']['metadata']['labels'] = {'hoover.dev/runtime': 'runc'}
    assert cpu_requests.runtime(labelled, 'zone') == 'runc'
    assert cpu_requests.runtime(workload('x', []), 'hoover') == 'gvisor'


def test_the_runtime_cost_stays_below_the_cpu_limit():
    table = dict(TABLE, **OVERHEAD)
    probe = {'exec': {'command': ['true']}, 'periodSeconds': 1}
    doc = workload('other', [{'name': 'main', 'readinessProbe': probe,
                              'resources': {'requests': {'cpu': '25m'}, 'limits': {'cpu': '50m'}}}])
    cpu_requests.apply(doc, 'statefulset/other', 'zone', table=table)
    assert doc['spec']['template']['spec']['containers'][0]['resources']['requests']['cpu'] == '50m'


def test_the_post_renderer_removes_no_op_probes_and_lengthens_short_periods():
    sys.path.insert(0, str(K3S / 'hoover' / 'stores'))
    import postrender
    exit0 = {'exec': {'command': ['sh', '-c', 'exit 0\n']}, 'periodSeconds': 20}
    doc = {'kind': 'StatefulSet', 'metadata': {'name': 'ums-provisioning-prefill'}, 'spec': {'template': {'spec': {
        'containers': [{'name': 'main', 'livenessProbe': dict(exit0), 'readinessProbe': dict(exit0),
                        'startupProbe': {'exec': {'command': ['/bin/bash', '-c', 'exit 0\n']}}}],
        'initContainers': None}}}}
    postrender.probes(doc, 'statefulset/ums-provisioning-prefill')
    assert doc['spec']['template']['spec']['containers'][0] == {'name': 'main'}
    redis = {'kind': 'StatefulSet', 'metadata': {'name': 'redis-master'}, 'spec': {'template': {'spec': {'containers': [
        {'name': 'redis', 'readinessProbe': {'exec': {'command': ['/bin/bash', '-ec', 'x']}, 'periodSeconds': 1},
         'livenessProbe': {'exec': {'command': ['/bin/bash', '-ec', 'y']}, 'periodSeconds': 5}}]}}}}
    postrender.probes(redis, 'statefulset/redis-master')
    c = redis['spec']['template']['spec']['containers'][0]
    assert c['readinessProbe']['periodSeconds'] == 10 and c['livenessProbe']['periodSeconds'] == 10
    assert c['readinessProbe']['exec'] == {'command': ['/bin/bash', '-ec', 'x']}
    memcached = {'kind': 'Deployment', 'metadata': {'name': 'memcached'}, 'spec': {'template': {'spec': {'containers': [
        {'name': 'memcached', 'livenessProbe': {'exec': {'command': ['pgrep', 'memcached']}, 'periodSeconds': 10}}]}}}}
    postrender.probes(memcached, 'deployment/memcached')
    assert memcached['spec']['template']['spec']['containers'][0]['livenessProbe'] == \
        {'tcpSocket': {'port': 11211}, 'periodSeconds': 10}


def cronjob(name, schedule, container, account='a', security=None, volumes=(), labels=None):
    spec = {'serviceAccountName': account, 'securityContext': security or {}, 'restartPolicy': 'Never',
            'containers': [container], 'volumes': list(volumes)}
    return {'kind': 'CronJob', 'metadata': {'name': name, 'namespace': 'zone-a', 'labels': {'app': name}},
            'spec': {'schedule': schedule, 'jobTemplate': {'spec': {'template': {
                'metadata': {'labels': labels or {'app': name}, 'annotations': {'note': 'x'}}, 'spec': spec}}}}}


def pod_workload(name, containers, account, memory, security=None, volumes=()):
    return {'kind': 'Deployment', 'metadata': {'name': name}, 'spec': {'replicas': 1, 'selector': {'matchLabels': {'app': account}},
                                                                        'template': {'metadata': {}, 'spec': {
        'serviceAccountName': account, 'securityContext': security or {}, 'volumes': list(volumes),
        'containers': [{'name': c, 'resources': {'requests': {'memory': memory}}} for c in containers]}}}}


def task(name, command=None, mounts=()):
    c = {'name': name, 'image': f'{name}:1', 'env': [{'name': 'E', 'value': '1'}],
         'resources': {'requests': {'cpu': '26m', 'memory': '204Mi'}, 'limits': {'cpu': '3', 'memory': '1Gi'}},
         'volumeMounts': [{'name': m, 'mountPath': f'/{m}'} for m in mounts]}
    if command:
        c['command'] = command
    return c


def opendesk_cronjobs():
    """The four CronJobs of openDesk v1.19.1 and the workloads whose pods get their sidecars."""
    empty = {'name': 'nextcloud-config', 'emptyDir': {'medium': 'Memory'}}
    ldap = {'name': 'secret-ldap', 'secret': {'secretName': 'ums-ldap-server-admin'}}
    return [
        pod_workload('opendesk-nextcloud-aio', ['aio'], 'opendesk-nextcloud-aio', '896Mi', {'fsGroup': 101},
                     [{'name': 'nextcloud-config', 'emptyDir': {}}]),
        pod_workload('ums-udm-rest-api', ['main'], 'ums-udm-rest-api', '448Mi', {'fsGroup': 1000}, [ldap]),
        cronjob('opendesk-nextcloud-aio-cron', '*/5 * * * *', task('cron', mounts=['nextcloud-config']),
                'opendesk-nextcloud-aio', {'fsGroup': 101}, [empty]),
        # The CronJobs of the UDM chart carry the labels of the UDM REST API, which its selector matches.
        cronjob('ums-udm-rest-api-license-cache', '0 * * * *', task('main', ['/usr/share/update-license-cache'], ['secret-ldap']),
                'ums-udm-rest-api', {'fsGroup': 1000}, [ldap], labels={'app': 'ums-udm-rest-api'}),
        cronjob('ums-udm-rest-api-blocklist-cleanup', '0 8 * * *', task('main', mounts=['secret-ldap']), 'ums-udm-rest-api',
                {'fsGroup': 1000}, [ldap], labels={'app': 'ums-udm-rest-api'}),
        cronjob('opendesk-element-customization-media-cleanup', '0 * * * *',
                task('media-cleanup', ['/bin/bash', '/usr/local/bin/media-cleanup.sh']), 'media-cleanup'),
    ]


def test_each_cronjob_of_the_charts_becomes_a_container_that_stays_running():
    import postrender
    out = postrender.periodic(opendesk_cronjobs())
    assert not [d for d in out if d['kind'] == 'CronJob']
    by_name = {d['metadata']['name']: d for d in out}
    aio = by_name['opendesk-nextcloud-aio']['spec']['template']['spec']
    cron = aio['containers'][1]
    assert [c['name'] for c in aio['containers']] == ['aio', 'cron']
    assert cron['command'][:2] == ['/bin/sh', '-c'] and cron['command'][3:] == [
        'opendesk-nextcloud-aio-cron', '300', '0', '60', '/docker-entrypoint.sh', '/usr/bin/php', '/usr/local/bin/entrypoint/entrypoint.php']
    assert cron['image'] == 'cron:1' and cron['env'] == [{'name': 'E', 'value': '1'}]
    assert cron['resources'] == {'requests': {'cpu': '26m', 'memory': '128Mi'}, 'limits': {'cpu': '3', 'memory': '1Gi'}}
    # The sidecar has its own copy of each volume, so it shares no emptyDir with the aio container.
    assert cron['volumeMounts'] == [{'name': 'cron-nextcloud-config', 'mountPath': '/nextcloud-config'}]
    assert {'name': 'cron-nextcloud-config', 'emptyDir': {'medium': 'Memory'}} in aio['volumes']
    assert {'name': 'nextcloud-config', 'emptyDir': {}} in aio['volumes']
    # The UDM REST API keeps its pod: a change of its tasks does not restart it, and it keeps the chart rollout.
    udm = by_name['ums-udm-rest-api']
    assert [c['name'] for c in udm['spec']['template']['spec']['containers']] == ['main']
    # The second pod of a rolling update found no node on the full test site, so it keeps maxSurge 0.
    postrender.rollout(udm)
    assert udm['spec']['strategy'] == {'type': 'RollingUpdate', 'rollingUpdate': {'maxSurge': 0, 'maxUnavailable': 1}}
    tasks = by_name['ums-udm-rest-api-periodic']
    spec = tasks['spec']['template']['spec']
    # The selector of the UDM REST API does not find the pod of the tasks.
    assert tasks['spec']['template']['metadata']['labels'] == {'hoover.dev/periodic': 'ums-udm-rest-api-periodic'}
    assert tasks['kind'] == 'Deployment' and tasks['spec']['strategy'] == {'type': 'Recreate'}
    assert tasks['spec']['selector'] == {'matchLabels': {'hoover.dev/periodic': 'ums-udm-rest-api-periodic'}}
    assert [c['name'] for c in spec['containers']] == ['license-cache', 'blocklist-cleanup']
    assert spec['serviceAccountName'] == 'ums-udm-rest-api' and spec['restartPolicy'] == 'Always'
    license, blocklist = spec['containers']
    assert license['command'][4:] == ['3600', '0', '60', '/usr/share/update-license-cache']
    assert blocklist['command'][4:] == ['86400', '28800', '60', '/bin/blocklist_clean_expired.py']
    assert [v['name'] for v in spec['volumes']] == ['license-cache-secret-ldap', 'blocklist-cleanup-secret-ldap']
    media = by_name['opendesk-element-customization-media-cleanup']
    spec = media['spec']['template']['spec']
    assert media['kind'] == 'Deployment' and media['spec']['replicas'] == 1 and media['spec']['strategy'] == {'type': 'Recreate'}
    assert media['spec']['selector'] == {'matchLabels': {'hoover.dev/periodic': 'opendesk-element-customization-media-cleanup'}}
    assert media['spec']['template']['metadata']['labels'] == {
        'app': 'opendesk-element-customization-media-cleanup', 'hoover.dev/periodic': 'opendesk-element-customization-media-cleanup'}
    assert spec['serviceAccountName'] == 'media-cleanup' and spec['restartPolicy'] == 'Always'
    assert spec['containers'][0]['command'][4:] == ['3600', '0', '60', '/bin/bash', '/usr/local/bin/media-cleanup.sh']
    # A second render gives the same result.
    assert postrender.periodic(out) == out


def test_a_disabled_zone_or_application_runs_no_periodic_deployment():
    import postrender
    media = [d for d in opendesk_cronjobs() if d['metadata']['name'].endswith('media-cleanup')]
    assert postrender.periodic(json_copy(media), disabled=True)[0]['spec']['replicas'] == 0
    assert postrender.periodic(json_copy(media), values={'app.element': 'false'})[0]['spec']['replicas'] == 0


def json_copy(value):
    import json
    return json.loads(json.dumps(value))


def test_a_cronjob_without_a_rule_stops_the_render():
    import postrender
    new = cronjob('opendesk-new-task', '0 * * * *', task('main', ['run']))
    with pytest.raises(RuntimeError, match='opendesk-new-task, which has no rule in postrender.py PERIODIC'):
        postrender.periodic([new])
    cron = opendesk_cronjobs()
    cron[2]['spec']['jobTemplate']['spec']['template']['spec']['serviceAccountName'] = 'other'
    with pytest.raises(RuntimeError, match='differ in serviceAccountName'):
        postrender.periodic(cron)
    cron = opendesk_cronjobs()
    cron[4]['spec']['jobTemplate']['spec']['template']['spec']['serviceAccountName'] = 'other'
    with pytest.raises(RuntimeError, match='the other tasks of ums-udm-rest-api-periodic differ in serviceAccountName'):
        postrender.periodic(cron)
    with pytest.raises(RuntimeError, match='needs deployment/opendesk-nextcloud-aio'):
        postrender.periodic(opendesk_cronjobs()[2:])


def test_the_schedules_give_their_interval_and_offset():
    import postrender
    assert postrender.interval('*/5 * * * *') == (300, 0)
    assert postrender.interval('0 * * * *') == (3600, 0)
    assert postrender.interval('15 * * * *') == (3600, 900)
    assert postrender.interval('0 8 * * *') == (86400, 28800)
    with pytest.raises(RuntimeError, match='no interval form'):
        postrender.interval('0 8 * * 1')


def test_the_loop_runs_again_after_a_failed_run_and_stops_at_once():
    import postrender
    loop = ['sh', '-c', postrender.PERIODIC_LOOP, 'task']
    process = subprocess.Popen(loop + ['1', '0', '60', 'sh', '-c', 'echo run; exit 3'], stdout=subprocess.PIPE, text=True)
    time.sleep(2.5)
    process.send_signal(signal.SIGTERM)
    out, _ = process.communicate(timeout=5)
    assert process.returncode == 0
    assert out.count('run\n') >= 2 and 'periodic task task: exit 3 after 0 s' in out
    # A failed run repeats after the retry wait, before the next time of the schedule, at most 5 times.
    process = subprocess.Popen(loop + ['3600', '0', '1', 'false'], stdout=subprocess.PIPE, text=True)
    time.sleep(7.5)
    process.send_signal(signal.SIGTERM)
    out, _ = process.communicate(timeout=5)
    assert out.count('exit 1') == 6
    # A stop signal during the wait ends the loop without waiting for the next run.
    process = subprocess.Popen(loop + ['3600', '0', '60', 'true'], stdout=subprocess.PIPE, text=True)
    time.sleep(0.5)
    started = time.monotonic()
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=5)
    assert process.returncode == 0 and time.monotonic() - started < 2


# The check of the openDesk waves without a change (zone.py opendesk_changes()) ---------------------------------------

LOCAL_MODULE_DIRS = (K3S / 'zones', K3S, K3S / 'hoover' / 'stores')


def local_modules(path, seen):
    """The k3s modules that a file imports, and the modules that they import."""
    import re
    for name in re.findall(r'^\s*(?:import|from)\s+([A-Za-z_]\w*)', path.read_text(), re.M):
        found = next((d / f'{name}.py' for d in LOCAL_MODULE_DIRS if (d / f'{name}.py').exists()), None)
        if found and found not in seen:
            seen.add(found)
            local_modules(found, seen)
    return seen


def test_the_inputs_name_every_module_and_table_that_the_post_renderer_reads():
    import re
    sources = {K3S / s for s in zone.INPUT_SOURCES}
    modules = local_modules(K3S / 'zones/postrender.py', set())
    assert modules - sources == set()
    # The tables that the modules of zones/ read by their file name.
    for module in [m for m in modules if m.parent == K3S / 'zones'] + [K3S / 'zones/postrender.py']:
        for name in re.findall(r"'([\w-]+\.(?:json|yaml|rb|py))'", module.read_text()):
            for folder in (module.parent, K3S / 'cluster'):
                if (folder / name).is_file():
                    assert folder / name in sources, f'{module.name} reads {name}'
    # postrender.py reads its patch files from these folders.
    assert {'zones/synapse', 'zones/openproject'} <= set(zone.INPUT_SOURCES)
    # The scripts of step 6 that zone.py and zone-patches.py run.
    for script in re.findall(r"HERE / '([\w.-]+)'", (K3S / 'zones/zone.py').read_text()):
        if script.startswith('zone-') and (K3S / 'zones' / script).is_file() and script != 'zone-state.example.json':
            assert f'zones/{script}' in zone.INPUT_SOURCES, script
    for script in re.findall(r"lab/'([\w.-]+)'", (K3S / 'zones/zone-patches.py').read_text()):
        assert f'zones/{script}' in zone.INPUT_SOURCES, script


def test_every_helmfile_process_reads_the_charts_from_the_shared_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(zone, 'PRIVATE', tmp_path)
    monkeypatch.setattr(zone, 'CHART_CACHE', tmp_path / 'opendesk-charts')
    (tmp_path / 'zones/zone-a').mkdir(parents=True)
    (tmp_path / 'zones/zone-a/master-password').write_text('x\n')
    assert zone.helmfile_env('zone-a')['HELMFILE_CACHE_HOME'] == str(tmp_path / 'opendesk-charts')
    env = zone.helmfile_env('zone-a', tmp_path / 'home')
    assert env['HELMFILE_CACHE_HOME'] == str(tmp_path / 'opendesk-charts')
    # Each process keeps its own Helm cache and configuration.
    assert env['HELM_CACHE_HOME'] == str(tmp_path / 'home/helm-cache')
    assert (tmp_path / 'opendesk-charts').is_dir()


RELEASES = {'nubus': {'revision': '4', 'status': 'deployed', 'chart': 'nubus-1.0'},
            'xwiki': {'revision': '7', 'status': 'deployed', 'chart': 'xwiki-2.0'}}


@pytest.fixture
def recorded(monkeypatch):
    inputs = {'source/zones/postrender.py': 'a', 'state/zones/zone-a/values.yaml': 'b'}
    record = {'digest': zone.sha(inputs), 'inputs': inputs, 'releases': RELEASES}
    monkeypatch.setattr(zone, 'first_bootstrap', lambda z: False)
    monkeypatch.setattr(zone, 'read_record', lambda z: record)
    return inputs, record


def test_the_waves_skip_only_with_the_same_inputs_and_the_same_releases(recorded, monkeypatch):
    inputs, record = recorded
    assert zone.opendesk_changes('zone-a', dict(inputs), json.loads(json.dumps(RELEASES))) == []
    # A changed input names itself, without its value.
    assert zone.opendesk_changes('zone-a', {**inputs, 'state/zones/zone-a/values.yaml': 'c'}, RELEASES) == [
        'state/zones/zone-a/values.yaml changed']
    assert zone.opendesk_changes('zone-a', {**inputs, 'source/zones/new.py': 'd'}, RELEASES) == ['source/zones/new.py changed']
    # A Helm upgrade, a rollback, a removed release or a failed release since the record runs the waves.
    upgraded = {**RELEASES, 'xwiki': {**RELEASES['xwiki'], 'revision': '8'}}
    assert zone.opendesk_changes('zone-a', inputs, upgraded) == ['release xwiki changed by revision or chart']
    assert zone.opendesk_changes('zone-a', inputs, {'nubus': RELEASES['nubus']}) == ['release xwiki changed by revision or chart']
    failed = {**RELEASES, 'nubus': {**RELEASES['nubus'], 'status': 'failed'}}
    assert 'release nubus is failed' in zone.opendesk_changes('zone-a', inputs, failed)
    # Without a record, and before the first complete install, the waves run.
    monkeypatch.setattr(zone, 'read_record', lambda z: None)
    assert zone.opendesk_changes('zone-a', inputs, RELEASES) == ['no record of a complete run']
    monkeypatch.setattr(zone, 'read_record', lambda z: record)
    monkeypatch.setattr(zone, 'first_bootstrap', lambda z: True)
    assert zone.opendesk_changes('zone-a', inputs, RELEASES) == ['the first install of the zone has not completed']


@pytest.mark.parametrize('full, changes, waves', [(False, [], False), (False, ['x changed'], True), (True, [], True)])
def test_a_zone_apply_without_a_change_runs_only_the_discovery_check(monkeypatch, full, changes, waves):
    calls = []
    for name in ('register', 'images', 'cluster', 'namespaces', 'hoover'):
        monkeypatch.setattr(zone, name, lambda *a, **kw: None)
    monkeypatch.setattr(zone.clusterstate, 'checkpoint', lambda folder: None)
    monkeypatch.setattr(zone.zonestate, 'enabled', lambda z: True)
    monkeypatch.setattr(zone, 'run', lambda *args, **kw: calls.append([str(a).rsplit('/', 1)[-1] for a in args[1:]]))
    monkeypatch.setattr(zone, 'apply_manifest', lambda *a, **kw: None)
    monkeypatch.setattr(zone, 'opendesk_inputs', lambda z: {'a': '1'})
    monkeypatch.setattr(zone, 'helm_revisions', lambda z: RELEASES)
    monkeypatch.setattr(zone, 'opendesk_changes', lambda z, inputs, releases: changes)
    monkeypatch.setattr(zone, 'opendesk', lambda z: calls.append(['waves']))
    monkeypatch.setattr(zone, 'write_record', lambda z, inputs: calls.append(['record', inputs]))
    gate = type(sys)('gate')
    gate.objects = lambda z: []
    monkeypatch.setitem(sys.modules, 'gate', gate)
    monkeypatch.setattr(zone.settings, 'zone_host', lambda z, app: f'{z}-{app}.test', raising=False)
    zone.apply('zone-a', full=full)
    calls = [c for c in calls if c[0] not in ('zones.py', 'write-password-table.py')]
    names = [c[0] for c in calls]
    if waves:
        assert names == ['waves', 'zone-login-no-mfa.sh', 'zone-users.py', 'zone-patches.py', 'record']
        assert calls[3] == ['zone-patches.py', 'zone-a'] and calls[4] == ['record', {'a': '1'}]
    else:
        assert 'waves' not in names and 'record' not in names
        assert ['zone-patches.py', 'zone-a', '--discovery'] in calls
        assert 'zone-users.py' not in names and 'zone-login-no-mfa.sh' not in names


def test_a_zone_operation_outside_up_ensures_the_pools(monkeypatch):
    import zone
    ran = []
    monkeypatch.setattr(zone, 'run', lambda *argv, **kw: ran.append([str(a) for a in argv]))
    monkeypatch.delenv('HOOVER4_POOLS_STEP', raising=False)
    zone.pools()
    assert ran and ran[0][-2:] == [str(zone.SOURCE / 'hoover' / 'pools.py'), 'ensure']
    ran.clear()
    monkeypatch.setenv('HOOVER4_POOLS_STEP', '1')
    zone.pools()
    assert ran == []
