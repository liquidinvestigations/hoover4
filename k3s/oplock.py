"""The one site operation lock of a cluster installation. Standard library only.

Every operation that changes services or stored data of a site holds this lock while it runs: deploy-k3s up and down,
the settings Apply and the zone operations of the operator runner, the steps of a migration, and the backup jobs at
their consistency boundary. A settings save does not take it, so an operator can save settings during a deployment.
The saved revision then waits for a later Apply.

The lock is an flock on <operator state>/site-operation.lock. The kernel releases it when its process ends, so a
stopped or killed process never leaves a stale lock, and no process id is proof of ownership.
<operator state>/site-operation.json names the holder: its kind, its operation id, its host and its process id.
A new holder that finds the record of an earlier holder records it as `recovered`, because the earlier process ended
without a release. A child process of the holder gets HOOVER4_SITE_OPERATION=<id> and runs inside the operation of its
parent without a second lock.
"""
import fcntl
import json
import os
import socket
import time
from pathlib import Path

ENV = 'HOOVER4_SITE_OPERATION'


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
