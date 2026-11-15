#!/usr/bin/env python3
"""Pull the zone images on every eligible node, so a pod that the scheduler moves to any node starts without a pull.

Usage: prepull.py [--timeout SECONDS] [image ...]
The images are the arguments (deploy-k3s up gives the Hoover images of the revision) and the images of the containers
and init containers of the pods in the zone namespaces (label hoover.dev/zone=true) and in calls. An eligible node is
Ready, schedulable and has no NoSchedule or NoExecute taint, so a GPU node is left out.
For each node the script starts one pod prepull-<node> in kube-system, bound to the node. Its first init container
copies the static busybox binary into an emptyDir volume. Each further init container uses one image and runs that
binary as true, so the kubelet pulls the image (imagePullPolicy IfNotPresent) and the container ends at once, also in
an image without a shell. The containers request no CPU and no memory, so a full node admits the pod. The nodes pull at the same time. The kubelet of a node pulls one image after the other.
The script waits until each pod has succeeded, then deletes the pods. It fails with the node and the image of a pod
that did not succeed before the timeout (default 1800 s). KUBECONFIG names the admin kubeconfig.
"""
import argparse
import json
import os
import subprocess
import sys
import time

NAMESPACE = 'kube-system'
BUSYBOX = 'docker.io/library/busybox:1.37.0-musl@sha256:f6a95d611e0a8780fabdb2aec43e31275b2720dfefa3e41b16835bfc42454478'
LABEL = 'hoover.dev/prepull'


def kubectl(*args, input=None, check=True):
    command = ['kubectl'] + (['--kubeconfig', os.environ['KUBECONFIG']] if os.environ.get('KUBECONFIG') else [])
    result = subprocess.run(command + list(args), input=input, capture_output=True, text=True)
    if check and result.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:3])} failed: {result.stderr.strip()[-300:]}')
    return result.stdout


def eligible_nodes(nodes):
    out = []
    for node in nodes:
        ready = any(c['type'] == 'Ready' and c['status'] == 'True' for c in node.get('status', {}).get('conditions', []))
        taints = [t for t in node['spec'].get('taints', []) if t.get('effect') in ('NoSchedule', 'NoExecute')]
        if ready and not node['spec'].get('unschedulable') and not taints:
            out.append(node['metadata']['name'])
    return sorted(out)


def pod_images(pods):
    images = set()
    for pod in pods:
        spec = pod['spec']
        for c in spec.get('containers', []) + spec.get('initContainers', []):
            images.add(c['image'])
    return images


def pod(node, images):
    """The pull pod of one node."""
    tools = {'name': 'tools', 'mountPath': '/prepull'}
    # The pod is bound to its node, so the kubelet admits it without the scheduler and refuses it when the requests do
    # not fit (OutOfcpu, OutOfmemory). A node can have all of its CPU or memory requested. The containers only start an
    # image and end, so they request nothing.
    small = {'requests': {'cpu': '0', 'memory': '0'}, 'limits': {'cpu': '200m', 'memory': '64Mi'}}
    init = [{'name': 'copy-true', 'image': BUSYBOX, 'command': ['/bin/busybox', 'cp', '/bin/busybox', '/prepull/true'],
             'resources': small, 'volumeMounts': [tools]}]
    for index, image in enumerate(images):
        init.append({'name': f'pull-{index}', 'image': image, 'imagePullPolicy': 'IfNotPresent', 'command': ['/prepull/true'],
                     'resources': small, 'volumeMounts': [tools], 'securityContext': {'runAsUser': 0}})
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': f'prepull-{node}', 'namespace': NAMESPACE, 'labels': {LABEL: 'true'},
                         'annotations': {'hoover.dev/images': json.dumps(images)}},
            'spec': {'nodeName': node, 'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                     'enableServiceLinks': False, 'terminationGracePeriodSeconds': 1, 'initContainers': init,
                     'containers': [{'name': 'done', 'image': BUSYBOX, 'command': ['/bin/busybox', 'true'], 'resources': small}],
                     'volumes': [{'name': 'tools', 'emptyDir': {}}]}}


def problem(item, images):
    """The node and the image of a pull pod that waits or failed, from its init container states."""
    for index, status in enumerate(item.get('status', {}).get('initContainerStatuses', [])):
        state = status.get('state', {})
        reason = (state.get('waiting') or {}).get('reason') or (state.get('terminated') or {}).get('reason')
        if reason and reason not in ('PodInitializing', 'Completed') and index > 0:
            return f"{item['spec']['nodeName']}: {images[index - 1]}: {reason}"
    return f"{item['spec']['nodeName']}: phase {item.get('status', {}).get('phase', 'unknown')}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('images', nargs='*')
    args = parser.parse_args()
    namespaces = [n['metadata']['name'] for n in json.loads(kubectl('get', 'namespaces', '-l', 'hoover.dev/zone=true', '-o', 'json'))['items']]
    found = set(args.images)
    for namespace in namespaces + ['calls']:
        found |= pod_images(json.loads(kubectl('-n', namespace, 'get', 'pods', '-o', 'json', check=False) or '{"items": []}')['items'])
    images = sorted(found)
    nodes = eligible_nodes(json.loads(kubectl('get', 'nodes', '-o', 'json'))['items'])
    kubectl('-n', NAMESPACE, 'delete', 'pod', '-l', f'{LABEL}=true', '--ignore-not-found', '--wait=true')
    started = time.monotonic()
    kubectl('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': [pod(n, images) for n in nodes]}))
    deadline = started + args.timeout
    while True:
        items = json.loads(kubectl('-n', NAMESPACE, 'get', 'pods', '-l', f'{LABEL}=true', '-o', 'json'))['items']
        phases = {i['spec']['nodeName']: i.get('status', {}).get('phase') for i in items}
        failed = [problem(i, images) for i in items if phases[i['spec']['nodeName']] == 'Failed']
        if failed or all(p == 'Succeeded' for p in phases.values()) or time.monotonic() > deadline:
            break
        time.sleep(5)
    waiting = [problem(i, images) for i in items if i.get('status', {}).get('phase') not in ('Succeeded', 'Failed')]
    kubectl('-n', NAMESPACE, 'delete', 'pod', '-l', f'{LABEL}=true', '--ignore-not-found', '--wait=false')
    print(json.dumps({'nodes': nodes, 'images': len(images), 'seconds': int(time.monotonic() - started),
                      'failed': failed, 'waiting': waiting}), flush=True)
    if failed or waiting:
        raise SystemExit('the pull of the zone images did not finish: ' + '; '.join(failed + waiting))


if __name__ == '__main__':
    sys.exit(main())
