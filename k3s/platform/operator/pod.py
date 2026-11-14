#!/usr/bin/env python3
"""Start a container of the operator pod (operator-login.yaml). Usage: pod.py portal|runner

The pod runs the operator image of the registry (../../images/operator-pod/), which holds the files of the checkout and
the operator tools. No container mounts a host folder of a checkout or a state folder.
HOOVER4_SITE names the site file in its JSON form (the ConfigMap portal-site). Its state folder is a folder of the pod,
which both containers share. The runner mounts its own folder at zones/ of the state folder, so the portal container
never sees a zone secret.
The script:
  1. writes a kubeconfig into /tmp for the token of the container: the token of the ServiceAccount portal for the
     portal, and the token of the ServiceAccount zone-runner (the Secret zone-runner-token) for the runner,
  2. for the runner, links the operator tools of the image into bin/ and copies the openDesk release into downloads/
     of the state folder, where the zone installer reads them,
  3. reads the cluster copy of the state into the state folder (../../clusterstate.py): the ConfigMaps for both
     containers, and the zone Secrets for the runner,
  4. starts portal-server.py or runner.py with HOOVER4_CLUSTER_STATE=1, so they write their changes into the cluster.
"""
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parents[1]
TOOLS = Path(os.environ.get('OPERATOR_TOOLS', '/opt/hoover4-tools'))
TOKENS = {'portal': Path('/var/run/secrets/kubernetes.io/serviceaccount'), 'runner': Path('/var/run/zone-runner')}
SERVER = 'https://kubernetes.default.svc'


def kubeconfig(role):
    tokens = TOKENS[role]
    path = Path('/tmp') / f'kubeconfig-{role}'
    path.write_text(f'''apiVersion: v1
kind: Config
clusters: [{{name: cluster, cluster: {{server: "{SERVER}", certificate-authority: "{tokens / 'ca.crt'}"}}}}]
users: [{{name: {role}, user: {{tokenFile: "{tokens / 'token'}"}}}}]
contexts: [{{name: {role}, context: {{cluster: cluster, user: {role}, namespace: operator-portal}}}}]
current-context: {role}
''')
    path.chmod(0o600)
    return path


def tools(state):
    """Link the tools of the image into bin/ and copy the openDesk release into downloads/ of the state folder."""
    import json
    artifacts = json.loads((K3S / 'driver/artifacts.json').read_text())
    for item in artifacts['tools']:
        for entry in item['install']:
            entry = entry.rstrip('/')
            source, target = TOOLS / entry, state / entry
            if not source.exists():
                raise SystemExit(f'the operator image has no {source}')
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry.startswith('downloads/'):
                # helmfile runs in the release folder, so the folder is writable.
                if not target.exists():
                    shutil.copytree(source, target, symlinks=True)
            elif not target.is_symlink():
                target.symlink_to(source)


def main(argv):
    if len(argv) != 1 or argv[0] not in TOKENS:
        raise SystemExit(__doc__)
    role = argv[0]
    site = Path(os.environ['HOOVER4_SITE'])
    state = site.with_suffix('')
    state.mkdir(parents=True, exist_ok=True)
    os.environ['KUBECONFIG'] = str(kubeconfig(role))
    Path(os.environ.setdefault('HOME', f'/tmp/home-{role}')).mkdir(parents=True, exist_ok=True)
    if role == 'runner':
        tools(state)
    sys.path.insert(0, str(K3S))
    import clusterstate
    kinds = ('configmap', 'secret') if role == 'runner' else ('configmap',)
    for attempt in range(30):
        try:
            changes = clusterstate.pull(state, kinds)
            break
        except clusterstate.Unavailable as error:
            print(f'pod.py: the cluster copy of the state is unavailable: {error}', file=sys.stderr, flush=True)
            time.sleep(5)
    else:
        raise SystemExit('pod.py: the cluster copy of the state stayed unavailable.')
    print(f'pod.py: {role} read {len(changes)} files of the cluster copy into {state}', flush=True)
    os.environ[clusterstate.ENV] = '1'
    script = HERE / ('portal-server.py' if role == 'portal' else 'runner.py')
    os.execv(sys.executable, [sys.executable, str(script)])


if __name__ == '__main__':
    main(sys.argv[1:])
