"""The client of the secret store of a site. The store is OpenBao in the namespace openbao (platform/secrets/openbao.py).
The module uses the standard library only.

Every secret that the deployment tools generate is a key of a KV version 2 path below the mount MOUNT. The store
requires check-and-set on each write, so a write names the version that it read. A write over a newer version fails.
update() then reads the path again and repeats the change, so two writers of one path keep both changes.

The paths are relative to the mount.
  site/calls                 the JVB password and the LiveKit secrets of the call services (../zones/zones.py)
  site/zone-users            the password of each user of ../zones/zone-users.json, the same in every zone
  site/stores                the Secret hoover-stores of the shared stores (../hoover/stores/shared.py)
  site/temporal              the signing key of the Temporal of the site (../hoover/stores/temporal.py)
  site/gpu                   the GPU key of the installation (../hoover/gpu.py)
  site/operator-login        the operator login (../platform/operator/start-web-tools.sh)
  site/registry              the push password of the cluster registry (../platform/registry/install-registry.sh)
  zones/<zone>/secrets       the secrets of a zone that zones.py generates
  zones/<zone>/test-user     the password of test.user of the zone (../zones/zone-users.py)
  zones/<zone>/imported-users  the passwords of the users of a Compose import (../import_compose/import_compose.py)
  zones/<zone>/stores        the Secret hoover-stores of the zone namespace (../hoover/stores/creds.py)
  zones/<zone>/garage-tenants  the Garage keys of the zone (../hoover/setup.py)
  zones/<zone>/hoover/<name> the Secrets hoover-runtime, manticore-schema and oauth2-proxy of the Hoover namespace
  zones/<zone>/records/<name>  the records opendesk-applied.json, objectstore-move.json and postgresql-move.json
The Kubernetes Secrets that pods read are copies. The step that owns a secret writes the copy from the store
(keep()). A step that only reads a secret of another step reads the copy, for example a zone step that reads the
shared store admin.

Each process logs in once with the Kubernetes auth method of OpenBao. The roles are these.
  deployer  deploy-k3s and the tools of the workstation. kubectl makes a short token of the ServiceAccount
            openbao-deployer with the admin kubeconfig. The role administers the store.
  runner    the runner container of the operator pod, with the token of the ServiceAccount zone-runner. It reads and
            writes every path of the mount and creates zone step tokens.
  backup    ../platform/backups/backups.py in the runner container. It reads every path and takes and restores the
            snapshot of the store.
  zone step zone.py of one zone gets a token of the token role zone-step (zone_token()). The policy zone-step gives
            it the paths zones/<zone>/ of its own zone. It also reads site/calls and site/zone-users.
HOOVER4_SECRET_TOKEN gives a process the token of its parent, and the process then does not log in.
HOOVER4_SECRET_STORE names the address. file://<path> is the JSON file store of the tests. Without it, a process in a
pod uses the Service, and another process uses kubectl proxy to the pod openbao-0 with its kubeconfig (KubeProxy).
In the cluster the client checks the TLS certificate of OpenBao against the ConfigMap openbao-ca of operator-portal.
Through kubectl proxy the API server makes the TLS connection to the pod.

keep() is the one write rule of a generated secret, and it never replaces a stored value. A copy of an earlier
version, for example the Kubernetes Secret, can give a value that the store lacks. A copy with another value stops
the write with the names of the path and the key, because the services can use the copy.

Usage: secretstore.py status                  print the paths of the store
       secretstore.py files <path> <folder> <name>[:<generator>] ...
                                              keep files of a folder in a path (keep_files())
       secretstore.py read <path> <key>       print one value, for the scripts of the deployment
"""
import contextlib
import fcntl
import json
import os
import re
import secrets as random
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

NAMESPACE = 'openbao'
POD = 'openbao-0'
SERVICE = 'openbao'
PORT = 8200
MOUNT = 'hoover'
CA_CONFIGMAP = ('operator-portal', 'openbao-ca')
ENV_ADDRESS = 'HOOVER4_SECRET_STORE'
ENV_TOKEN = 'HOOVER4_SECRET_TOKEN'
ENV_ROLE = 'HOOVER4_SECRET_ROLE'
# The ServiceAccount of the deployer role and the token file of the runner (../platform/operator/pod.py).
DEPLOYER_ACCOUNT = 'openbao-deployer'
RUNNER_TOKEN = Path('/var/run/zone-runner/token')
ZONE = re.compile(r'zone-[a-z0-9]{1,12}')
# The generators of keep_files() and of the CLI.
GENERATORS = {
    'hex16': lambda: random.token_hex(16),
    'hex24': lambda: random.token_hex(24),
    'hex32': lambda: random.token_hex(32),
    # openssl rand -hex 24 of an earlier version wrote the line end.
    'hex24n': lambda: random.token_hex(24) + '\n',
    'urlsafe18': lambda: random.token_urlsafe(18) + '\n',
}


