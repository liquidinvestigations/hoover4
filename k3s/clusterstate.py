"""The cluster copy of the zone state and the operator state of a site. Standard library only.

The cluster holds the authoritative copy. Each file of the synchronized set is one object in the namespace
operator-portal: a ConfigMap with the label hoover.dev/state=file, or a Secret with the label
hoover.dev/state=secret. The annotation hoover.dev/state-path names the path of the file in the state folder. The key
`content` holds the file.

  ConfigMaps  zone-state.json, operator/ (the operator settings, the apply operations and their logs, the backup and
              relay state), operations/ (the logs of the zone operations of the runner), facts/ (the host facts) and
              frontend/local-ca.crt (the root certificate of the internal CA of the frontend)
  Secrets     zones/ (the zone secrets, the openDesk values and the master passwords)

operator/deploy/ (the records of deploy-k3s), operator/import/ (the records of the Compose import), operator/migration/
(the records of the earlier migration tool), lock files and files whose name starts with a dot stay local. A log file larger than LOG_LIMIT keeps its last LOG_LIMIT bytes in the cluster.

A folder that uses the cluster copy, for example the state folder of the workstation or the state folder of the
operator pod, keeps a manifest of the last synchronization: the digest of each local file and the resourceVersion of
its object. pull() writes the files that changed in the cluster and that did not change in the folder. push() writes
the files that changed in the folder. A replace names the resourceVersion of the manifest, so the API server refuses a
file that another writer changed after the last pull. push() then raises Conflict, and the next pull and push resolve
it. A file that is new in the folder and in the cluster takes the cluster copy at the pull.
The site operation lock (oplock.py) makes deploy-k3s, the runner and the backups the only writer at a time. The
settings saves of the portal take no lock, and they write other files than the operations of the lock holder.

Usage: clusterstate.py pull|push <state folder> [configmap|secret ...]    KUBECONFIG names the kubeconfig.
"""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

NAMESPACE = 'operator-portal'
LABEL = 'hoover.dev/state'
PATH_ANNOTATION = 'hoover.dev/state-path'
# The environment variable that makes checkpoint() push. The operator pod and the steps of deploy-k3s set it.
ENV = 'HOOVER4_CLUSTER_STATE'
LOG_LIMIT = 256 * 1024
# kind: (label value, files, folders, manifest, lock). The paths are relative to the state folder.
KINDS = {
    'configmap': ('file', ('zone-state.json', 'frontend/local-ca.crt'), ('operator', 'operations', 'facts'),
                  '.cluster-state.json', '.cluster-state.lock'),
    'secret': ('secret', (), ('zones',), 'zones/.cluster-state.json', 'zones/.cluster-state.lock'),
}
# operator/migration/ holds the records of the earlier migration tool in older state folders.
EXCLUDED_FOLDERS = ('operator/deploy/', 'operator/import/', 'operator/migration/')


class Conflict(RuntimeError):
    """Another writer changed a file of the cluster copy after the last pull."""


class Unavailable(RuntimeError):
    """The cluster does not answer."""


def object_name(path):
    return 'state-' + hashlib.sha256(path.encode()).hexdigest()[:24]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def local_files(folder, kind):
    """{relative path: bytes} of the files of a kind in a state folder."""
    folder = Path(folder)
    _, files, folders, _, _ = KINDS[kind]
    found = {}
    candidates = [folder / f for f in files]
    for name in folders:
        root = folder / name
        if root.is_dir():
            candidates += sorted(p for p in root.rglob('*') if p.is_file() or p.is_symlink())
    for path in candidates:
        if not path.is_file():
            continue
        relative = path.relative_to(folder).as_posix()
        if (any(part.startswith('.') for part in relative.split('/')) or relative.endswith('.lock')
                or relative == 'operator/site-operation.json' or relative.startswith(EXCLUDED_FOLDERS)):
            continue
        found[relative] = path.read_bytes()
    return found


def stored(path, data):
    """The bytes that the cluster copy keeps of a file."""
    if path.endswith('.log') and len(data) > LOG_LIMIT:
        tail = data[-LOG_LIMIT:]
        return tail[tail.find(b'\n') + 1:] if b'\n' in tail else tail
    return data


