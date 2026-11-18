#!/usr/bin/env python3
"""Check the rights of the zone runner with its own kubeconfig. Usage: runner-scope-check.py <zone> <other zone>

Each case runs one kubectl command as the ServiceAccount zone-runner (<state folder>/operator-runner/kubeconfig). A
write runs with --dry-run=server, so the API server checks the rights and the admission policies, and stores nothing.
The pod cases check the pod limits of the zone pod policy and the policy k3s-snapshot-reader of the reader pod of
the platform backup. The cases for calls and hoover-pools run with the admin kubeconfig, because the runner creates no
pod there itself, and the ReplicaSet controller would create the pods of its Deployments.
The store cases log in to the secret store (../secretstore.py) with the token of zone-runner, as the roles runner and
backup, and with a zone step token that the runner creates for <zone>. <other> is another zone of the site. A read
prints no value, only allowed or refused.
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


def reader(change=None):
    """The reader pod of the platform backup (../platform/backups/backups.py snapshot_reader()), changed by change()."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('backups', Path(__file__).resolve().parents[1] / 'platform/backups/backups.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    body = module.snapshot_reader(settings.SITE.control_plane)
    if change:
        change(body['spec'])
    return json.dumps(body)


def set_path(spec, path):
    spec['volumes'][0]['hostPath']['path'] = path


def set_writable(spec):
    spec['containers'][0]['volumeMounts'][0]['readOnly'] = False


def set_image(spec):
    spec['containers'][0]['image'] = 'docker.io/library/alpine:3.22'


def set_capability(spec):
    spec['containers'][0]['securityContext']['capabilities']['add'] = ['SYS_ADMIN']


def set_token(spec):
    spec['automountServiceAccountToken'] = True


def ingress(name):
    return json.dumps({'apiVersion': 'networking.k8s.io/v1', 'kind': 'Ingress', 'metadata': {'name': name, 'namespace': 'hoover-stores'},
                       'spec': {'ingressClassName': 'haproxy', 'rules': [{'host': f'{name}.example', 'http': {'paths': [
                           {'path': '/nextcloud', 'pathType': 'Prefix', 'backend': {'service': {'name': 'garage', 'port': {'number': 3900}}}}]}}]}})


def cases(zone):
    dry = ['--dry-run=server']
    return [
        ('read a Secret of the zone', True, ['-n', zone, 'get', 'secret', 'ums-nubus-credentials', '-o', 'name']),
        ('change a Deployment of the zone', True, ['-n', zone, 'scale', 'deployment', 'gate', '--replicas=1', *dry]),
        ('create a zone namespace', True, ['create', '-f', '-', *dry], namespace('zone-scopecheck')),
        ('bind zone-admin in a zone namespace', True, ['create', '-f', '-', *dry], binding(zone, 'zone-admin')),
        ('read the nodes', True, ['get', 'nodes', '-o', 'name']),
        ('change a call service', True, ['-n', 'calls', 'annotate', 'deployment', 'jvb', 'hoover.dev/scope-check=1', *dry]),
        ('read the seal key of the secret store', False, ['-n', 'openbao', 'get', 'secret', 'openbao-seal', '-o', 'name']),
        ('read the Secrets of openbao', False, ['-n', 'openbao', 'get', 'secrets', '-o', 'name']),
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
        ('create the k3s snapshot reader pod', True, ['create', '-f', '-', *dry], reader()),
        ('create the reader with another host path', False, ['create', '-f', '-', *dry], reader(lambda s: set_path(s, '/'))),
        ('create the reader with a writable mount', False, ['create', '-f', '-', *dry], reader(set_writable)),
        ('create the reader with another image', False, ['create', '-f', '-', *dry], reader(set_image)),
        ('create the reader with a capability', False, ['create', '-f', '-', *dry], reader(set_capability)),
        ('create the reader with an API token', False, ['create', '-f', '-', *dry], reader(set_token)),
        ('read the Secrets of platform-backup', False, ['-n', 'platform-backup', 'get', 'secrets', '-o', 'name']),
        ('change a processing pool', True, ['-n', 'hoover-pools', 'annotate', 'deployment', 'hoover4-tika', 'hoover.dev/scope-check=1', *dry]),
        ('create the Ingress of an object storage host', True, ['create', '-f', '-', *dry], ingress('opendesk-zone-scopecheck')),
        ('change a volume', False, ['auth', 'can-i', 'patch', 'persistentvolumes']),
        ('change the Garage StatefulSet', False, ['-n', 'hoover-stores', 'annotate', 'statefulset', 'garage', 'hoover.dev/scope-check=1', *dry]),
        ('admin: a pod with a host path in calls', False, ['create', '-f', '-', *dry], pod('calls', spec=HOST_PATH), 'admin'),
        ('admin: a pod with a host path in hoover-pools', False, ['create', '-f', '-', *dry], pod('hoover-pools', runtime='gvisor', spec=HOST_PATH), 'admin'),
        ('admin: a privileged pod in hoover-pools', False, ['create', '-f', '-', *dry], pod('hoover-pools', runtime='gvisor', security={'privileged': True}), 'admin'),
        ('admin: a host network pod in calls that is not coturn', False, ['create', '-f', '-', *dry], pod('calls', spec={'hostNetwork': True}), 'admin'),
        ('admin: a coturn pod with the host network in calls', True, ['create', '-f', '-', *dry],
         pod('calls', labels={'app.kubernetes.io/name': 'coturn'}, spec={'hostNetwork': True},
             security={'capabilities': {'add': ['NET_BIND_SERVICE'], 'drop': ['ALL']}}), 'admin'),
    ]