class StoreError(RuntimeError):
    """The secret store refused a request or does not answer."""


class Mismatch(StoreError):
    """A copy holds another value than the store. The message names the path and the key, never a value."""


class CasConflict(StoreError):
    """Another writer changed the path after the read."""


# ----------------------------------------------------------------------------------------------------------------------
# Backends
# ----------------------------------------------------------------------------------------------------------------------

class FileStore:
    """A JSON file with the same operations, for the tests. A file lock gives one writer at a time."""

    def __init__(self, path):
        self.path = Path(path)

    @contextlib.contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.path) + '.lock', 'a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            data = json.loads(self.path.read_text()) if self.path.exists() else {}
            yield data
            tmp = self.path.with_name(f'.{self.path.name}.{os.getpid()}.tmp')
            tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
            os.replace(tmp, self.path)

    def read(self, path):
        with self._locked() as data:
            item = data.get(path)
            return (dict(item['data']), item['version']) if item else ({}, 0)

    def write(self, path, values, cas):
        with self._locked() as data:
            version = (data.get(path) or {}).get('version', 0)
            if version != cas:
                raise CasConflict(f'{path} has version {version}, not {cas}')
            data[path] = {'data': dict(values), 'version': version + 1}
            return version + 1

    def list(self, prefix):
        prefix = prefix.rstrip('/') + '/'
        with self._locked() as data:
            return sorted({p[len(prefix):].split('/')[0] + ('/' if '/' in p[len(prefix):] else '')
                           for p in data if p.startswith(prefix)})

    def delete(self, path):
        with self._locked() as data:
            data.pop(path, None)

    def raw(self, method, path, body=None):
        raise StoreError(f'the file store has no {method} {path}')

    def snapshot(self):
        with self._locked() as data:
            return json.dumps(data, sort_keys=True).encode()

    def restore_snapshot(self, raw):
        with self._locked() as data:
            data.clear()
            data.update(json.loads(raw))


class KubeProxy:
    """kubectl proxy on a free local port, for the life of this process. A request goes through the API server to the
    pod of OpenBao. A kubectl port-forward does not reach a pod in gVisor, because its listener is inside the sandbox.
    The API server runs on the control-plane node with the pod, and the network policy of a node admits the traffic of
    the node itself."""

    def __init__(self, kubeconfig=None):
        self.kubeconfig = kubeconfig
        self.process = None
        self.port = None
        self.lock = threading.Lock()

    def address(self):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.start()
            return (f'http://127.0.0.1:{self.port}/api/v1/namespaces/{NAMESPACE}/pods/'
                    f'https:{POD}:{PORT}/proxy')

    def restart(self):
        with self.lock:
            self.stop()
            self.start()

    def start(self):
        argv = ['kubectl', *(['--kubeconfig', self.kubeconfig] if self.kubeconfig else []), 'proxy', '--port=0',
                '--address=127.0.0.1']
        self.process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            found = re.search(r'127\.0\.0\.1:(\d+)', line or '')
            if found:
                self.port = int(found.group(1))
                # kubectl goes on writing, and a full pipe would block it.
                threading.Thread(target=self.process.stdout.read, daemon=True).start()
                threading.Thread(target=self.process.stderr.read, daemon=True).start()
                return
            if not line and self.process.poll() is not None:
                break
        error = self.process.stderr.read() if self.process.poll() is not None else ''
        self.stop()
        raise StoreError(f'kubectl proxy failed: {error.strip()[-300:]}')

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None


