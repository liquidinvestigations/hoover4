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
    for name in ('status', 'events', 'zones', 'settings_overview'):
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


ROUTES = ('/status.json', '/events.json', '/zones.json', '/settings.json')


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
    monkeypatch.setattr(module, 'zones', lambda: {'nodes': ['node-a']})
    monkeypatch.setattr(module, 'operations', lambda: [])
    created = []
    monkeypatch.setattr(module, 'api', lambda method, path, body=None, content=None: created.append(body) or {})
    for zone in ('/etc', 'zone-../x', 'zone-a/b', '../zone-a', 'zone-A', 'zone-' + 'a' * 13):
        with pytest.raises(module.Refused):
            module.create_operation('admin', {'kind': 'create-zone', 'zone': zone, 'home': 'node-a'})
    with pytest.raises(module.Refused):
        module.create_operation('admin', {'kind': 'create-zone', 'zone': 'zone-a', 'home': '/srv'})
    with pytest.raises(module.Refused):
        module.onboarding('zone-a/../../secrets')
    assert module.create_operation('admin', {'kind': 'create-zone', 'zone': 'zone-a', 'home': 'node-a'})
    assert created[0]['data']['zone'] == 'zone-a'


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
    containers = {c['name']: c for c in pod['containers']}
    assert {c['image'] for c in containers.values()} == {'OPERATOR_IMAGE'}
    assert containers['portal']['args'] == ['portal'] and containers['runner']['args'] == ['runner']
    portal_mounts = {m['mountPath'] for m in containers['portal']['volumeMounts']}
    runner_mounts = {m['mountPath']: m['name'] for m in containers['runner']['volumeMounts']}
    assert '/site/site/zones' not in portal_mounts and runner_mounts['/site/site/zones'] == 'zone-secrets'
    assert runner_mounts['/var/run/zone-runner'] == 'runner-token'


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
