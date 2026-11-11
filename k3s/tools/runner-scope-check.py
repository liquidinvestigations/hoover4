#!/usr/bin/env python3
"""Check the rights of the zone runner with its own kubeconfig. Usage: runner-scope-check.py <zone>

Each case runs one kubectl command as the ServiceAccount zone-runner (k3s/private/operator-runner/kubeconfig). A
write runs with --dry-run=server, so the API server checks the rights and the admission policies, and stores nothing.
The pod cases check the pod limits of the zone pod policy. The cases for calls run with the admin kubeconfig, because
the runner creates no pod there itself, and the ReplicaSet controller would create the pods of its Deployments.
The check prints one JSON line for each case and exits with 1 when a case has another result than expected.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

KUBECONFIG = settings.PRIVATE / 'operator-runner/kubeconfig'


def namespace(name):
    return json.dumps({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': name}})


def binding(namespace_name, role):
    return json.dumps({'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
                       'metadata': {'name': 'runner-scope-check', 'namespace': namespace_name},
                       'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': role},
                       'subjects': [{'kind': 'ServiceAccount', 'name': 'zone-runner', 'namespace': 'operator-portal'}]})


def pod(namespace_name, name='runner-scope-check', runtime=None, labels=None, spec=None, security=None):
    container = {'name': 'main', 'image': 'docker.io/library/alpine:3.22', 'command': ['sleep', '1']}
    if security:
        container['securityContext'] = security
    body = {'containers': [container], **(spec or {})}
    if runtime:
        body['runtimeClassName'] = runtime
    return json.dumps({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': namespace_name, 'labels': labels or {}},
                       'spec': body})


HOST_PATH = {'volumes': [{'name': 'host', 'hostPath': {'path': '/'}}]}
RUNC = {'hoover.dev/runtime': 'runc'}


def cases(zone):
    dry = ['--dry-run=server']
    return [
        ('read a Secret of the zone', True, ['-n', zone, 'get', 'secret', 'ums-nubus-credentials', '-o', 'name']),
        ('change a Deployment of the zone', True, ['-n', zone, 'scale', 'deployment', 'gate', '--replicas=1', *dry]),
        ('create a zone namespace', True, ['create', '-f', '-', *dry], namespace('zone-scopecheck')),
        ('bind zone-admin in a zone namespace', True, ['create', '-f', '-', *dry], binding(zone, 'zone-admin')),
        ('read the nodes', True, ['get', 'nodes', '-o', 'name']),
        ('change a call service', True, ['-n', 'calls', 'annotate', 'deployment', 'jvb', 'hoover.dev/scope-check=1', *dry]),
        ('read a Secret of kube-system', False, ['-n', 'kube-system', 'get', 'secrets', '-o', 'name']),
        ('list Secrets of all namespaces', False, ['get', 'secrets', '-A', '-o', 'name']),
        ('change a Deployment of monitoring', False, ['-n', 'monitoring', 'scale', 'deployment', 'monitor-grafana', '--replicas=1', *dry]),
        ('create another namespace', False, ['create', '-f', '-', *dry], namespace('scopecheck')),
        ('delete the namespace monitoring', False, ['delete', 'namespace', 'monitoring', *dry]),
        ('bind zone-admin in kube-system', False, ['create', '-f', '-', *dry], binding('kube-system', 'zone-admin')),
        ('bind cluster-admin in a zone namespace', False, ['create', '-f', '-', *dry], binding(zone, 'cluster-admin')),
        ('create a ClusterRoleBinding', False, ['create', 'clusterrolebinding', 'runner-scope-check', '--clusterrole=cluster-admin',
                                                '--serviceaccount=operator-portal:zone-runner', *dry]),
        ('delete a node', False, ['delete', 'node', settings.HOST['ingress_node'], *dry]),
        ('read the ingress Deployments', False, ['-n', 'ingress', 'get', 'deployments', '-o', 'name']),
        ('create a gVisor pod in the zone', True, ['create', '-f', '-', *dry], pod(zone)),
        ('create a Kata pod with SYS_ADMIN in the zone', True, ['create', '-f', '-', *dry],
         pod(zone, runtime='kata', security={'capabilities': {'add': ['SYS_ADMIN', 'SYS_RESOURCE']}})),
        ('create a runc pod of a recorded exception', True, ['create', '-f', '-', *dry], pod(zone, 'ums-ldap-notifier-9', labels=RUNC)),
        ('create a pod with a host path in the zone', False, ['create', '-f', '-', *dry], pod(zone, runtime='kata', spec=HOST_PATH)),
        ('create a privileged pod in the zone', False, ['create', '-f', '-', *dry], pod(zone, runtime='kata', security={'privileged': True})),
        ('create a host network pod in the zone', False, ['create', '-f', '-', *dry], pod(zone, spec={'hostNetwork': True})),
        ('create a host PID pod in the zone', False, ['create', '-f', '-', *dry], pod(zone, spec={'hostPID': True})),
        ('create a runc pod outside the exceptions', False, ['create', '-f', '-', *dry], pod(zone, labels=RUNC)),
        ('create a runc exception pod with a capability', False, ['create', '-f', '-', *dry],
         pod(zone, 'ums-ldap-notifier-9', labels=RUNC, security={'capabilities': {'add': ['SYS_ADMIN']}})),
        ('change the zone pod policy', False, ['annotate', 'mutatingadmissionpolicy', 'hoover-zone-pods', 'hoover.dev/scope-check=1', *dry]),
        ('change the zone pod policy binding', False, ['annotate', 'mutatingadmissionpolicybinding', 'hoover-zone-pods', 'hoover.dev/scope-check=1', *dry]),
        ('admin: a pod with a host path in calls', False, ['create', '-f', '-', *dry], pod('calls', spec=HOST_PATH), 'admin'),
        ('admin: a host network pod in calls that is not coturn', False, ['create', '-f', '-', *dry], pod('calls', spec={'hostNetwork': True}), 'admin'),
        ('admin: a coturn pod with the host network in calls', True, ['create', '-f', '-', *dry],
         pod('calls', labels={'app.kubernetes.io/name': 'coturn'}, spec={'hostNetwork': True},
             security={'capabilities': {'add': ['NET_BIND_SERVICE'], 'drop': ['ALL']}}), 'admin'),
    ]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    ok = True
    for name, expected, args, *data in cases(sys.argv[1]):
        config = settings.KUBECONFIG if data[1:] == ['admin'] else KUBECONFIG
        result = subprocess.run(['kubectl', '--kubeconfig', str(config), *args], input=data[0] if data else None,
                                capture_output=True, text=True)
        allowed = result.returncode == 0
        ok &= allowed == expected
        reason = '' if allowed else result.stderr.strip().splitlines()[-1][:200]
        print(json.dumps({'case': name, 'expected': 'allowed' if expected else 'refused',
                          'result': 'allowed' if allowed else 'refused', 'reason': reason}), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
