#!/usr/bin/env python3
"""Record the desired state of every object of a zone, to show that a second installer run changes no object.

For each object in the zone namespaces the record holds a hash of its content without status and server fields:
metadata labels and annotations, spec, data and the other top-level fields. Pods, Events, EndpointSlices, Endpoints,
Leases, ReplicaSets, ControllerRevisions and finished Jobs are left out, because controllers write them at run time.
The record also holds the zone pod policy. A Helm release Secret counts by its name, so a new release revision shows
as an added object.
Usage:
  zone-snapshot.py record <zone> <file>
  zone-snapshot.py compare <before file> <after file>    prints each added, removed or changed object, exit 1 on a difference
"""
import hashlib
import copy
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402
K = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG)]
SKIP = {'Pod', 'Event', 'EndpointSlice', 'Endpoints', 'Lease', 'ReplicaSet', 'ControllerRevision'}
SERVER = {'uid', 'resourceVersion', 'generation', 'creationTimestamp', 'managedFields', 'selfLink', 'ownerReferences'}
# Fields that controllers write into the objects at run time.
RUNTIME_ANNOTATIONS = ('deployment.kubernetes.io/revision', 'kubectl.kubernetes.io/last-applied-configuration',
                       'pv.kubernetes.io/', 'volume.kubernetes.io/', 'volume.beta.kubernetes.io/', 'leader',
                       'control-plane.alpha.kubernetes.io/leader', 'meta.helm.sh/', 'endpoints.kubernetes.io/')


def kubectl(*args):
    return json.loads(subprocess.run(K + list(args), capture_output=True, text=True, check=True).stdout)


def clean(item):
    item = copy.deepcopy(item)
    item.pop('status', None)
    meta = {k: v for k, v in item.pop('metadata', {}).items() if k not in SERVER}
    meta['annotations'] = {k: v for k, v in (meta.get('annotations') or {}).items() if not k.startswith(RUNTIME_ANNOTATIONS)}
    item['metadata'] = meta
    if item.get('kind') == 'PersistentVolumeClaim':
        item.get('spec', {}).pop('volumeName', None)
    return item


def record(zone):
    kinds = [line.split()[0] for line in subprocess.run(K + ['api-resources', '--namespaced', '--verbs=list', '-o', 'name'],
                                                         capture_output=True, text=True, check=True).stdout.split()]
    out = {}
    state = kubectl('get', 'mutatingadmissionpolicy,mutatingadmissionpolicybinding', '-o', 'json')['items']
    for item in state:
        if item['metadata']['name'] != 'hoover-zone-pods':
            continue
        out[f"cluster/{item['kind']}/{item['metadata']['name']}"] = hashlib.sha256(json.dumps(clean(item), sort_keys=True).encode()).hexdigest()[:16]
    for namespace in (zone, f'hoover-{zone}'):
        item = kubectl('get', 'namespace', namespace, '-o', 'json')
        out[f"cluster/Namespace/{namespace}"] = hashlib.sha256(json.dumps(clean(item), sort_keys=True).encode()).hexdigest()[:16]
        items = kubectl('-n', namespace, 'get', ','.join(k for k in kinds if k.split('.')[0] not in
                                                          ('pods', 'events', 'endpointslices', 'endpoints', 'leases', 'replicasets',
                                                           'controllerrevisions', 'localsubjectaccessreviews', 'bindings')),
                        '-o', 'json')['items']
        for item in items:
            if item['kind'] in SKIP:
                continue
            if item['kind'] == 'Job' and (item.get('status') or {}).get('completionTime'):
                continue
            key = f"{namespace}/{item['kind']}/{item['metadata']['name']}"
            out[key] = hashlib.sha256(json.dumps(clean(item), sort_keys=True).encode()).hexdigest()[:16]
            if item['kind'] == 'Secret' and item.get('type') == 'helm.sh/release.v1':
                out[key] = 'release'
    return out


def main():
    if sys.argv[1:2] == ['record'] and len(sys.argv) == 4:
        data = record(sys.argv[2])
        Path(sys.argv[3]).write_text(json.dumps(data, indent=1, sort_keys=True))
        print(json.dumps({'objects': len(data), 'file': sys.argv[3]}))
    elif sys.argv[1:2] == ['compare'] and len(sys.argv) == 4:
        before, after = (json.loads(Path(p).read_text()) for p in sys.argv[2:4])
        diff = [{'object': k, 'change': 'added' if k not in before else 'removed' if k not in after else 'changed'}
                for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
        for row in diff:
            print(json.dumps(row))
        print(json.dumps({'before': len(before), 'after': len(after), 'differences': len(diff)}))
        sys.exit(1 if diff else 0)
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
