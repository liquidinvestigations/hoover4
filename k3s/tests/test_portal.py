"""The operator portal: every dynamic route needs the gateway secret, and only the portal receives that secret.

The portal server runs in this process on a free port. Its cluster functions return fixed data. No test contacts a
cluster.
"""
import functools
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
import yaml

from conftest import K3S

OPERATOR = K3S / 'platform/operator'
SECRET = 'portal-secret-value'


@pytest.fixture
def portal(monkeypatch):
    spec = importlib.util.spec_from_file_location('portal_server_test', OPERATOR / 'portal-server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PROXY_SECRET = SECRET
    for name in ('status', 'events', 'alarms', 'zones', 'settings_overview'):
        setattr(module, name, functools.partial(lambda n: {'route': n}, name))
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(module.Handler, directory=str(module.ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()


def get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


ROUTES = ('/status.json', '/events.json', '/alarms.json', '/zones.json', '/settings.json')


@pytest.mark.parametrize('path', ROUTES + tuple(r + '?x=1' for r in ROUTES))
def test_every_feed_refuses_a_missing_wrong_or_spoofed_secret(portal, path):
    for headers in ({}, {'X-Forwarded-User': 'admin'},
                    {'X-Forwarded-User': 'admin', 'X-Operator-Proxy-Secret': 'wrong'},
                    {'X-Operator-Proxy-Secret': SECRET}):
        status, body = get(portal + path, headers)
        assert status == 403, (path, headers)
        assert b'route' not in body
    status, body = get(portal + path, {'X-Forwarded-User': 'admin', 'X-Operator-Proxy-Secret': SECRET})
    assert status == 200 and 'route' in json.loads(body)


def test_health_answers_without_the_operator_and_gives_no_data(portal):
    status, body = get(portal + '/healthz')
    assert status == 200 and json.loads(body) == {'ok': True}
    assert get(portal + '/unknown.json')[0] == 404


def test_a_post_needs_the_operator_and_the_origin(portal):
    request = urllib.request.Request(portal + '/settings/save', data=b'{}', method='POST',
                                     headers={'X-Forwarded-User': 'admin', 'X-Operator-Proxy-Secret': 'wrong',
                                              'Origin': 'https://operator.hoover.test'})
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request, timeout=10)
    assert error.value.code == 403


def gateway():
    docs = [d for d in yaml.safe_load_all((OPERATOR / 'operator-login.yaml').read_text()) if d]
    config = next(d for d in docs if d['kind'] == 'ConfigMap' and d['metadata']['name'] == 'gateway')
    deployment = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == 'gateway')
    return config, deployment


def test_only_the_portal_hop_receives_the_secret():
    config, deployment = gateway()
    alpha = yaml.safe_load(config['data']['alpha.yaml'])
    injected = [h['name'] for h in alpha['injectRequestHeaders']]
    assert injected == ['X-Forwarded-User']
    upstreams = {u['id']: u['uri'] for u in alpha['upstreamConfig']['upstreams']}
    assert upstreams['portal'] == 'http://127.0.0.1:8081'
    assert all('127.0.0.1' not in uri for name, uri in upstreams.items() if name != 'portal')
    hop = config['data']['portal-hop.conf.template']
    assert 'listen 127.0.0.1:8081;' in hop
    assert 'proxy_set_header X-Operator-Proxy-Secret "${PROXY_SECRET}";' in hop
    assert 'proxy_pass http://portal.operator-portal.svc.cluster.local:8080;' in hop
    containers = {c['name']: c for c in deployment['spec']['template']['spec']['containers']}
    # oauth2-proxy no longer mounts the portal secret. Only the hop reads it.
    proxy_mounts = deployment['spec']['template']['spec']['volumes']
    secret_items = next(v for v in proxy_mounts if v['name'] == 'secrets')['secret']['items']
    assert 'proxy-secret' not in [i['key'] for i in secret_items]
    env = {e['name']: e for e in containers['portal-hop']['env']}
    assert env['PROXY_SECRET']['valueFrom']['secretKeyRef']['key'] == 'proxy-secret'
    assert 'PROXY_SECRET' not in json.dumps(containers['oauth2-proxy'])


def test_the_portal_probe_uses_the_health_route():
    docs = [d for d in yaml.safe_load_all((OPERATOR / 'operator-login.yaml').read_text()) if d]
    portal = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == 'portal')
    probe = portal['spec']['template']['spec']['containers'][0]['readinessProbe']
    assert probe == {'httpGet': {'path': '/healthz', 'port': 'http'}}


