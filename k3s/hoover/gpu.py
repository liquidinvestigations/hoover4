#!/usr/bin/env python3
"""The inference proxy between the Hoover installations and the shared GPU pool.

The GPU pool serves the three GPU services of ai_services: the model server (21960), the NER, embedding and reranker
server (21961) and EasyOCR (21962). vars.gpu_pool of the site file (../config.py) names the pool: the GPU nodes of the
site, or the address of a shared pool, for example a Compose GPU host.
The installation has one GPU key. The script generates it once and keeps it in the Secret gpu-api-key of the namespace
operator-portal (api_key()). The operator portal shows it. Each GPU service checks it on every port except /health,
and a Compose GPU host needs the same key in its [ai_services] vllm_api_key_file.
- The Deployment gpu-proxy in the namespace gpu-proxy is the only cluster workload that reaches the pool. It accepts a
  request with the headers X-Hoover-Zone and X-Hoover-Zone-Token, where the token is the HMAC-SHA256 of the zone name
  with the GPU key. It answers 403 to any other request. It sends the GPU key on every port. Its access log names the
  zone of each request.
- The Deployment gpu in each Hoover namespace adds the headers of its zone and forwards to gpu-proxy. Hoover names gpu
  as its GPU host (zone_ini.py), so the installation needs no change of the Hoover clients and never holds the key.
  The processing pools of the site (pools.py) have their own forwarder with the name hoover-pools in place of a zone.
The proxy derives each token from the zone name, so a new zone needs no change of the proxy. A new GPU key changes
every token: run gpu.py install, ../platform/gpu/gpu_pool.py apply and ../zones/zone.py apply of each zone after it.
Usage: gpu.py token <zone>             prints the token of a zone
       gpu.py install [<site file>]    applies the central proxy with the admin kubeconfig
       gpu.py ensure-key               creates the GPU key when it is missing, and prints no key
       gpu.py key                      creates the GPU key when it is missing, and prints it
       gpu.py set-key                  replaces the GPU key with the key on standard input, for example the key of a
                                       Compose GPU host
"""
import hashlib
import hmac
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

NS = 'gpu-proxy'
NGINX = 'docker.io/library/nginx:1.29.3-alpine@sha256:b3c656d55d7ad751196f21b7fd2e8d4da9cb430e32f646adcf92441b72f82b14'
PORTS = (21960, 21961, 21962)
# The Secret of the GPU key. The operator portal reads it from its own namespace.
KEY_NAMESPACE = 'operator-portal'
KEY_SECRET = 'gpu-api-key'


def site_pool(site_path=None):
    """The address of the GPU pool of the site file, and whether it is the gateway of the GPU nodes of the site."""
    import config as site_config
    site = site_config.read(site_path or settings.SITE_FILE)
    pool = site.gpu_pool
    if not pool:
        raise SystemExit('the site file has no vars.gpu_pool.')
    if pool.get('nodes'):
        # The GPU nodes of the site run the pool with its gateway (../platform/gpu/gpu_pool.py).
        return {'address': 'gateway.gpu-pool.svc.cluster.local', 'gateway': True}
    return {'address': pool['address'], 'gateway': False}
# A model answer can take minutes, and an OCR request can carry a large image.
PROXY = '''proxy_http_version 1.1;
      proxy_buffering off;
      proxy_request_buffering off;
      proxy_read_timeout 900s;
      proxy_send_timeout 900s;
      client_max_body_size 512m;'''


def kubectl(*args, input=None, check=True):
    import subprocess
    return subprocess.run(['kubectl', '--kubeconfig', settings.KUBECONFIG, *args], input=input, text=True,
                          capture_output=True, check=check)


def secret_object(value):
    return {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque',
            'metadata': {'name': KEY_SECRET, 'namespace': KEY_NAMESPACE, 'labels': {'hoover.dev/secret': 'gpu-api-key'}},
            'stringData': {'key': value}}


def write_key(value):
    """Store a GPU key in the Secret gpu-api-key. The namespace is created when it is missing."""
    if not value or any(c.isspace() for c in value):
        raise SystemExit('a GPU key is one word without spaces.')
    kubectl('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'Namespace',
                                                   'metadata': {'name': KEY_NAMESPACE}}))
    kubectl('apply', '-f', '-', input=json.dumps(secret_object(value)))


