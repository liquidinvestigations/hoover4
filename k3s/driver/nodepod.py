"""Run a root command on a node of the cluster through a short pod. Standard library only.

The pod runs in kube-system on the named node, with the root folder of the host mounted at /host, and runs the command
with chroot /host, so the command uses the tools of the host (k3s crictl, k3s ctr, lvs, k3s etcd-snapshot). It needs
the admin kubeconfig and no SSH access or sudo rule on the node. deploy-k3s reset (reset.py) uses it.
A node that does not start the pod within START_TIMEOUT seconds, for example a stopped node, raises Unreachable. The
pod is deleted after each command.
"""
import json
import subprocess
import time
import uuid

NAMESPACE = 'kube-system'
LABEL = 'hoover.dev/node-command'
# The busybox image of the pre-pull step (../images/prepull.py), which every eligible node has.
IMAGE = 'docker.io/library/busybox:1.37.0-musl@sha256:f6a95d611e0a8780fabdb2aec43e31275b2720dfefa3e41b16835bfc42454478'
START_TIMEOUT = 180


class Unreachable(RuntimeError):
    """The node did not run the pod."""


class Failed(RuntimeError):
    """The command ended with an exit code other than 0."""


def kubectl(kubeconfig, *args, input=None, check=True):
    r = subprocess.run(['kubectl', '--kubeconfig', str(kubeconfig), *args], input=input, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f'kubectl {" ".join(args[:3])} failed: {r.stderr.strip()[-300:]}')
    return r


def pod(name, node, script):
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': name, 'namespace': NAMESPACE, 'labels': {LABEL: 'true'}},
            'spec': {'nodeName': node, 'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                     'enableServiceLinks': False, 'tolerations': [{'operator': 'Exists'}],
                     'priorityClassName': 'system-node-critical',
                     'containers': [{'name': 'run', 'image': IMAGE, 'imagePullPolicy': 'IfNotPresent',
                                     'command': ['chroot', '/host', '/bin/sh', '-c', script],
                                     'securityContext': {'privileged': True},
                                     'volumeMounts': [{'name': 'host', 'mountPath': '/host',
                                                       'mountPropagation': 'HostToContainer'}]}],
                     'volumes': [{'name': 'host', 'hostPath': {'path': '/', 'type': 'Directory'}}]}}


def run(kubeconfig, node, script, timeout=900, check=True):
    """Run script as root on node. Return its output (stdout and stderr of the pod). A failed script raises Failed
    with check, else the output ends with the line 'exit <code>'."""
    name = f'node-command-{node}-{uuid.uuid4().hex[:8]}'[:63]
    kubectl(kubeconfig, 'apply', '-f', '-', input=json.dumps(pod(name, node, script)))
    try:
        started = time.monotonic()
        while True:
            r = kubectl(kubeconfig, '-n', NAMESPACE, 'get', 'pod', name, '-o', 'json', check=False)
            status = json.loads(r.stdout).get('status', {}) if r.returncode == 0 else {}
            phase = status.get('phase', '')
            if phase in ('Succeeded', 'Failed'):
                break
            waited = time.monotonic() - started
            if phase in ('', 'Pending') and waited > START_TIMEOUT:
                raise Unreachable(f'the node {node} did not start the command pod in {START_TIMEOUT} s')
            if waited > timeout:
                raise Unreachable(f'the command on {node} did not end in {timeout} s')
            time.sleep(2)
        out = kubectl(kubeconfig, '-n', NAMESPACE, 'logs', name, check=False).stdout
        code = next((c.get('state', {}).get('terminated', {}).get('exitCode') for c in status.get('containerStatuses', [])), None)
        if code and check:
            raise Failed(f'the command on {node} ended with exit code {code}: {out.strip()[-400:]}')
        return out if not code else f'{out}\nexit {code}'
    finally:
        kubectl(kubeconfig, '-n', NAMESPACE, 'delete', 'pod', name, '--ignore-not-found', '--wait=false', check=False)
