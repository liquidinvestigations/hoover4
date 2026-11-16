#!/usr/bin/env python3
"""Put the operator pod on the backup node and mount the backup folder in its runner container.

start-web-tools.sh sends the operator manifest (the JSON list of ../../zones/cpu_policy.py --render) through this file.
When the site file has vars.backup, the Deployment portal gets the node selector of the backup node. Its runner
container then mounts the folder of vars.backup at the same path (hostPath, type Directory). ../backups/backups.py
writes the copies into that folder without SSH. Without vars.backup the manifest does not change. The pod then runs on
the control-plane node and has no backup mount. A change of vars.backup changes this Deployment only.
The host step of the backup node (../../ansible/roles/hoover4_host/tasks/backup.yml) creates the folder before this
step, because the pod does not start without it.
Usage: backup-mount.py < list.json > list.json    HOOVER4_SITE names the site file.
"""
import json
import sys
from pathlib import Path

NAMESPACE = 'operator-portal'
DEPLOYMENT = 'portal'
CONTAINER = 'runner'
VOLUME = 'backups'
HOST = 'kubernetes.io/hostname'


def mount(items, backup):
    """The manifest items with the node and the mount of backup ({node, path}). An empty backup changes nothing."""
    if not backup:
        return items
    for item in items:
        meta = item.get('metadata') or {}
        if item.get('kind') != 'Deployment' or meta.get('name') != DEPLOYMENT or meta.get('namespace') != NAMESPACE:
            continue
        spec = item['spec']['template']['spec']
        spec['nodeSelector'] = {HOST: backup['node']}
        spec['volumes'] = [v for v in spec.get('volumes', []) if v['name'] != VOLUME]
        spec['volumes'].append({'name': VOLUME, 'hostPath': {'path': backup['path'], 'type': 'Directory'}})
        container = next(c for c in spec['containers'] if c['name'] == CONTAINER)
        container['volumeMounts'] = [m for m in container.get('volumeMounts', []) if m['name'] != VOLUME]
        container['volumeMounts'].append({'name': VOLUME, 'mountPath': backup['path']})
    return items


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import settings
    data = json.load(sys.stdin)
    backup = dict(settings.SITE.backup) if settings.SITE is not None and settings.SITE.backup else {}
    data['items'] = mount(data['items'], backup)
    print(json.dumps(data))


if __name__ == '__main__':
    main()