def api_key(create=True):
    """The GPU key of the installation from the Secret gpu-api-key. Without the Secret, create=True generates a key and
    stores it, and create=False stops with a message."""
    import base64
    found = kubectl('-n', KEY_NAMESPACE, 'get', 'secret', KEY_SECRET, '--ignore-not-found', '-o', 'jsonpath={.data.key}').stdout
    if found.strip():
        return base64.b64decode(found.strip()).decode().strip()
    if not create:
        raise SystemExit(f'the Secret {KEY_SECRET} of {KEY_NAMESPACE} is missing. deploy-k3s up creates it.')
    write_key(secrets.token_hex(32))
    return api_key(create=False)


def zone_token(gpu_key, zone):
    """The token of a zone: the HMAC-SHA256 of the zone name with the GPU key."""
    return hmac.new(gpu_key.encode(), zone.encode(), hashlib.sha256).hexdigest()


def token(zone):
    return zone_token(api_key(), zone)


# The main configuration of the central proxy. It loads the njs module, which the image has and does not load.
MAIN = '''load_module modules/ngx_http_js_module.so;
worker_processes auto;
error_log /dev/stderr notice;
pid /tmp/nginx.pid;
events { worker_connections 4096; }
http {
  include /etc/nginx/conf.d/*.conf;
}
'''


def pod(name, namespace, config, env, ports, runtime=None, labels=None, main=None):
    labels = labels or {'app.kubernetes.io/name': name}
    mounts = [{'name': 'config', 'mountPath': '/etc/nginx/templates', 'readOnly': True}]
    if main:
        config = {**config, 'nginx.conf': main}
        mounts.append({'name': 'config', 'mountPath': '/etc/nginx/nginx.conf', 'subPath': 'nginx.conf', 'readOnly': True})
    container = {'name': 'nginx', 'image': NGINX, 'env': env,
                 'ports': [{'name': f'p{p}', 'containerPort': p} for p in ports],
                 'volumeMounts': mounts,
                 'readinessProbe': {'tcpSocket': {'port': ports[0]}, 'periodSeconds': 5},
                 'resources': {'requests': {'cpu': '20m', 'memory': '32Mi'}, 'limits': {'cpu': '2', 'memory': '256Mi'}}}
    spec = {'enableServiceLinks': False, 'automountServiceAccountToken': False, 'containers': [container],
            'volumes': [{'name': 'config', 'configMap': {'name': name}}]}
    if runtime:
        spec['runtimeClassName'] = runtime
    return [
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name, 'namespace': namespace}, 'data': config},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': name, 'namespace': namespace, 'labels': labels},
         'spec': {'replicas': 1, 'selector': {'matchLabels': labels},
                  'template': {'metadata': {'labels': labels, 'annotations': {'hoover.dev/config': hashlib.sha256(
                      json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]}}, 'spec': spec}}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name, 'namespace': namespace},
         'spec': {'selector': labels, 'ports': [{'name': f'p{p}', 'port': p, 'targetPort': p} for p in ports]}},
    ]


def forwarder(zone, namespace):
    """The forwarder gpu of a Hoover namespace. The template gets the token from the Secret hoover-runtime."""
    servers = ''.join(f'''
  server {{
    listen {p};
    location / {{
      proxy_pass http://gpu-proxy.{NS}.svc.cluster.local:{p};
      proxy_set_header X-Hoover-Zone {zone};
      proxy_set_header X-Hoover-Zone-Token ${{GPU_TOKEN}};
      {PROXY}
    }}
  }}''' for p in PORTS)
    config = {'default.conf.template': f'# The GPU forwarder of {zone} (k3s/hoover/gpu.py).{servers}\n'}
    env = [{'name': 'GPU_TOKEN', 'valueFrom': {'secretKeyRef': {'name': 'hoover-runtime', 'key': 'gpu-token'}}},
           # The template keeps the nginx variables, which start with $ and are not in this list.
           {'name': 'NGINX_ENVSUBST_FILTER', 'value': '^GPU_TOKEN$'}]
    return pod('gpu', namespace, config, env, list(PORTS))


