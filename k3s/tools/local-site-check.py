#!/usr/bin/env python3
"""Check the storage, the registry and a host-service restart of a single-node site. Usage: local-site-check.py [--restart]

In the namespace site-check the check:
  1. creates a 1 GiB claim of the default storage class and a Deployment whose image comes from the site registry
     (the whois MCP image of the deployed revision), which writes a file with its checksum,
  2. grows the claim to 2 GiB while the pod runs and reads the file system size in the pod,
  3. deletes the pod, waits for the new pod and reads the file again,
  4. with --restart, restarts k3s, hoover4-dns and hoover4-frontend with sudo -n, then reads the file a third time and
     asks the frontend for https://operator.<suffix>/.
It prints one JSON line for each step and deletes the namespace at the end. It changes no other object.
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

NS = 'site-check'
K = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG)]
IMAGE = 'registry.hoover.internal/hoover/hoover-mcp-whois:0b5763d36722'


def kubectl(*args, input=None, check=True):
    return subprocess.run(K + list(args), input=input, capture_output=True, text=True, check=check).stdout


def report(step, **fields):
    print(json.dumps({'at': time.strftime('%H:%M:%S'), 'step': step, **fields}), flush=True)


def pod_exec(command):
    pod = kubectl('-n', NS, 'get', 'pod', '-l', 'app=site-check', '-o', 'jsonpath={.items[0].metadata.name}')
    return kubectl('-n', NS, 'exec', pod, '--', 'sh', '-c', command).strip()


def wait_ready():
    kubectl('-n', NS, 'rollout', 'status', 'deployment/site-check', '--timeout=300s')
    deadline = time.time() + 120
    while time.time() < deadline:
        phases = kubectl('-n', NS, 'get', 'pods', '-l', 'app=site-check', '-o', 'jsonpath={.items[*].status.phase}').split()
        if phases == ['Running']:
            return
        time.sleep(2)
    raise SystemExit('the pod of site-check did not run alone')


def main():
    restart = '--restart' in sys.argv
    objects = {'apiVersion': 'v1', 'kind': 'List', 'items': [
        {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS}},
        {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'data', 'namespace': NS},
         'spec': {'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': '1Gi'}}}},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'site-check', 'namespace': NS},
         'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': {'app': 'site-check'}},
                  'template': {'metadata': {'labels': {'app': 'site-check'}}, 'spec': {
                      'containers': [{'name': 'c', 'image': IMAGE, 'imagePullPolicy': 'Always', 'command': ['sh', '-c',
                                      '[ -f /data/f ] || (head -c 33554432 /dev/urandom > /data/f && sync); sleep 100000'],
                                      'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
                      'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'data'}}]}}}},
    ]}
    try:
        kubectl('apply', '-f', '-', input=json.dumps(objects))
        wait_ready()
        events = kubectl('-n', NS, 'get', 'events', '--field-selector', 'reason=Pulled', '-o', 'jsonpath={.items[*].message}')
        report('registry-pull', image=IMAGE, event=events[-200:])
        first = pod_exec('sha256sum /data/f')
        size = pod_exec("df -k /data | tail -1 | awk '{print $2}'")
        report('provision', storage_class=kubectl('-n', NS, 'get', 'pvc', 'data', '-o', 'jsonpath={.spec.storageClassName}'),
               kib=int(size), sha256=first.split()[0])
        kubectl('-n', NS, 'patch', 'pvc', 'data', '-p', json.dumps({'spec': {'resources': {'requests': {'storage': '2Gi'}}}}))
        deadline = time.time() + 180
        grown = size
        while time.time() < deadline and int(grown) < 1.5 * 2 ** 20:
            time.sleep(3)
            grown = pod_exec("df -k /data | tail -1 | awk '{print $2}'")
        report('expand', kib_before=int(size), kib_after=int(grown),
               capacity=kubectl('-n', NS, 'get', 'pvc', 'data', '-o', 'jsonpath={.status.capacity.storage}'))
        kubectl('-n', NS, 'delete', 'pod', '-l', 'app=site-check', '--wait=true')
        wait_ready()
        second = pod_exec('sha256sum /data/f')
        report('pod-replaced', same_file=second == first)
        if restart:
            started = time.time()
            for unit in ('k3s.service', 'hoover4-dns.service', 'hoover4-frontend.service'):
                subprocess.run(['sudo', '-n', '/usr/bin/systemctl', 'restart', unit], check=True)
            deadline = time.time() + 300
            while time.time() < deadline:
                if subprocess.run(K + ['get', 'node', '--no-headers'], capture_output=True, text=True).stdout.count(' Ready ') == 1:
                    break
                time.sleep(5)
            wait_ready()
            third = pod_exec('sha256sum /data/f')
            code = urllib.request.urlopen(f'https://operator.{settings.SUFFIX}/oauth2/sign_in', timeout=20).status
            report('host-restart', seconds=round(time.time() - started), same_file=third == first, frontend_status=code)
    finally:
        kubectl('delete', 'namespace', NS, '--wait=true', check=False)
        report('cleanup', logical_volumes=kubectl('get', 'logicalvolumes.topolvm.io', '-o', 'name', check=False).count('\n'))


if __name__ == '__main__':
    main()
