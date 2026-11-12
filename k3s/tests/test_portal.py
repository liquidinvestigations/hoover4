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
