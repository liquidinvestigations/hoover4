#!/usr/bin/env python3
"""Render and install the shared GPU pool on the GPU nodes of a site.

The [gpu_pool] section of the site file names the GPU nodes (nodes = ...). Each GPU node runs the GPU services of the
ai_services Compose files, as `./deploy --ai-services` starts them on a GPU host: the model server (hoover4-vllm), the
NER, embedding and reranker server (hoover4-ai-server) and EasyOCR (hoover4-easyocr-gpu). compose.load_ai() reads them
from hoover4.ini.release, so the commands, the environment and the limits stay those of Compose.

Runtime (the cluster setting gpu.runtime of the operator settings):
- runsc: the RuntimeClass gvisor-gpu, gVisor with nvproxy. ../../hosts/root-install-k3s.py registers its handler on a
  GPU node, with the runsc build of gVisor PR 16643 when stage-runsc-nvproxy.sh staged it (decision D3).
- runc: the RuntimeClass nvidia of the NVIDIA container toolkit. This is the fallback of decision D20, when the GPU
  services do not work in gVisor after a bounded diagnosis. Record the failure before an operator selects it.
Authentication: the gateway of each GPU node accepts a request on the ports 21960, 21961 and 21962 only with the
header `Authorization: Bearer <pool key>`, where the pool key is the content of [gpu_pool] api_key_file. It sends the
key on to the model server, which checks it too, and no key to the other services. The gateway listens on the VPN
address of its node, so the gpu-proxy of another installation of the shared pool reaches it (decision D27), and on the
Service gateway inside the cluster. ../../hoover/gpu.py sends the key on every port to a pool of GPU nodes.
Model caches stay on the GPU node below <data_root>/gpu/<Compose volume folder>, so a new pod keeps the downloaded
models. The images are hoover-ai-server, hoover-easyocr and hoover-vllm of the registry, which
../../images/build-hoover.py --gpu builds for the architecture of the GPU nodes.
Usage: gpu_pool.py show|apply [--site FILE] [--revision REV] [--state FOLDER]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parents[1]
sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'hoover'))
import config as site_config  # noqa: E402
import settings as k3s_settings  # noqa: E402
import compose  # noqa: E402
import manifests  # noqa: E402

NS = 'gpu-pool'
NGINX = 'docker.io/library/nginx:1.29.3-alpine@sha256:b3c656d55d7ad751196f21b7fd2e8d4da9cb430e32f646adcf92441b72f82b14'
# The Compose service, its image key in compose.GPU_IMAGES, the port of the pool and whether the service checks the key.
SERVICES = {'hoover4-vllm': ('vllm', 21960, True), 'hoover4-ai-server': ('ai-server', 21961, False),
            'hoover4-easyocr-gpu': ('easyocr', 21962, False)}
RUNTIMES = {'runsc': 'gvisor-gpu', 'runc': 'nvidia'}
TOLERATION = {'key': 'hoover.dev/gpu', 'operator': 'Equal', 'value': 'true', 'effect': 'NoSchedule'}


def gpu_services(tree=site_config.REPO):
    """The merged GPU services of hoover4.ini.release, with every GPU service on."""
    text = (Path(tree) / 'hoover4.ini.release').read_text()
    with tempfile.TemporaryDirectory() as folder:
        ini = Path(folder) / 'hoover4.ini'
        # The release file names a volumes folder of a Compose host. The render maps each volume itself.
        text = re.sub(r'(?m)^volumes_path\s*=.*$', f'volumes_path = {folder}', text)
        for key in ('enabled', 'llm_enabled', 'ai_server_enabled', 'easyocr_enabled'):
            text = re.sub(rf'(?m)^{key}\s*=.*$', f'{key} = true', text)
        ini.write_text(text)
        _, _, _, services = compose.load_ai(ini, tree)
    return services


def container_port(service_def):
    for p in service_def.get('ports') or []:
        return int(str(p.get('target') if isinstance(p, dict) else p).rsplit(':', 1)[-1].split('/')[0])
    return 8000


def volumes(node, service_def):
    pod, mounts = [], []
    for spec in service_def.get('volumes') or []:
        source, target, read_only = compose.volume_parts(spec)
        if target.startswith('/run/secrets/'):
            pod.append({'name': 'pool-key', 'secret': {'secretName': 'gpu-pool', 'items': [{'key': 'pool-key', 'path': 'value'}]}})
            mounts.append({'name': 'pool-key', 'mountPath': target, 'subPath': 'value', 'readOnly': True})
            continue
        folder = Path(source).name
        name = 'cache-' + folder.replace('_', '-')
        pod.append({'name': name, 'hostPath': {'path': f'{node.data_root}/gpu/{folder}', 'type': 'DirectoryOrCreate'}})
        mounts.append({'name': name, 'mountPath': target, **({'readOnly': True} if read_only else {})})
    if service_def.get('shm_size'):
        pod.append({'name': 'shm', 'emptyDir': {'medium': 'Memory', 'sizeLimit': manifests.quantity(service_def['shm_size'], '1Gi')}})
        mounts.append({'name': 'shm', 'mountPath': '/dev/shm'})
    return pod, mounts


def service_objects(node, name, service_def, runtime, revision):
    key, _, _ = SERVICES[name]
    app = f'{key}-{node.name}'
    labels = {'app.kubernetes.io/name': app, 'hoover.dev/gpu-service': key}
    pod_volumes, mounts = volumes(node, service_def)
    memory, cpu = manifests.limits(service_def)
    env = {k: v for k, v in service_def.get('environment', {}).items()}
    env.setdefault('NVIDIA_VISIBLE_DEVICES', 'all')
    env.setdefault('NVIDIA_DRIVER_CAPABILITIES', 'compute,utility')
    port = container_port(service_def)
    c = {'name': key, 'image': f'{manifests.REGISTRY}/hoover-{key}:{manifests.image_tag(revision)}', 'imagePullPolicy': 'IfNotPresent',
         'env': [{'name': k, 'value': str(v)} for k, v in sorted(env.items())],
         'ports': [{'name': 'http', 'containerPort': port}],
         'resources': {'requests': {'cpu': '500m', 'memory': '1Gi'}, 'limits': {'memory': memory, **({'cpu': str(cpu)} if cpu else {})}},
         'volumeMounts': mounts}
    for field in ('entrypoint', 'command'):
        value = service_def.get(field)
        if value:
            c['command' if field == 'entrypoint' else 'args'] = value if isinstance(value, list) else ['sh', '-c', value]
    check = manifests.probe(service_def)
    if check:
        # A model server loads its weights for minutes before it answers its health check.
        c['startupProbe'] = {**check, 'failureThreshold': 120, 'periodSeconds': 15}
        c['readinessProbe'] = check
    spec = {'enableServiceLinks': False, 'automountServiceAccountToken': False, 'runtimeClassName': RUNTIMES[runtime],
            'nodeSelector': {'kubernetes.io/hostname': node.name}, 'tolerations': [TOLERATION],
            'terminationGracePeriodSeconds': 60, 'containers': [c], 'volumes': pod_volumes}
    return [
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': app, 'namespace': NS, 'labels': labels},
         'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': {'app.kubernetes.io/name': app}},
                  'template': {'metadata': {'labels': labels}, 'spec': spec}}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': app, 'namespace': NS},
         'spec': {'selector': {'app.kubernetes.io/name': app}, 'ports': [{'name': 'http', 'port': port, 'targetPort': port}]}},
    ]


def gateway(node, services):
    """The nginx gateway of one GPU node. It checks the pool key on every port."""
    servers = ''
    for name, (key, port, checks) in SERVICES.items():
        if name not in services:
            continue
        target = f'{key}-{node.name}.{NS}.svc.cluster.local:{container_port(services[name])}'
        servers += f'''
  server {{
    listen {port};
    location / {{
      if ($http_authorization != "Bearer ${{POOL_KEY}}") {{ return 403; }}
      proxy_pass http://{target};
      proxy_set_header Authorization {'$http_authorization' if checks else '""'};
      proxy_http_version 1.1;
      proxy_buffering off;
      proxy_request_buffering off;
      proxy_read_timeout 900s;
      proxy_send_timeout 900s;
      client_max_body_size 512m;
    }}
  }}'''
    config = {'default.conf.template': f'# The GPU pool gateway of {node.name} (k3s/platform/gpu/gpu_pool.py).\n'
                                       f'log_format pool \'$time_iso8601 $remote_addr $server_port $request_method $uri $status $request_time\';\n'
                                       f'access_log /dev/stdout pool;{servers}\n'}
    name = f'gateway-{node.name}'
    labels = {'app.kubernetes.io/name': name, 'hoover.dev/gpu-gateway': 'true'}
    ports = [p for n, (_, p, _) in SERVICES.items() if n in services]
    container = {'name': 'nginx', 'image': NGINX,
                 'env': [{'name': 'POOL_KEY', 'valueFrom': {'secretKeyRef': {'name': 'gpu-pool', 'key': 'pool-key'}}},
                         {'name': 'NGINX_ENVSUBST_FILTER', 'value': '^POOL_KEY$'}],
                 # The gateway listens on the VPN address of the node, so the installations of the shared pool reach it.
                 'ports': [{'name': f'p{p}', 'containerPort': p, **({'hostPort': p, 'hostIP': node.vpn_address} if node.vpn_address else {})}
                           for p in ports],
                 'readinessProbe': {'tcpSocket': {'port': ports[0]}, 'periodSeconds': 5},
                 'resources': {'requests': {'cpu': '20m', 'memory': '32Mi'}, 'limits': {'cpu': '2', 'memory': '256Mi'}},
                 'volumeMounts': [{'name': 'config', 'mountPath': '/etc/nginx/templates', 'readOnly': True}]}
    spec = {'enableServiceLinks': False, 'automountServiceAccountToken': False, 'runtimeClassName': 'gvisor',
            'nodeSelector': {'kubernetes.io/hostname': node.name}, 'tolerations': [TOLERATION], 'containers': [container],
            'volumes': [{'name': 'config', 'configMap': {'name': name}}]}
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:12]
    return [
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name, 'namespace': NS}, 'data': config},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': name, 'namespace': NS, 'labels': labels},
         'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': {'app.kubernetes.io/name': name}},
                  'template': {'metadata': {'labels': labels, 'annotations': {'hoover.dev/config': digest}}, 'spec': spec}}},
    ]


def objects(site, runtime, revision, tree=site_config.REPO):
    pool = site.gpu_pool
    if not pool.get('nodes'):
        raise SystemExit('[gpu_pool] names no GPU nodes of the site. A pool at an address runs outside this site.')
    services = {n: d for n, d in gpu_services(tree).items() if n in SERVICES}
    items = [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS}}]
    ports = [p for n, (_, p, _) in SERVICES.items() if n in services]
    for node_name in pool['nodes']:
        node = site.nodes[node_name]
        for name, service_def in services.items():
            items += service_objects(node, name, service_def, runtime, revision)
        items += gateway(node, services)
    items.append({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': 'gateway', 'namespace': NS},
                  'spec': {'selector': {'hoover.dev/gpu-gateway': 'true'}, 'ports': [{'name': f'p{p}', 'port': p, 'targetPort': p} for p in ports]}})
    # The GPU services take connections from the gateways only. The gateways take them from the gpu-proxy of this
    # cluster, and from other installations through the host port on the VPN address.
    items += [
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'services-from-gateway', 'namespace': NS},
         'spec': {'podSelector': {'matchExpressions': [{'key': 'hoover.dev/gpu-service', 'operator': 'Exists'}]}, 'policyTypes': ['Ingress'],
                  'ingress': [{'from': [{'podSelector': {'matchLabels': {'hoover.dev/gpu-gateway': 'true'}}}]}]}},
    ]
    return items


def runtime_setting(site, state=None):
    folder = Path(state) if state else site.operator_state()
    sys.path.insert(0, str(K3S / 'platform/operator'))
    operator = manifests.operator_settings
    overrides = operator.State(folder).overrides() if (folder / 'desired.json').exists() else {}
    return operator.effective('cluster', overrides.get('cluster', {}))['gpu.runtime']


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('show', 'apply'))
    parser.add_argument('--site', default=os.environ.get('HOOVER4_SITE', str(site_config.DEFAULT_SITE)))
    parser.add_argument('--revision')
    parser.add_argument('--state')
    args = parser.parse_args(argv)
    site = site_config.read(args.site)
    revision = args.revision or manifests.resolve_revision()
    items = objects(site, runtime_setting(site, args.state), revision)
    text = json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}, indent=1, sort_keys=True)
    if args.command == 'show':
        print(text)
        return
    kubectl = ['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG]
    key = Path(site.gpu_pool['api_key_file']).read_text().strip()
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'gpu-pool', 'namespace': NS}, 'type': 'Opaque',
              'stringData': {'pool-key': key}}
    subprocess.run(kubectl + ['apply', '-f', '-'], input=json.dumps(items[0]), text=True, check=True)
    subprocess.run(kubectl + ['apply', '-f', '-'], input=json.dumps(secret), text=True, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(kubectl + ['apply', '--server-side', '--force-conflicts', '--field-manager=hoover', '-f', '-'], input=text, text=True, check=True)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except site_config.SiteError as error:
        raise SystemExit(str(error))