class Kubectl:
    """The objects of the cluster copy, through kubectl with a kubeconfig."""

    def __init__(self, kubeconfig=None, namespace=NAMESPACE):
        self.kubeconfig = str(kubeconfig) if kubeconfig else os.environ.get('KUBECONFIG', '')
        self.namespace = namespace

    def run(self, *args, data=None, check=True):
        argv = ['kubectl', *(['--kubeconfig', self.kubeconfig] if self.kubeconfig else []), '-n', self.namespace, *args]
        result = subprocess.run(argv, input=data, capture_output=True, text=True, timeout=120)
        if check and result.returncode:
            message = (result.stderr or result.stdout).strip()[-500:]
            if 'the object has been modified' in message or 'AlreadyExists' in message or 'already exists' in message:
                raise Conflict(message)
            raise Unavailable(f'kubectl {" ".join(args[:3])} failed: {message}')
        return result.stdout

    def list(self, kind):
        """{path: {name, version, data}} of the objects of a kind."""
        label = KINDS[kind][0]
        items = json.loads(self.run('get', f'{kind}s', '-l', f'{LABEL}={label}', '-o', 'json'))['items']
        out = {}
        for item in items:
            path = (item['metadata'].get('annotations') or {}).get(PATH_ANNOTATION)
            if not path:
                continue
            if kind == 'secret':
                data = base64.b64decode((item.get('data') or {}).get('content', ''))
            elif 'content' in (item.get('binaryData') or {}):
                data = base64.b64decode(item['binaryData']['content'])
            else:
                data = (item.get('data') or {}).get('content', '').encode()
            out[path] = {'name': item['metadata']['name'], 'version': item['metadata']['resourceVersion'], 'data': data}
        return out

    def body(self, kind, path, data, version=None):
        metadata = {'name': object_name(path), 'namespace': self.namespace, 'labels': {LABEL: KINDS[kind][0]},
                    'annotations': {PATH_ANNOTATION: path}}
        if version:
            metadata['resourceVersion'] = version
        body = {'apiVersion': 'v1', 'kind': 'Secret' if kind == 'secret' else 'ConfigMap', 'metadata': metadata}
        if kind == 'secret':
            body['type'] = 'Opaque'
            body['data'] = {'content': base64.b64encode(data).decode()}
        else:
            try:
                body['data'] = {'content': data.decode()}
            except UnicodeDecodeError:
                body['binaryData'] = {'content': base64.b64encode(data).decode()}
        return body

    def put(self, kind, path, data, version=None):
        """Create the object, or replace the object of version. Return the new resourceVersion."""
        body = json.dumps(self.body(kind, path, data, version))
        out = self.run('replace' if version else 'create', '-f', '-', '-o', 'jsonpath={.metadata.resourceVersion}', data=body)
        return out.strip()

    def delete(self, kind, path):
        self.run('delete', kind, object_name(path), '--ignore-not-found', '--wait=false')

    def ensure_namespace(self):
        text = subprocess.run(['kubectl', *(['--kubeconfig', self.kubeconfig] if self.kubeconfig else []), 'create',
                               'namespace', self.namespace, '--dry-run=client', '-o', 'json'],
                              capture_output=True, text=True, check=True).stdout
        subprocess.run(['kubectl', *(['--kubeconfig', self.kubeconfig] if self.kubeconfig else []), 'apply', '-f', '-'],
                       input=text, capture_output=True, text=True, check=True)


@contextlib.contextmanager
def locked(folder, kind):
    path = Path(folder) / KINDS[kind][4]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_manifest(folder, kind):
    try:
        return json.loads((Path(folder) / KINDS[kind][3]).read_text())
    except (OSError, ValueError):
        return {}


def write_manifest(folder, kind, manifest):
    path = Path(folder) / KINDS[kind][3]
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    os.replace(tmp, path)


def write_file(folder, path, data, kind):
    target = Path(folder) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f'.{target.name}.{os.getpid()}.tmp')
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if kind == 'secret' else 0o644), 'wb') as f:
        f.write(data)
    os.replace(tmp, target)


def pull(folder, kinds=('configmap', 'secret'), store=None):
    """Write the cluster changes into the folder. Return {path: action} of the changed files."""
    store = store or Kubectl()
    changes = {}
    for kind in kinds:
        with locked(folder, kind):
            remote = store.list(kind)
            local = {p: digest(d) for p, d in local_files(folder, kind).items()}
            manifest = read_manifest(folder, kind)
            for path in sorted(set(remote) | set(manifest)):
                seen = manifest.get(path)
                item = remote.get(path)
                changed_here = path in local and (seen is None or local[path] != seen['digest'])
                if item is None:
                    # The cluster copy lost the file. An unchanged local copy goes too.
                    if path in local and not changed_here:
                        (Path(folder) / path).unlink()
                        changes[path] = 'deleted'
                    manifest.pop(path, None)
                    continue
                if seen and seen['version'] == item['version']:
                    # The cluster copy did not change. push() sends a local change or a local delete.
                    continue
                if changed_here and seen is not None:
                    raise Conflict(f'{path} changed in the cluster and in {folder} since the last sync. '
                                   f'The cluster has version {item["version"]}.')
                if local.get(path) != digest(item['data']):
                    write_file(folder, path, item['data'], kind)
                    changes[path] = 'written'
                manifest[path] = {'digest': digest(item['data']), 'version': item['version']}
            write_manifest(folder, kind, manifest)
    return changes


def push(folder, kinds=('configmap', 'secret'), store=None):
    """Write the changes of the folder into the cluster copy. Return {path: action} of the changed objects."""
    store = store or Kubectl()
    changes = {}
    for kind in kinds:
        with locked(folder, kind):
            local = local_files(folder, kind)
            manifest = read_manifest(folder, kind)
            for path in sorted(set(local) | set(manifest)):
                seen = manifest.get(path)
                if path not in local:
                    store.delete(kind, path)
                    manifest.pop(path)
                    changes[path] = 'deleted'
                    continue
                current = digest(local[path])
                if seen and seen['digest'] == current:
                    continue
                version = store.put(kind, path, stored(path, local[path]), seen['version'] if seen else None)
                manifest[path] = {'digest': current, 'version': version}
                changes[path] = 'written'
                write_manifest(folder, kind, manifest)
            write_manifest(folder, kind, manifest)
    return changes


def checkpoint(folder, kinds=('configmap', 'secret')):
    """Push the folder when this process runs with ENV set, for example after a zone step wrote its secrets."""
    if os.environ.get(ENV) != '1':
        return {}
    return push(folder, kinds)


def main(argv):
    if len(argv) < 2 or argv[0] not in ('pull', 'push'):
        raise SystemExit(__doc__)
    kinds = tuple(argv[2:]) or ('configmap', 'secret')
    result = (pull if argv[0] == 'pull' else push)(argv[1], kinds)
    print(json.dumps(result, indent=1, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
