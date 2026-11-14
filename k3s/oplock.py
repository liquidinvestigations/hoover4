"""The one site operation lock of a cluster installation. Standard library only.

Every operation that changes services or stored data of a site holds this lock while it runs: deploy-k3s up and down,
the settings Apply and the zone operations of the operator runner, the Compose import, and the backup jobs at
their consistency boundary. A settings save does not take it, so an operator can save settings during a deployment.
The saved revision then waits for a later Apply.

site_lock() gives the lock of a site. When the cluster of the site answers, it is the Lease site-operation of the
namespace operator-portal (LeaseLock). deploy-k3s on the workstation and the runner in the operator pod then exclude
each other. Before the cluster exists, for example in the first host steps of deploy-k3s up, it is the file lock of
the operator state folder (SiteLock).

LeaseLock: the holder renews the Lease every RENEW seconds. A Lease that nobody renewed for DURATION seconds is free,
so a killed holder blocks the site for at most DURATION seconds. The annotation hoover.dev/site-operation names the
holder: its kind, its operation id, its host and its process id.
SiteLock: an flock on <operator state>/site-operation.lock. The kernel releases it when its process ends.
<operator state>/site-operation.json names the holder.
A new holder that finds the record of an earlier holder that did not release records it as `recovered`.
A child process of the holder gets HOOVER4_SITE_OPERATION=<id> and runs inside the operation of its parent without a
second lock.
"""
import fcntl
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

ENV = 'HOOVER4_SITE_OPERATION'
NAMESPACE = 'operator-portal'
LEASE = 'site-operation'
ANNOTATION = 'hoover.dev/site-operation'
DURATION = 90
RENEW = 20


class Busy(RuntimeError):
    """Another operation holds the site lock. The message names it."""


