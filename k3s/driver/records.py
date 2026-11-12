"""The deployment records of ../deploy-k3s on the control-plane host.

The folder is <operator state>/deploy (config.Site.operator_state()):
  records/<id>.json   one record for each up or down: the command, the targets, the revision that the driver resolved
                      once, the pinned inputs (deploy.pinned_inputs()), the steps with their state, the image
                      references with their digests and architectures, and the last error
  applied.json        a copy of the newest record of an up that finished
  previous.json       the copy that applied.json held before, so a failed update can return to it
  stopped.json        the replica counts that down recorded, which `up --start` restores
The driver holds the site operation lock of ../oplock.py while it runs, so no Apply, zone operation, migration step
or backup consistency step changes the site at the same time.
Each write goes to a temporary file, is synced and renamed, so a stopped driver leaves complete files.
A step has the state pending, running, done, failed or waiting. A waiting step needs an operator action on a host,
for example a remote installation script. A pending step with blocked_by waits for that step.
A record with a step that is not done is not a finished deployment.
"""
import json
import os
import time
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import oplock  # noqa: E402

STATES = ('pending', 'running', 'done', 'failed', 'waiting')


Busy = oplock.Busy


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    with open(tmp, 'w') as f:
        json.dump(value, f, indent=1, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class Records:
    def __init__(self, folder):
        self.folder = Path(folder)
        self._lock = None

    def lock(self, kind='deploy', operation_id=None):
        """Hold the site operation lock. Raise Busy while another operation holds it."""
        lock = oplock.SiteLock(self.folder.parent)
        lock.acquire(kind, operation_id or f'{kind}-{uuid.uuid4().hex[:8]}')
        self._lock = lock

    def unlock(self):
        if self._lock:
            self._lock.release()
            self._lock = None

    def path(self, record_id):
        return self.folder / 'records' / f'{record_id}.json'

    def new(self, command, targets, revision, steps, **extra):
        record_id = time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + '-' + uuid.uuid4().hex[:6]
        record = {'id': record_id, 'command': command, 'targets': list(targets), 'revision': revision,
                  'created': now(), 'status': 'running', 'error': '', 'images': {},
                  'steps': [{'name': s, 'state': 'pending'} for s in steps], **extra}
        self.save(record)
        return record

    def load(self, record_id):
        path = self.path(record_id)
        if not path.exists():
            raise KeyError(f'the deployment record {record_id} does not exist in {path.parent}.')
        return json.loads(path.read_text())

    def save(self, record):
        record['updated'] = now()
        write_json(self.path(record['id']), record)

    def list(self):
        folder = self.folder / 'records'
        return sorted(json.loads(p.read_text())['id'] for p in folder.glob('*.json')) if folder.exists() else []

    def step(self, record, name):
        for entry in record['steps']:
            if entry['name'] == name:
                return entry
        raise KeyError(name)

    def mark(self, record, name, state, **fields):
        assert state in STATES
        entry = self.step(record, name)
        entry['state'] = state
        entry[{'running': 'started'}.get(state, 'finished')] = now()
        entry.update(fields)
        self.save(record)

    def applied(self):
        path = self.folder / 'applied.json'
        return json.loads(path.read_text()) if path.exists() else None

    def previous(self):
        path = self.folder / 'previous.json'
        return json.loads(path.read_text()) if path.exists() else None

    def finish(self, record):
        """Mark an up as applied and keep the earlier applied record as previous.json."""
        record['status'] = 'done'
        self.save(record)
        current = self.applied()
        if current and current['id'] != record['id']:
            write_json(self.folder / 'previous.json', current)
        write_json(self.folder / 'applied.json', record)

    def stopped(self):
        path = self.folder / 'stopped.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def save_stopped(self, value):
        write_json(self.folder / 'stopped.json', value)

    def clear_stopped(self):
        (self.folder / 'stopped.json').unlink(missing_ok=True)
