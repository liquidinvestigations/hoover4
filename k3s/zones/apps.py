#!/usr/bin/env python3
"""Turn the openDesk applications of a zone off and on as the operator settings app.<name> say. Usage: apps.py <zone>

An application that is off has zero replicas. Its claims, Secrets and database rows stay, so turning it on again
restores it with its data. The script records the replica count of each workload in the annotation
hoover.dev/replicas-before-disable before it scales the workload to zero, and restores that count later.
postrender.py renders the same replica counts, so a later zone.py apply keeps the state.
HOOVER4_SETTINGS_REVISION names the saved settings revision, for example the revision of an apply operation.
The Hoover application of the zone follows app.hoover through ../hoover/manifests.py.
"""
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import settings  # noqa: E402
import postrender  # noqa: E402

ANNOTATION = 'hoover.dev/replicas-before-disable'


def kubectl(*args):
    return subprocess.run(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), *args], capture_output=True, text=True,
                          check=True).stdout


def main(zone):
    values = postrender.operator_values(zone)
    items = json.loads(kubectl('-n', zone, 'get', 'deployments,statefulsets', '-o', 'json'))['items']
    changed = []
    for item in items:
        name, kind = item['metadata']['name'], item['kind'].lower()
        app = next((a for a, patterns in postrender.APP_WORKLOADS.items()
                    if any(fnmatch.fnmatchcase(name, p) for p in patterns)), None)
        if app is None:
            continue
        replicas = item['spec'].get('replicas', 1)
        before = (item['metadata'].get('annotations') or {}).get(ANNOTATION)
        if values[f'app.{app}'] == 'false' and replicas:
            kubectl('-n', zone, 'annotate', kind, name, f'{ANNOTATION}={replicas}', '--overwrite')
            kubectl('-n', zone, 'scale', kind, name, '--replicas=0')
            changed.append(f'{app}/{name}')
        elif values[f'app.{app}'] == 'true' and before is not None:
            kubectl('-n', zone, 'scale', kind, name, f'--replicas={before}')
            kubectl('-n', zone, 'annotate', kind, name, f'{ANNOTATION}-')
            changed.append(f'{app}/{name}')
    print(json.dumps({'zone': zone, 'changed': changed}))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
