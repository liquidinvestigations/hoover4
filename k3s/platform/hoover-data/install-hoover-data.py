#!/usr/bin/env python3
"""Install the NFS servers of the Hoover data directories (hoover_data.py). Usage: install-hoover-data.py [show]

The script builds the image nfs-server/ and applies, in the namespace hoover-data:
- for each data node of the zones in the zone state, the Deployment and the Service nfs-<node>, with the export table
  in the ConfigMap nfs-<node>. A changed table restarts the server.
- the ServiceAccount nfs-server, which can list namespaces, so the server creates the folders of a new zone.
- the NetworkPolicy nfs-from-nodes. Only the nodes reach port 2049, because the kubelet mounts the volumes from the
  node. A pod cannot reach the server, so it cannot read the folder of another zone with its own NFS client.
The server is privileged and mounts host paths, so it runs outside the zone namespaces with the admin kubeconfig.
show prints the objects and applies nothing.
"""
import hashlib
import ipaddress
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / 'zones'))
import settings  # noqa: E402
import zonestate  # noqa: E402
import hoover_data  # noqa: E402

settings.use_kubeconfig()
NS = hoover_data.NS
LABELS = {'app.kubernetes.io/name': 'nfs-server'}
EXPORT = 'sync,no_subtree_check,no_root_squash,insecure'


def kubectl(*args, data=None):
    return subprocess.run(['kubectl', *args], input=data, text=True, check=True, capture_output=True).stdout


def image():
    files = sorted((HERE / 'nfs-server').iterdir())
    tag = hashlib.sha256(b''.join(f.read_bytes() for f in files)).hexdigest()[:12]
    return f'hoover/nfs-server:{tag}'


def server(node, zones, name):
    extras = [(z, e) for z in zones for e in hoover_data.extra(z) if e['node'] == node]
    # NFS version 4 needs one root export with fsid=0. A client path is relative to it. The extra directories are mounts
    # below the root, each with its own read-only export.
    lines = [f'/exports *(rw,{EXPORT},fsid=0)']
    lines += [f"/exports/extra/{z}/{e['name']} *(ro,{EXPORT},fsid={i})" for i, (z, e) in enumerate(extras, start=1)]
    table = '\n'.join(lines) + '\n'
    volumes = [{'name': 'root', 'hostPath': {'path': hoover_data.root(node), 'type': 'DirectoryOrCreate'}},
               {'name': 'modules', 'hostPath': {'path': '/lib/modules', 'type': 'Directory'}},
               {'name': 'config', 'configMap': {'name': f'nfs-{node}'}}]
    mounts = [{'name': 'root', 'mountPath': '/exports'}, {'name': 'modules', 'mountPath': '/lib/modules', 'readOnly': True},
              {'name': 'config', 'mountPath': '/config', 'readOnly': True}]
    for i, (z, e) in enumerate(extras):
        volumes.append({'name': f'extra-{i}', 'hostPath': {'path': e['path'], 'type': 'Directory'}})
        mounts.append({'name': f'extra-{i}', 'mountPath': f"/exports/extra/{z}/{e['name']}", 'readOnly': True})
    container = {'name': 'nfs', 'image': f'registry.hoover.internal/{name}', 'ports': [{'name': 'nfs', 'containerPort': 2049}],
                 'securityContext': {'privileged': True}, 'volumeMounts': mounts,
                 'readinessProbe': {'tcpSocket': {'port': 2049}, 'periodSeconds': 5},
                 'resources': {'requests': {'cpu': '50m', 'memory': '32Mi'}, 'limits': {'memory': '256Mi'}}}
    labels = {**LABELS, 'hoover.dev/node': node}
    digest = hashlib.sha256(table.encode()).hexdigest()[:12]
    return [
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': f'nfs-{node}', 'namespace': NS}, 'data': {'exports': table}},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': f'nfs-{node}', 'namespace': NS, 'labels': labels},
         'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': labels},
                  'template': {'metadata': {'labels': labels, 'annotations': {'hoover.dev/exports': digest}},
                               'spec': {'serviceAccountName': 'nfs-server', 'enableServiceLinks': False,
                                        'nodeSelector': {'kubernetes.io/hostname': node},
                                        'terminationGracePeriodSeconds': 30, 'containers': [container], 'volumes': volumes}}}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': f'nfs-{node}', 'namespace': NS},
         'spec': {'selector': labels, 'ports': [{'name': 'nfs', 'port': 2049, 'targetPort': 2049}]}},
    ]


def node_sources():
    """The addresses from which a node reaches a pod: its node address, and the first two addresses of its pod range,
    which flannel and the pod bridge use."""
    blocks = []
    for n in json.loads(kubectl('get', 'nodes', '-o', 'json'))['items']:
        blocks += [a['address'] for a in n['status']['addresses'] if a['type'] == 'InternalIP']
        pods = ipaddress.ip_network(n['spec']['podCIDR'])
        blocks += [str(pods[0]), str(pods[1])]
    return [{'ipBlock': {'cidr': f'{b}/32'}} for b in sorted(set(blocks))]


def objects(name):
    zones = list(zonestate.load()['zones'])
    items = [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS}},
             {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': 'nfs-server', 'namespace': NS}},
             {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRole', 'metadata': {'name': 'hoover-nfs-server'},
              'rules': [{'apiGroups': [''], 'resources': ['namespaces'], 'verbs': ['list']}]},
             {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRoleBinding', 'metadata': {'name': 'hoover-nfs-server'},
              'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': 'hoover-nfs-server'},
              'subjects': [{'kind': 'ServiceAccount', 'name': 'nfs-server', 'namespace': NS}]},
             {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'nfs-from-nodes', 'namespace': NS},
              'spec': {'podSelector': {'matchLabels': LABELS}, 'policyTypes': ['Ingress'],
                       'ingress': [{'from': node_sources(), 'ports': [{'port': 2049, 'protocol': 'TCP'}]}]}}]
    for node in hoover_data.nodes(zones):
        items += server(node, zones, name)
    return {'apiVersion': 'v1', 'kind': 'List', 'items': items}


def main():
    name = image()
    if sys.argv[1:] == ['show']:
        print(json.dumps(objects(name), indent=1))
        return
    subprocess.run(['bash', str(HERE.parents[1] / 'images/build-image.sh'), str(HERE / 'nfs-server'), name], check=True)
    print(kubectl('apply', '-f', '-', data=json.dumps(objects(name))), end='')
    kubectl('-n', NS, 'rollout', 'status', 'deployment', '-l', 'app.kubernetes.io/name=nfs-server', '--timeout=300s')
    print(kubectl('-n', NS, 'get', 'pods', '-o', 'wide'), end='')


if __name__ == '__main__':
    main()