def proxy(box, gpu_key):
    """The central proxy. The njs function checks the zone token with the GPU key, and every port sends the GPU key."""
    servers = ''.join(f'''
  server {{
    listen {p};
    location / {{
      if ($hoover_zone_ok != "yes") {{ return 403; }}
      proxy_pass http://{box["address"]}:{p};
      proxy_set_header X-Hoover-Zone "";
      proxy_set_header X-Hoover-Zone-Token "";
      proxy_set_header Authorization "Bearer ${{GPU_KEY}}";
      {PROXY}
    }}
  }}''' for p in PORTS)
    config = {
        'auth.js.template': '''// Accept a request when its zone token is the HMAC-SHA256 of the zone name with the GPU key.
const crypto = require('crypto');
function zone_ok(r) {
  const zone = r.headersIn['X-Hoover-Zone'] || '';
  const given = r.headersIn['X-Hoover-Zone-Token'] || '';
  if (!/^(zone-[a-z0-9]{1,12}|hoover-pools)$/.test(zone)) return 'no';
  const want = crypto.createHmac('sha256', '${GPU_KEY}').update(zone).digest('hex');
  return given.length === want.length && given === want ? 'yes' : 'no';
}
export default {zone_ok};
''',
        'default.conf.template': f'''# The central GPU proxy (k3s/hoover/gpu.py).
js_path /etc/nginx/conf.d;
js_import auth from auth.js;
js_set $hoover_zone_ok auth.zone_ok;
log_format zone '$time_iso8601 $http_x_hoover_zone $server_port $request_method $uri $status $request_time';
access_log /dev/stdout zone;{servers}
''',
    }
    env = [{'name': 'GPU_KEY', 'valueFrom': {'secretKeyRef': {'name': 'gpu-proxy', 'key': 'gpu-key'}}},
           {'name': 'NGINX_ENVSUBST_FILTER', 'value': '^GPU_KEY$'},
           {'name': 'NGINX_ENVSUBST_OUTPUT_DIR', 'value': '/etc/nginx/conf.d'}]
    items = pod('gpu-proxy', NS, config, env, list(PORTS), runtime='gvisor', main=MAIN)
    # A copy of the GPU key in the namespace of the proxy. The config hash of pod() does not see a new key, so the
    # Deployment carries the hash of the key too, and a new key restarts the proxy.
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'gpu-proxy', 'namespace': NS}, 'type': 'Opaque',
              'stringData': {'gpu-key': gpu_key}}
    items[1]['spec']['template']['metadata']['annotations']['hoover.dev/key'] = hashlib.sha256(gpu_key.encode()).hexdigest()[:12]
    # Only the zone forwarders and the forwarder of the processing pools (pools.py) reach the proxy, and the proxy
    # reaches only the GPU box and the cluster DNS.
    policy = {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'gpu-proxy', 'namespace': NS},
              'spec': {'podSelector': {}, 'policyTypes': ['Ingress', 'Egress'],
                       'ingress': [{'from': [{'namespaceSelector': {'matchLabels': {'hoover.dev/zone': 'true'}},
                                              'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'gpu'}}},
                                             {'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'hoover-pools'}},
                                              'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'gpu'}}}]}],
                       'egress': [{'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'gpu-pool'}}}
                                          if box.get('gateway') else {'ipBlock': {'cidr': f'{box["address"]}/32'}}],
                                   'ports': [{'port': p, 'protocol': 'TCP'} for p in PORTS]},
                                  {'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'kube-system'}},
                                           'podSelector': {'matchLabels': {'k8s-app': 'kube-dns'}}}],
                                   'ports': [{'port': 53, 'protocol': 'UDP'}, {'port': 53, 'protocol': 'TCP'}]}]}}
    return [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS}}, secret, *items, policy]


def install(site_path=None):
    """Apply the central proxy with the admin kubeconfig."""
    import subprocess
    items = {'apiVersion': 'v1', 'kind': 'List', 'items': proxy(site_pool(site_path), api_key())}
    subprocess.run(['kubectl', '--kubeconfig', settings.KUBECONFIG, 'apply', '-f', '-'], input=json.dumps(items), text=True, check=True)
    subprocess.run(['kubectl', '--kubeconfig', settings.KUBECONFIG, '-n', NS, 'rollout', 'status', 'deployment/gpu-proxy', '--timeout=300s'],
                   check=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'token':
        print(token(sys.argv[2]))
    elif sys.argv[1:] == ['ensure-key']:
        api_key()
        print(json.dumps({'gpu_key': f'Secret {KEY_SECRET} of {KEY_NAMESPACE}'}))
    elif sys.argv[1:] == ['key']:
        print(api_key())
    elif sys.argv[1:] == ['set-key']:
        write_key(sys.stdin.read().strip())
        print(json.dumps({'gpu_key': 'replaced', 'next': 'run gpu.py install, gpu_pool.py apply and zone.py apply of each zone'}))
    elif sys.argv[1:2] == ['install'] and len(sys.argv) <= 3:
        install(sys.argv[2] if len(sys.argv) == 3 else None)
    else:
        sys.exit(__doc__)