class OpenBao:
    """The KV version 2 mount MOUNT of OpenBao over HTTPS."""

    def __init__(self, address, token=None, ca=None, forward=None):
        self.fixed = address
        self.forward = forward
        self.token = token
        self.context = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()

    def raw(self, method, path, body=None, token=True, expect=(200, 204)):
        """One request of the HTTP API. Return the decoded answer, or {} for an empty one."""
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(4):
            base = self.fixed or self.forward.address()
            request = urllib.request.Request(f'{base}/v1/{path}', data=data, method=method)
            request.add_header('Content-Type', 'application/json')
            if token and self.token:
                request.add_header('X-Vault-Token', self.token)
            try:
                with urllib.request.urlopen(request, timeout=60, context=self.context) as response:
                    text = response.read()
                    return json.loads(text) if text else {}
            except urllib.error.HTTPError as error:
                text = error.read().decode(errors='replace')
                if error.code in expect:
                    return json.loads(text) if text.strip() else {}
                if error.code == 404 and method == 'GET':
                    return None
                try:
                    messages = '; '.join(json.loads(text).get('errors') or [])
                except ValueError:
                    messages = text.strip()[:300]
                if 'check-and-set' in messages:
                    raise CasConflict(f'{path}: {messages}') from None
                if error.code in (500, 502, 503) and attempt < 3:
                    time.sleep(2 + 3 * attempt)
                    continue
                raise StoreError(f'OpenBao answered {error.code} to {method} {path}: {messages}') from None
            except (urllib.error.URLError, ConnectionError, socket.timeout, ssl.SSLError) as error:
                if attempt < 3:
                    if self.forward:
                        self.forward.restart()
                    time.sleep(2 + 3 * attempt)
                    continue
                raise StoreError(f'OpenBao does not answer at {base}: {error}. '
                                 'Run deploy-k3s up --steps secret-store.') from None
        raise StoreError(f'OpenBao does not answer {method} {path}')

    def snapshot(self):
        """The Raft snapshot of the store as bytes."""
        return self.transfer('GET', 'sys/storage/raft/snapshot')

    def restore_snapshot(self, data):
        """Replace the whole store with a Raft snapshot of a store with the same seal key."""
        self.transfer('POST', 'sys/storage/raft/snapshot-force', data)

    def transfer(self, method, path, data=None):
        base = self.fixed or self.forward.address()
        request = urllib.request.Request(f'{base}/v1/{path}', data=data, method=method)
        request.add_header('X-Vault-Token', self.token or '')
        if data is not None:
            request.add_header('Content-Type', 'application/octet-stream')
        try:
            with urllib.request.urlopen(request, timeout=600, context=self.context) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            raise StoreError(f'OpenBao answered {error.code} to {method} {path}: '
                             f'{error.read().decode(errors="replace").strip()[:300]}') from None
        except (urllib.error.URLError, ConnectionError, socket.timeout, ssl.SSLError) as error:
            raise StoreError(f'OpenBao does not answer at {base}: {error}') from None

    def read(self, path):
        answer = self.raw('GET', f'{MOUNT}/data/{path}')
        if not answer:
            return {}, 0
        found = answer.get('data') or {}
        return dict(found.get('data') or {}), (found.get('metadata') or {}).get('version', 0)

    def write(self, path, values, cas):
        answer = self.raw('POST', f'{MOUNT}/data/{path}', {'options': {'cas': cas}, 'data': values})
        return answer['data']['version']

    def list(self, prefix):
        answer = self.raw('GET', f'{MOUNT}/metadata/{prefix.rstrip("/")}/?list=true')
        return sorted((answer or {}).get('data', {}).get('keys') or [])

    def delete(self, path):
        self.raw('DELETE', f'{MOUNT}/metadata/{path}')


# ----------------------------------------------------------------------------------------------------------------------
# The client of this process
# ----------------------------------------------------------------------------------------------------------------------

_client = None
_client_lock = threading.Lock()
# The role of the login of this process. use_role() sets it, so that a child process does not inherit it.
_role = None


def use_role(role):
    """Log in with role, for example backup, unless the process has a token of its parent."""
    global _role
    _role = role
    reset()


def in_cluster():
    return bool(os.environ.get('KUBERNETES_SERVICE_HOST')) and RUNNER_TOKEN.exists()


def kubectl(*args, input=None):
    kubeconfig = os.environ.get('KUBECONFIG')
    argv = ['kubectl', *(['--kubeconfig', kubeconfig] if kubeconfig else []), *args]
    result = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise StoreError(f'kubectl {" ".join(args[:4])} failed: {(result.stderr or result.stdout).strip()[-300:]}')
    return result.stdout