def test_zone_operations_accept_names_only(monkeypatch):
    spec = importlib.util.spec_from_file_location('portal_server_names', OPERATOR / 'portal-server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'operations', lambda: [])
    created = []
    monkeypatch.setattr(module, 'api', lambda method, path, body=None, content=None: created.append(body) or {})
    for zone in ('/etc', 'zone-../x', 'zone-a/b', '../zone-a', 'zone-A', 'zone-' + 'a' * 13):
        with pytest.raises(module.Refused):
            module.create_operation('admin', {'kind': 'create-zone', 'zone': zone})
    with pytest.raises(module.Refused):
        module.onboarding('zone-a/../../secrets')
    # A create names no home node. A home value of an earlier client has no effect and does not reach the operation.
    assert module.create_operation('admin', {'kind': 'create-zone', 'zone': 'zone-a'})
    assert module.create_operation('admin', {'kind': 'create-zone', 'zone': 'zone-b', 'home': '/srv'})
    assert [c['data']['zone'] for c in created] == ['zone-a', 'zone-b']
    assert all('home' not in c['data'] for c in created)


def test_the_gpu_key_needs_the_operator_and_reads_only_its_secret(portal, monkeypatch):
    for headers in ({'Origin': 'https://operator.hoover.test'},
                    {'X-Forwarded-User': 'admin', 'X-Operator-Proxy-Secret': SECRET}):
        request = urllib.request.Request(portal + '/gpu/key', data=b'{}', method='POST', headers=headers)
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=10)
        assert error.value.code == 403
    spec = importlib.util.spec_from_file_location('portal_server_gpu', OPERATOR / 'portal-server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import base64
    paths = []
    monkeypatch.setattr(module, 'api', lambda method, path, body=None, content=None:
                        paths.append((method, path)) or {'data': {'key': base64.b64encode(b'k123\n').decode()}})
    assert module.gpu_key() == {'key': 'k123'}
    assert paths == [('GET', '/api/v1/namespaces/operator-portal/secrets/gpu-api-key')]
    docs = [d for d in yaml.safe_load_all((OPERATOR / 'operator-login.yaml').read_text()) if d]
    role = next(d for d in docs if d['kind'] == 'Role' and d['metadata']['name'] == 'portal-operations')
    assert {'apiGroups': [''], 'resources': ['secrets'], 'resourceNames': ['gpu-api-key'], 'verbs': ['get']} in role['rules']


def test_the_operator_pod_mounts_no_host_folder_except_the_cgroup_and_keeps_zone_secrets_from_the_portal():
    docs = [d for d in yaml.safe_load_all((OPERATOR / 'operator-login.yaml').read_text()) if d]
    pod = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == 'portal')['spec']['template']['spec']
    host = [v for v in pod['volumes'] if 'hostPath' in v]
    assert [v['name'] for v in host] == ['cgroup']
    # The pod is bound to the control plane, so it may preempt a pod of the default priority there.
    assert pod['nodeSelector'] == {'kubernetes.io/hostname': 'CONTROL_PLANE'} and pod['priorityClassName'] == 'hoover-node-bound'
    containers = {c['name']: c for c in pod['containers']}
    assert {c['image'] for c in containers.values()} == {'OPERATOR_IMAGE'}
    assert containers['portal']['args'] == ['portal'] and containers['runner']['args'] == ['runner']
    portal_mounts = {m['mountPath'] for m in containers['portal']['volumeMounts']}
    runner_mounts = {m['mountPath']: m['name'] for m in containers['runner']['volumeMounts']}
    assert '/site/site/zones' not in portal_mounts and runner_mounts['/site/site/zones'] == 'zone-secrets'
    assert runner_mounts['/var/run/zone-runner'] == 'runner-token'


