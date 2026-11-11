#!/usr/bin/env python3
"""Stop or start the zones. `down` records the replicas of every Deployment and StatefulSet and sets them to zero.

`up` sets the recorded replicas again. A namespace of a disabled zone stays at zero. The record is
`zones-replicas.json` in k3s/private/stores. `down` keeps an existing record, so a second `down` does not lose
the replicas of the first one. The zone list comes from the zone state (zonestate.py) and includes extensions.
Usage: zone-switch.py down | up | status
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hoover' / 'stores'))
import common  # noqa: E402
import zonestate  # noqa: E402

NAMESPACES = [ns for entry in zonestate.load()['zones'].values() for ns in entry['namespaces']] + ['extensions']
RECORD = common.PRIVATE / 'zones-replicas.json'


def controllers(namespace):
    for kind in ('deployment', 'statefulset'):
        for item in common.kubectl_json('-n', namespace, 'get', kind)['items']:
            yield kind, item['metadata']['name'], item['spec'].get('replicas', 1)


def down():
    common.PRIVATE.mkdir(parents=True, exist_ok=True)
    record = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    for namespace in NAMESPACES:
        for kind, name, replicas in controllers(namespace):
            record.setdefault(f'{namespace}/{kind}/{name}', replicas)
    RECORD.write_text(json.dumps(record, indent=1))
    for namespace in NAMESPACES:
        common.kubectl('-n', namespace, 'scale', 'deployment,statefulset', '--all', '--replicas=0')
    deadline = time.time() + 600
    while time.time() < deadline and (left := running()):
        time.sleep(5)
    common.log('zones.jsonl', step='down', controllers=len(record), pods_left=running())


def running():
    return sum(1 for ns in NAMESPACES for p in common.kubectl_json('-n', ns, 'get', 'pods')['items']
               if p['metadata'].get('ownerReferences', [{}])[0].get('kind') in ('ReplicaSet', 'StatefulSet')
               and p['status'].get('phase') in ('Pending', 'Running'))


def up():
    record = json.loads(RECORD.read_text())
    skipped = []
    for key, replicas in sorted(record.items()):
        namespace, kind, name = key.split('/')
        if not replicas:
            continue
        if not common.namespace_enabled(namespace):
            skipped.append(key)
            continue
        common.kubectl('-n', namespace, 'scale', kind, name, f'--replicas={replicas}', check=False)
    common.log('zones.jsonl', step='up', controllers=len(record), skipped=skipped)


if __name__ == '__main__':
    {'down': down, 'up': up, 'status': lambda: print(running())}[sys.argv[1]]()