def _write(path, value):
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    with open(tmp, 'w') as f:
        json.dump(value, f, indent=1, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class SiteLock:
    def __init__(self, state_folder):
        self.folder = Path(state_folder)
        self.path = self.folder / 'site-operation.lock'
        self.record = self.folder / 'site-operation.json'
        self.handle = None
        self.inherited = False
        self.owner = None

    def holder(self):
        """The record of the current or last holder, or None."""
        try:
            return json.loads(self.record.read_text())
        except (OSError, ValueError):
            return None

    def busy(self):
        """The record of the holder when another process holds the lock now, else None. It takes no lock."""
        if not self.path.exists():
            return None
        with open(self.path, 'a+') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return self.holder() or {'kind': 'unknown'}
            fcntl.flock(handle, fcntl.LOCK_UN)
        return None

    def acquire(self, kind, operation_id, wait=0.0):
        """Hold the lock for one operation. wait is the number of seconds to wait for another holder."""
        inherited = os.environ.get(ENV)
        if inherited:
            # A child of the holder runs inside the operation of its parent.
            current = self.holder() or {}
            # The holder process itself takes no second lock: a second acquire in one process is a conflict.
            if current.get('id') == inherited and current.get('state') == 'held' and current.get('pid') != os.getpid():
                self.inherited = True
                self.owner = current
                return current
        self.folder.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, 'a+')
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    other = self.holder() or {}
                    raise Busy(f'the site operation {other.get("kind", "unknown")} {other.get("id", "")} runs on '
                               f'{other.get("host", "an unknown host")} since {other.get("started", "an unknown time")}. '
                               'Wait for it to end.')
                time.sleep(1)
        earlier = self.holder()
        owner = {'kind': kind, 'id': operation_id, 'host': socket.gethostname(), 'pid': os.getpid(),
                 'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'state': 'held'}
        if earlier and earlier.get('state') == 'held':
            # The earlier holder ended without a release. The flock proves that it no longer runs.
            owner['recovered'] = {k: earlier.get(k) for k in ('kind', 'id', 'host', 'pid', 'started')}
        _write(self.record, owner)
        self.handle = handle
        self.owner = owner
        os.environ[ENV] = operation_id
        return owner

    def release(self):
        if self.inherited:
            self.inherited = False
            return
        if self.handle is None:
            return
        owner = dict(self.owner or {}, state='released',
                     released=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        _write(self.record, owner)
        os.environ.pop(ENV, None)
        self.handle.close()
        self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%S.000000Z', time.gmtime())


def _seconds(stamp):
    import calendar
    try:
        return calendar.timegm(time.strptime(stamp.split('.')[0].rstrip('Z'), '%Y-%m-%dT%H:%M:%S'))
    except (AttributeError, ValueError):
        return 0


class LeaseLock:
    """The site lock as the Lease site-operation of the namespace operator-portal. kubectl reaches the cluster."""

    def __init__(self, kubeconfig=None):
        self.kubeconfig = str(kubeconfig) if kubeconfig else os.environ.get('KUBECONFIG', '')
        self.inherited = False
        self.owner = None
        self.held = None
        self.stop = threading.Event()
        self.renewer = None

    def kubectl(self, *args, data=None):
        argv = ['kubectl', *(['--kubeconfig', self.kubeconfig] if self.kubeconfig else []), '-n', NAMESPACE, *args]
        return subprocess.run(argv, input=data, capture_output=True, text=True, timeout=60)

    def lease(self):
        """The Lease object, or None when it does not exist."""
        result = self.kubectl('get', 'lease', LEASE, '-o', 'json')
        if result.returncode:
            if 'NotFound' in result.stderr or 'not found' in result.stderr:
                return None
            raise RuntimeError(f'the site lock {NAMESPACE}/{LEASE} is unreadable: {result.stderr.strip()[-300:]}')
        return json.loads(result.stdout)

    @staticmethod
    def record(lease):
        try:
            return json.loads((lease['metadata'].get('annotations') or {}).get(ANNOTATION, ''))
        except ValueError:
            return None

    @staticmethod
    def live(lease):
        """True when the holder of the Lease renewed it within its duration."""
        spec = lease.get('spec') or {}
        if not spec.get('holderIdentity'):
            return False
        renewed = _seconds(spec.get('renewTime') or spec.get('acquireTime') or '')
        return time.time() - renewed < int(spec.get('leaseDurationSeconds') or DURATION)

    def holder(self):
        lease = self.lease()
        return self.record(lease) if lease else None

    def busy(self):
        lease = self.lease()
        if lease and self.live(lease):
            return self.record(lease) or {'kind': 'unknown', 'id': lease['spec']['holderIdentity']}
        return None

    def write(self, lease, owner):
        """Create or replace the Lease. Return False when another writer changed it first."""
        body = {'apiVersion': 'coordination.k8s.io/v1', 'kind': 'Lease',
                'metadata': {'name': LEASE, 'namespace': NAMESPACE, 'annotations': {ANNOTATION: json.dumps(owner, sort_keys=True)}},
                'spec': {'holderIdentity': owner['id'] if owner.get('state') == 'held' else '',
                         'leaseDurationSeconds': DURATION, 'renewTime': _now()}}
        if owner.get('state') == 'held':
            body['spec']['acquireTime'] = (lease or {}).get('spec', {}).get('acquireTime') if (
                lease and (lease.get('spec') or {}).get('holderIdentity') == owner['id']) else _now()
        if lease:
            body['metadata']['resourceVersion'] = lease['metadata']['resourceVersion']
        result = self.kubectl('replace' if lease else 'create', '-f', '-', data=json.dumps(body))
        if result.returncode:
            if 'the object has been modified' in result.stderr or 'AlreadyExists' in result.stderr:
                return False
            raise RuntimeError(f'the site lock {NAMESPACE}/{LEASE} cannot be written: {result.stderr.strip()[-300:]}')
        return True

    def acquire(self, kind, operation_id, wait=0.0):
        inherited = os.environ.get(ENV)
        if inherited:
            lease = self.lease()
            current = (self.record(lease) or {}) if lease else {}
            if lease and self.live(lease) and current.get('id') == inherited and current.get('pid') != os.getpid():
                self.inherited = True
                self.owner = current
                return current
        deadline = time.monotonic() + wait
        while True:
            lease = self.lease()
            if lease and self.live(lease):
                if time.monotonic() >= deadline:
                    other = self.record(lease) or {}
                    raise Busy(f'the site operation {other.get("kind", "unknown")} {other.get("id", "")} runs on '
                               f'{other.get("host", "an unknown host")} since {other.get("started", "an unknown time")}. '
                               'Wait for it to end.')
                time.sleep(2)
                continue
            owner = {'kind': kind, 'id': operation_id, 'host': socket.gethostname(), 'pid': os.getpid(),
                     'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'state': 'held'}
            earlier = self.record(lease) if lease else None
            if earlier and earlier.get('state') == 'held':
                # The earlier holder stopped its renewals without a release.
                owner['recovered'] = {k: earlier.get(k) for k in ('kind', 'id', 'host', 'pid', 'started')}
            if self.write(lease, owner):
                break
        self.owner = owner
        self.held = True
        os.environ[ENV] = operation_id
        self.stop.clear()
        self.renewer = threading.Thread(target=self._renew, daemon=True)
        self.renewer.start()
        return owner

    def _renew(self):
        while not self.stop.wait(RENEW):
            try:
                lease = self.lease()
                if lease is None or (lease.get('spec') or {}).get('holderIdentity') != self.owner['id']:
                    print(json.dumps({'site_lock': 'lost', 'id': self.owner['id']}), flush=True)
                    return
                self.write(lease, self.owner)
            except (RuntimeError, OSError, subprocess.SubprocessError) as error:
                # The next renewal tries again. The API server can be away during a k3s restart.
                print(json.dumps({'site_lock': 'renewal failed', 'error': str(error)[:200]}), flush=True)

    def release(self):
        if self.inherited:
            self.inherited = False
            return
        if not self.held:
            return
        self.stop.set()
        if self.renewer:
            self.renewer.join(timeout=5)
        owner = dict(self.owner or {}, state='released', released=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        for _ in range(5):
            lease = self.lease()
            if lease is None or (lease.get('spec') or {}).get('holderIdentity') != self.owner['id']:
                break
            if self.write(lease, owner):
                break
        os.environ.pop(ENV, None)
        self.held = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def cluster_answers(kubeconfig):
    """True when the API server of the kubeconfig answers. A missing kubeconfig file gives False."""
    if not kubeconfig or not Path(kubeconfig).exists():
        return False
    try:
        result = subprocess.run(['kubectl', '--kubeconfig', str(kubeconfig), '--request-timeout=5s', 'get', '--raw',
                                 '/readyz'], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == 'ok'


def site_lock(state_folder, kubeconfig=None):
    """The lock of the site of an operator state folder: the Lease when the cluster answers, else the file lock.

    kubeconfig defaults to $KUBECONFIG, else to kubeconfig of the state folder of the site (the parent folder).
    """
    kubeconfig = kubeconfig or os.environ.get('KUBECONFIG') or Path(state_folder).parent / 'kubeconfig'
    if cluster_answers(kubeconfig):
        return LeaseLock(kubeconfig)
    return SiteLock(state_folder)