def test_the_backup_node_gets_the_operator_pod_and_only_the_runner_mounts_the_backup_folder():
    import copy
    spec = importlib.util.spec_from_file_location('backup_mount', OPERATOR / 'backup-mount.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    docs = [d for d in yaml.safe_load_all((OPERATOR / 'operator-login.yaml').read_text()) if d]
    # Without vars.backup the manifest stays as it is: the control plane and no backup mount.
    assert module.mount(copy.deepcopy(docs), {}) == docs
    backup = {'node': 'store', 'path': '/srv/hoover4-backups'}
    once = module.mount(copy.deepcopy(docs), backup)
    # A second render gives the same objects, so a second up changes nothing.
    assert module.mount(copy.deepcopy(once), backup) == once
    changed = [(a, b) for a, b in zip(docs, once) if a != b]
    assert [b['metadata']['name'] for _, b in changed] == ['portal']
    pod = changed[0][1]['spec']['template']['spec']
    assert pod['nodeSelector'] == {'kubernetes.io/hostname': 'store'}
    assert {'name': 'backups', 'hostPath': {'path': '/srv/hoover4-backups', 'type': 'Directory'}} in pod['volumes']
    containers = {c['name']: c for c in pod['containers']}
    assert {'name': 'backups', 'mountPath': '/srv/hoover4-backups'} in containers['runner']['volumeMounts']
    assert all(m['name'] != 'backups' for m in containers['portal']['volumeMounts'])
    # The host step gives the folders to the user of the pod.
    defaults = yaml.safe_load((K3S / 'ansible/roles/hoover4_host/defaults/main.yml').read_text())
    assert pod['securityContext']['runAsUser'] == pod['securityContext']['runAsGroup'] == defaults['hoover4_backup_uid']


def test_the_runner_frontend_step_checks_a_new_zone_and_skips_a_delete(tmp_path, monkeypatch):
    import sys
    from conftest import write_site
    site = write_site(tmp_path, 'remote.yml')
    monkeypatch.setenv('HOOVER4_SITE', str(site))
    monkeypatch.setenv('KUBECONFIG', str(tmp_path / 'none'))
    # The runner imports settings for the site of this test. The earlier modules come back after the test.
    for name in ('settings', 'zones', 'zonestate', 'clusterstate'):
        monkeypatch.setitem(sys.modules, name, None)
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location('runner_module', OPERATOR / 'runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner, 'LOGS', tmp_path / 'operations')
    calls = []
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *a, **k: calls.append(a))
    # A delete has no frontend step. An operation of an earlier version that lists it passes it without a warning.
    assert runner.STEPS['delete-zone'] == ['delete', 'calls']
    delete = runner.Operation({'metadata': {'name': 'op-1'}, 'data': {'kind': 'delete-zone', 'zone': 'zone-a'}})
    assert delete.step_frontend() is None
    create = runner.Operation({'metadata': {'name': 'op-2'}, 'data': {'kind': 'create-zone', 'zone': 'zone-a'}})
    monkeypatch.setattr(runner, 'frontend_problem', lambda zone: 'zone-a-portal.example: no certificate')
    with pytest.raises(RuntimeError, match='--steps frontend on the operator workstation, then select Run again'):
        create.step_frontend()
    monkeypatch.setattr(runner, 'frontend_problem', lambda zone: '')
    assert create.step_frontend() is None
    assert not calls


def test_the_settings_page_shows_the_pool_settings_once_for_the_site(tmp_path, monkeypatch):
    from conftest import REPO, operator_settings, write_site
    path = write_site(tmp_path, 'remote.yml')
    monkeypatch.setenv('HOOVER4_SITE', str(path))
    monkeypatch.setenv('PORTAL_REPO', str(REPO))
    monkeypatch.delenv('HOOVER4_CLUSTER_STATE', raising=False)
    spec = importlib.util.spec_from_file_location('portal_settings_test', OPERATOR / 'portal_settings.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    S = operator_settings()
    # A revision of an earlier version holds a pool setting in the scope of a site installation.
    S.State(module.site().operator_state()).save(0, {'hoover:zone-a': {'budget.clamav_memory_mib': '4096'}})
    nodes = {'server-a': {'cpus': 16, 'memory_mib': 65536}, 'worker-b': {'cpus': 16, 'memory_mib': 65536}}
    view = module.overview(nodes)
    scopes = {s['id']: s for s in view['scopes']}
    assert scopes['pools']['keys'] == list(S.POOLED)
    assert not set(S.POOLED) & set(scopes['hoover:zone-a']['keys'])
    # zone-c keeps its own copies, so its installation keeps the settings.
    assert set(S.POOLED) <= set(scopes['hoover:zone-c']['keys'])
    assert scopes['pools']['services']['budget.clamav_memory_mib'] == ['hoover4-clamav']
    assert 'budget.tika_cpus' in scopes['pools']['suggestions']
    assert 'budget.tika_cpus' not in scopes['hoover:zone-a']['suggestions']
    # The saved value has no effect, so it is no pending change.
    assert view['pending'] == []
    with pytest.raises(module.Refused) as refused:
        module.save('op', {'base': 1, 'changes': {'hoover:zone-a': {'budget.clamav_memory_mib': '5000'}}})
    assert 'processing pools' in refused.value.problems['hoover:zone-a/budget.clamav_memory_mib']
    # The page can remove the saved value, and the scope pools takes the change.
    assert module.save('op', {'base': 1, 'changes': {'hoover:zone-a': {'budget.clamav_memory_mib': None},
                                                   'pools': {'budget.clamav_memory_mib': '5000'}}}) == {'revision': 2}
    view = module.overview(nodes)
    # The budget value suggests the memory limit of ClamAV.
    assert view['pending'] == [{'scope': 'pools', 'key': 'budget.clamav_memory_mib', 'from': '3456', 'to': '5000'},
                               {'scope': 'pools', 'key': 'main_services.clamav_mem_limit', 'from': '3456M', 'to': '5000M'}]
    assert view['steps'] == ['pools'] and view['services'] == ['hoover4-clamav']


def test_the_alarm_list_leaves_out_watchdog_and_puts_critical_rows_first(monkeypatch):
    import io
    import types
    spec = importlib.util.spec_from_file_location('portal_server_alarms', OPERATOR / 'portal-server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    alerts = {'data': {'alerts': [
        {'state': 'firing', 'labels': {'alertname': 'Watchdog', 'severity': 'none'}, 'activeAt': '2026-01-01T00:00:00Z'},
        {'state': 'pending', 'labels': {'alertname': 'NodeMemoryLow', 'severity': 'critical'}},
        {'state': 'firing', 'labels': {'alertname': 'PodRestarts', 'severity': 'warning', 'namespace': 'a', 'pod': 'p'},
         'annotations': {'summary': 'restarted'}, 'activeAt': '2026-01-01T00:00:00Z'},
        {'state': 'firing', 'labels': {'alertname': 'NodeOutOfMemoryKill', 'severity': 'critical', 'instance': 'n:9100'},
         'annotations': {'description': 'x' * 400}, 'activeAt': '2026-01-02T00:00:00Z'}]}}
    urls = []
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda url, timeout: urls.append(url) or io.BytesIO(json.dumps(alerts).encode()))
    backup = {'source': 'backup', 'name': 'BackupPaused', 'severity': 'critical', 'summary': 's', 'since': ''}
    monkeypatch.setattr(module, 'portal_settings', lambda: types.SimpleNamespace(backup_alarms=lambda: [backup]))
    rows = module.alarms()
    assert urls == [module.PROMETHEUS + '/api/v1/alerts']
    assert [r['name'] for r in rows] == ['NodeOutOfMemoryKill', 'BackupPaused', 'PodRestarts']
    assert rows[0] == {'source': 'prometheus', 'name': 'NodeOutOfMemoryKill', 'severity': 'critical', 'summary': 'x' * 300,
                       'since': '2026-01-02T00:00:00Z', 'instance': 'n:9100'}
    assert rows[2]['namespace'] == 'a' and rows[2]['pod'] == 'p' and rows[2]['summary'] == 'restarted'
