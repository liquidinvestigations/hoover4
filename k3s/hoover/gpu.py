#!/usr/bin/env python3
"""The inference proxy between the Hoover installations and the shared GPU pool.

The GPU pool serves the three GPU services of ai_services: the model server (21960), the NER, embedding and reranker
server (21961) and EasyOCR (21962). Only the model server checks a key. The [gpu_pool] section of the site file
(../config.py) names the pool: the GPU nodes of the site, or the address of a shared pool, and the key file of the
model server.
- The Deployment gpu-proxy in the namespace gpu-proxy is the only cluster workload that reaches the pool. It accepts a
  request with the headers X-Hoover-Zone and X-Hoover-Zone-Token, where the token is the HMAC-SHA256 of the zone name
  with the proxy key. It answers 403 to any other request. It sends the model server key to the model server port and
  no key to the other ports. Its access log names the zone of each request.
- The Deployment gpu in each Hoover namespace adds the headers of its zone and forwards to gpu-proxy. Hoover names gpu
  as its GPU host (zone_ini.py), so the installation needs no change of the Hoover clients and never holds the key.
The proxy derives each token from the zone name, so a new zone needs no change of the proxy.
A pool of GPU nodes of the site (../platform/gpu/gpu_pool.py) has a gateway that checks the pool key on every port, so
the proxy sends the key on every port to it. A pool at an address is a Compose GPU host, so the proxy sends the key to
the model server port only.
The proxy key is k3s/private/gpu-proxy-key, which the script creates once.
Usage: gpu.py token <zone>             prints the token of a zone
       gpu.py install [<site.ini>]     applies the central proxy with the admin kubeconfig
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
PORTS = {21960: True, 21961: False, 21962: False}
KEY = settings.PRIVATE / 'gpu-proxy-key'


def site_pool(site_path=None):
    """The address and the model server key file of the GPU pool of the site file."""
    import config as site_config
    site = site_config.read(site_path or site_config.DEFAULT_SITE)
    pool = site.gpu_pool
    if not pool:
        raise SystemExit('the site file has no [gpu_pool] section.')
    if pool.get('nodes'):
        # The GPU nodes of the site run the pool with its gateway (../platform/gpu/gpu_pool.py).
        return {'address': 'gateway.gpu-pool.svc.cluster.local', 'api_key_file': pool['api_key_file'], 'gateway': True}
    return {'address': pool['address'], 'api_key_file': pool['api_key_file'], 'gateway': False}
# A model answer can take minutes, and an OCR request can carry a large image.
PROXY = '''proxy_http_version 1.1;
      proxy_buffering off;
      proxy_request_buffering off;
      proxy_read_timeout 900s;
      proxy_send_timeout 900s;
      client_max_body_size 512m;'''


def key():
    if not KEY.exists():
        KEY.write_text(secrets.token_hex(32))
        KEY.chmod(0o600)
    return KEY.read_text().strip()


def token(zone):
    return hmac.new(key().encode(), zone.encode(), hashlib.sha256).hexdigest()


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


def proxy(box):
    """The central proxy. The njs function checks the zone token with the proxy key."""
    vllm_key = Path(box['api_key_file']).read_text().strip()
    servers = ''.join(f'''
  server {{
    listen {p};
    location / {{
      if ($hoover_zone_ok != "yes") {{ return 403; }}
      proxy_pass http://{box["address"]}:{p};
      proxy_set_header X-Hoover-Zone "";
      proxy_set_header X-Hoover-Zone-Token "";
      proxy_set_header Authorization {'"Bearer ${VLLM_KEY}"' if checks or box.get('gateway') else '""'};
      {PROXY}
    }}
  }}''' for p, checks in PORTS.items())
    config = {
        'auth.js.template': '''// Accept a request when its zone token is the HMAC-SHA256 of the zone name with the proxy key.
const crypto = require('crypto');
function zone_ok(r) {
  const zone = r.headersIn['X-Hoover-Zone'] || '';
  const given = r.headersIn['X-Hoover-Zone-Token'] || '';
  if (!/^zone-[a-z0-9]{1,12}$/.test(zone)) return 'no';
  const want = crypto.createHmac('sha256', '${GPU_PROXY_KEY}').update(zone).digest('hex');
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
    env = [{'name': 'GPU_PROXY_KEY', 'valueFrom': {'secretKeyRef': {'name': 'gpu-proxy', 'key': 'proxy-key'}}},
           {'name': 'VLLM_KEY', 'valueFrom': {'secretKeyRef': {'name': 'gpu-proxy', 'key': 'vllm-key'}}},
           {'name': 'NGINX_ENVSUBST_FILTER', 'value': '^(GPU_PROXY_KEY|VLLM_KEY)$'},
           {'name': 'NGINX_ENVSUBST_OUTPUT_DIR', 'value': '/etc/nginx/conf.d'}]
    items = pod('gpu-proxy', NS, config, env, list(PORTS), runtime='gvisor', main=MAIN)
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'gpu-proxy', 'namespace': NS}, 'type': 'Opaque',
              'stringData': {'proxy-key': key(), 'vllm-key': vllm_key}}
    # Only the zone forwarders reach the proxy, and the proxy reaches only the GPU box and the cluster DNS.
    policy = {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'gpu-proxy', 'namespace': NS},
              'spec': {'podSelector': {}, 'policyTypes': ['Ingress', 'Egress'],
                       'ingress': [{'from': [{'namespaceSelector': {'matchLabels': {'hoover.dev/zone': 'true'}},
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
    items = {'apiVersion': 'v1', 'kind': 'List', 'items': proxy(site_pool(site_path))}
    subprocess.run(['kubectl', '--kubeconfig', settings.KUBECONFIG, 'apply', '-f', '-'], input=json.dumps(items), text=True, check=True)
    subprocess.run(['kubectl', '--kubeconfig', settings.KUBECONFIG, '-n', NS, 'rollout', 'status', 'deployment/gpu-proxy', '--timeout=300s'],
                   check=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == 'token':
        print(token(sys.argv[2]))
    elif sys.argv[1:2] == ['install'] and len(sys.argv) <= 3:
        install(sys.argv[2] if len(sys.argv) == 3 else None)
    else:
        sys.exit(__doc__)