def runner_jwt():
    import re
    return re.search(r'token: "?([^",}\s]+)', KUBECONFIG.read_text()).group(1)


def store_cases(zone, other):
    """[(case, expected, function)] of the secret store. A function returns normally when the store allows it."""
    import secretstore
    secretstore.client()
    jwt = runner_jwt()

    def session(role=None, token=None):
        client = secretstore.OpenBao(None, ca=secretstore.ca_file(), forward=secretstore.KubeProxy(str(settings.KUBECONFIG)))
        client.token = token or secretstore.login(client, role, jwt)
        return client
    runner, backup = session('runner'), session('backup')
    step = session(token=runner.raw('POST', 'auth/token/create/zone-step', {'entity_alias': zone, 'ttl': '10m'})['auth']['client_token'])

    def read(client, path):
        return lambda: client.read(path)

    def write(client, path):
        # The write names a version that no path has, so an allowed write changes nothing and the store answers with a
        # check-and-set error.
        def run():
            try:
                client.write(path, {'scope-check': '1'}, 999999)
            except secretstore.CasConflict:
                pass
        return run
    return [
        ('runner: log in as deployer', False, lambda: session('deployer')),
        ('runner: read the secrets of the zone', True, read(runner, f'zones/{zone}/secrets')),
        ('runner: read the shared store admin', True, read(runner, 'site/stores')),
        ('runner: write a policy', False, lambda: runner.raw('PUT', 'sys/policies/acl/scope-check', {'policy': ''})),
        ('runner: read the store snapshot', False, lambda: runner.transfer('GET', 'sys/storage/raft/snapshot')),
        ('backup: read the secrets of the zone', True, read(backup, f'zones/{zone}/secrets')),
        ('backup: write the shared store admin', False, write(backup, 'site/stores')),
        ('backup: create a zone step token', False, lambda: backup.raw('POST', 'auth/token/create/zone-step', {'entity_alias': zone})),
        ('zone step: read the secrets of its zone', True, read(step, f'zones/{zone}/secrets')),
        ('zone step: write a path of its zone', True, write(step, f'zones/{zone}/secrets')),
        ('zone step: read the secrets of the other zone', False, read(step, f'zones/{other}/secrets')),
        ('zone step: write a path of the other zone', False, write(step, f'zones/{other}/secrets')),
        ('zone step: read the Hoover Secrets of the other zone', False, read(step, f'zones/{other}/hoover/hoover-runtime')),
        ('zone step: list the zones', False, lambda: step.raw('GET', 'hoover/metadata/zones/?list=true')),
        ('zone step: read the call secrets', True, read(step, 'site/calls')),
        ('zone step: write the call secrets', False, write(step, 'site/calls')),
        ('zone step: read the shared store admin', False, read(step, 'site/stores')),
        ('zone step: create a token of the other zone', False,
         lambda: step.raw('POST', 'auth/token/create/zone-step', {'entity_alias': other})),
        ('runner: create a zone step token for a name outside zone-*', False,
         lambda: runner.raw('POST', 'auth/token/create/zone-step', {'entity_alias': 'site'})),
    ]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    ok = True
    import secretstore
    for name, expected, function in store_cases(sys.argv[1], sys.argv[2]):
        try:
            function()
            allowed, reason = True, ''
        except secretstore.StoreError as error:
            allowed, reason = False, str(error).splitlines()[0][:200]
        ok &= allowed == expected
        print(json.dumps({'case': name, 'expected': 'allowed' if expected else 'refused',
                          'result': 'allowed' if allowed else 'refused', 'reason': reason}), flush=True)
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
