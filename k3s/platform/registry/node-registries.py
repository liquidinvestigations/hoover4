#!/usr/bin/env python3
"""Write /etc/rancher/k3s/registries.yaml on each node and restart k3s on a node whose file changed.

The file makes containerd pull registry.hoover.internal/<name:tag> from registry_endpoint of settings.json over HTTP.
A privileged pod with the host PID namespace does the change on each node, because the operator user has no root
login on every host. The pod compares the file first, so a second run changes and restarts nothing.
A changed node keeps a copy of its earlier file as registries.yaml.before-hoover-registry. k3s restarts five seconds
after the pod ends. The running pods of the node keep running.
Usage: node-registries.py [--check] [node ...]    Without nodes it covers every node.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import settings  # noqa: E402
K = ['kubectl', '--kubeconfig', settings.KUBECONFIG]
NAME = 'registry.hoover.internal'
IMAGE = 'docker.io/library/alpine:3.22'
SCRIPT = r'''
set -eu
f=/etc/rancher/k3s/registries.yaml
if [ "$(cat "$f" 2>/dev/null)" = "$WANT" ]; then echo current; exit 0; fi
if [ "$CHECK" = 1 ]; then echo differs; exit 0; fi
[ -e "$f" ] && [ ! -e "$f.before-hoover-registry" ] && cp -p "$f" "$f.before-hoover-registry"
printf '%s\n' "$WANT" > "$f.new" && chmod 600 "$f.new" && mv "$f.new" "$f"
unit=k3s-agent
systemctl is-active -q k3s && unit=k3s
systemd-run --quiet --on-active=5 --unit=hoover-registry-restart systemctl restart "$unit"
echo "changed, $unit restarts"
'''


def kubectl(*args, input=None, check=True):
    return subprocess.run(K + list(args), input=input, capture_output=True, text=True, check=check)


def wanted():
    endpoint = settings.HOST['registry_endpoint']
    return f'mirrors:\n  "{NAME}":\n    endpoint:\n      - "http://{endpoint}"'


def run(node, check):
    pod = f'node-registries-{node}'
    spec = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': pod, 'namespace': 'kube-system'},
            'spec': {'nodeName': node, 'hostPID': True, 'restartPolicy': 'Never', 'tolerations': [{'operator': 'Exists'}],
                     'containers': [{'name': 'host', 'image': IMAGE, 'securityContext': {'privileged': True},
                                     'env': [{'name': 'WANT', 'value': wanted()}, {'name': 'CHECK', 'value': '1' if check else '0'}],
                                     'command': ['nsenter', '-t', '1', '-m', '-u', '-i', '-n', '-p', '--', 'sh', '-c', SCRIPT]}]}}
    kubectl('-n', 'kube-system', 'delete', 'pod', pod, '--ignore-not-found', '--wait=true')
    kubectl('apply', '-f', '-', input=json.dumps(spec))
    deadline = time.time() + 180
    while time.time() < deadline:
        phase = kubectl('-n', 'kube-system', 'get', 'pod', pod, '-o', 'jsonpath={.status.phase}').stdout
        if phase in ('Succeeded', 'Failed'):
            break
        time.sleep(2)
    out = kubectl('-n', 'kube-system', 'logs', pod, check=False).stdout.strip()
    kubectl('-n', 'kube-system', 'delete', 'pod', pod, '--wait=false')
    print(json.dumps({'node': node, 'phase': phase, 'result': out}), flush=True)
    if phase != 'Succeeded':
        raise SystemExit(f'the pod on {node} ended in phase {phase or "unknown"}')


def main():
    check = '--check' in sys.argv
    nodes = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not nodes:
        # The server node comes last, because its k3s restart stops the API for a short time.
        items = json.loads(kubectl('get', 'nodes', '-o', 'json').stdout)['items']
        nodes = sorted((i['metadata']['name'] for i in items),
                       key=lambda n: any('node-role.kubernetes.io/control-plane' in i['metadata']['labels']
                                         for i in items if i['metadata']['name'] == n))
    for node in nodes:
        run(node, check)


if __name__ == '__main__':
    main()