_ca_path = None


def ca_file():
    """A private file with the root certificate of OpenBao, from the ConfigMap openbao-ca. One file per process."""
    global _ca_path
    if _ca_path and Path(_ca_path).exists():
        return _ca_path
    namespace, name = CA_CONFIGMAP
    try:
        pem = kubectl('-n', namespace, 'get', 'configmap', name, '-o', 'jsonpath={.data.ca\\.crt}')
    except StoreError as error:
        raise StoreError(f'the ConfigMap {namespace}/{name} is unreadable: {error}. '
                         'Run deploy-k3s up --steps secret-store.') from None
    if 'BEGIN CERTIFICATE' not in pem:
        raise StoreError(f'the ConfigMap {namespace}/{name} has no certificate. Run deploy-k3s up --steps secret-store.')
    fd, path = tempfile.mkstemp(prefix='openbao-ca-', suffix='.crt')
    with os.fdopen(fd, 'w') as handle:
        handle.write(pem)
    import atexit
    atexit.register(lambda: os.path.exists(path) and os.unlink(path))
    _ca_path = path
    return path


def login(store, role, jwt):
    answer = store.raw('POST', 'auth/kubernetes/login', {'role': role, 'jwt': jwt}, token=False)
    try:
        return answer['auth']['client_token']
    except (KeyError, TypeError):
        raise StoreError(f'the login of the role {role} gave no token') from None


def client():
    """The store of this process. The first call connects and logs in."""
    global _client
    with _client_lock:
        if _client is not None:
            return _client
        address = os.environ.get(ENV_ADDRESS, '')
        if address.startswith('file://'):
            _client = FileStore(address[len('file://'):])
            return _client
        ca = ca_file()
        if address:
            store = OpenBao(address, ca=ca)
        elif in_cluster():
            store = OpenBao(f'https://{SERVICE}.{NAMESPACE}.svc:{PORT}', ca=ca)
        else:
            store = OpenBao(None, ca=ca, forward=KubeProxy(os.environ.get('KUBECONFIG')))
        token = os.environ.get(ENV_TOKEN)
        if not token:
            role = _role or os.environ.get(ENV_ROLE) or ('runner' if in_cluster() else 'deployer')
            if in_cluster():
                jwt = RUNNER_TOKEN.read_text().strip()
            else:
                jwt = kubectl('-n', NAMESPACE, 'create', 'token', DEPLOYER_ACCOUNT, '--duration=3600s').strip()
            token = login(store, role, jwt)
        store.token = token
        _client = store
        return store


def reset():
    """Forget the client of this process, for example after a test changed the environment."""
    global _client
    with _client_lock:
        if _client is not None and getattr(_client, 'forward', None):
            _client.forward.stop()
        _client = None


# ----------------------------------------------------------------------------------------------------------------------
# Operations
# ----------------------------------------------------------------------------------------------------------------------

def read(path):
    """{key: value} of a path, {} when it is missing."""
    return client().read(path)[0]


def update(path, change, attempts=8):
    """Read the path, apply change(dict) -> dict, and write the result with check-and-set. A write after another writer
    reads and changes again. Return the stored values. An unchanged result writes nothing."""
    store = client()
    for attempt in range(attempts):
        current, version = store.read(path)
        wanted = change(dict(current))
        if wanted == current:
            return current
        try:
            store.write(path, wanted, version)
            return wanted
        except CasConflict:
            time.sleep(0.2 * (attempt + 1) + random.randbelow(200) / 1000)
    raise StoreError(f'{path} changed during each of {attempts} writes')


def keep(path, wanted=None, copy=None, follow=(), drop=(), source='the copy'):
    """Keep the values of a generated secret in the store and return them.

    wanted gives a value or a generator for each missing key. A key in follow always takes the value of wanted,
    because another source owns it, for example the zone client secret. A key in drop goes.
    copy holds the values of an earlier copy, for example the Kubernetes Secret of an earlier version. A key that the
    store lacks takes the value of the copy. A key with another value in the copy stops the write (Mismatch), because
    a service can use the copy. source names the copy in that message. No stored value changes, except a key of follow.
    """
    wanted, copy = dict(wanted or {}), dict(copy or {})

    def change(data):
        for key, value in copy.items():
            if key in drop or key in follow:
                continue
            if key not in data:
                data[key] = value
            elif data[key] != value:
                raise Mismatch(f'the key {key} of {source} differs from the secret store path {MOUNT}/{path}. '
                               'Find which value the services use, write it into both, and run the step again.')
        for key, value in wanted.items():
            if key in follow:
                data[key] = value() if callable(value) else value
            elif key not in data:
                data[key] = value() if callable(value) else value
        for key in drop:
            data.pop(key, None)
        return data
    return update(path, change)


def replace(path, values, keys=None):
    """Write values over the stored keys of a path on purpose, for example after a restore. keys limits the change."""
    def change(data):
        data.update({k: v for k, v in values.items() if keys is None or k in keys})
        return data
    return update(path, change)


def remove(prefix):
    """Delete every path below prefix, with all versions. Return the deleted paths."""
    store = client()
    gone = []
    for name in store.list(prefix):
        path = f'{prefix.rstrip("/")}/{name}'
        if name.endswith('/'):
            gone += remove(path)
        else:
            store.delete(path)
            gone.append(path)
    return gone


def zone_path(zone, name='secrets'):
    if not ZONE.fullmatch(zone):
        raise StoreError(f'{zone} is no zone name')
    return f'zones/{zone}/{name}'


def zone_secrets(zone):
    """The secrets of a zone that zones.py generates. A SystemExit names the step when they are missing."""
    data = read(zone_path(zone))
    if not data:
        raise SystemExit(f'the secret store has no secrets of {zone}. Run zone.py apply {zone}.')
    return data


def record(zone, name):
    """The text of a record of a zone, or None."""
    data = read(zone_path(zone, f'records/{name}'))
    return data.get('content')


def write_record(zone, name, text):
    update(zone_path(zone, f'records/{name}'), lambda data: {'content': text})


def delete_record(zone, name):
    client().delete(zone_path(zone, f'records/{name}'))


def zone_token(zone, ttl='8h'):
    """A token of the token role zone-step for one zone: its policy reaches the paths of that zone only."""
    if not ZONE.fullmatch(zone):
        raise StoreError(f'{zone} is no zone name')
    store = client()
    if isinstance(store, FileStore):
        return f'file-token-{zone}'
    answer = store.raw('POST', 'auth/token/create/zone-step',
                       {'entity_alias': zone, 'ttl': ttl, 'display_name': f'zone-step-{zone}', 'no_parent': True})
    return answer['auth']['client_token']


def keep_files(path, folder, names):
    """Keep files of a folder in a path. names is [(file name, generator or None)].

    A file that exists gives its content as the copy of keep(). A missing value gets its generator, and a name
    without a generator stays missing. Each stored value is then written into its file of the folder (mode 0600), so
    the scripts that read the files keep working. Return the names of the written files.
    """
    folder = Path(folder)
    copy = {n: (folder / n).read_text() for n, _ in names if (folder / n).is_file()}
    wanted = {n: GENERATORS[g] for n, g in names if g}
    data = keep(path, wanted, copy, source=f'the file of {folder}')
    written = []
    folder.mkdir(parents=True, exist_ok=True)
    for name, _ in names:
        if name in data and (not (folder / name).is_file() or (folder / name).read_text() != data[name]):
            target = folder / name
            tmp = target.with_name(f'.{target.name}.{os.getpid()}.tmp')
            with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as handle:
                handle.write(data[name])
            os.replace(tmp, target)
            written.append(name)
    return written


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    if argv[0] == 'status':
        store = client()
        print(json.dumps({'sites': store.list('site'), 'zones': store.list('zones')}))
    elif argv[0] == 'files' and len(argv) >= 4:
        names = [(n.split(':', 1)[0], n.split(':', 1)[1] if ':' in n else None) for n in argv[3:]]
        for _, generator in names:
            if generator and generator not in GENERATORS:
                raise SystemExit(f'{generator} is no generator. The generators are {", ".join(GENERATORS)}.')
        print(json.dumps({'path': argv[1], 'written': keep_files(argv[1], argv[2], names)}))
    elif argv[0] == 'read' and len(argv) == 3:
        value = read(argv[1]).get(argv[2])
        if value is None:
            raise SystemExit(f'{MOUNT}/{argv[1]} has no key {argv[2]}')
        sys.stdout.write(value)
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except StoreError as error:
        raise SystemExit(str(error)) from None
