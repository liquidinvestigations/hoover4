#!/usr/bin/env python3
"""Check one zone after a Helm upgrade or a replica restore.

The chart controllers run their stores in Kata. Their Services select the same pod labels.
The Hoover stores also run in Kata, with one StatefulSet for each store.
A disabled zone must have no running workload in any of its namespaces: every controller has zero replicas, every
CronJob is suspended, no Job is active, and no Service has a ready pod address.
Usage: zone-reconcile.py <zone>
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hoover' / 'stores'))
import common  # noqa: E402

STORE_LABEL = 'hoover.dev/store'
STORES = {
    'redis': ('statefulset', 'redis-master', ['redis-master']),
    'nats': ('statefulset', 'ums-provisioning-nats', ['ums-provisioning-nats']),
    'memcached': ('deployment', 'memcached', ['memcached']),
    'postgresql': ('statefulset', 'postgresql', ['postgresql']),
    'seaweedfs': ('deployment', 'seaweedfs-all-in-one', ['seaweedfs-all-in-one']),
    **{name: ('statefulset', name + '-kata', [name])
       for name in ('clickhouse', 'manticore', 'manticore-vectors', 'garage')},
}


def fail(errors, text):
    errors.append(text)
    print(text)


def replicas(namespace, kind, name):
    item = common.kubectl('-n', namespace, 'get', kind, name, '--ignore-not-found', '-o', 'json').strip()
    if not item:
        return None
    return json.loads(item)


def check_disabled(zone, errors):
    namespaces = common.zonestate.load()['zones'].get(zone, {}).get('namespaces', [zone])
    existing = {n['metadata']['name'] for n in common.kubectl_json('get', 'namespaces')['items']}
    for ns in namespaces:
        if ns not in existing:
            continue
        for kind in ('deployments', 'statefulsets', 'replicasets'):
            for item in common.kubectl_json('-n', ns, 'get', kind)['items']:
                if item['spec'].get('replicas', 1):
                    fail(errors, f"{ns}/{kind}/{item['metadata']['name']} has replicas {item['spec'].get('replicas', 1)}")
        for item in common.kubectl_json('-n', ns, 'get', 'daemonsets')['items']:
            fail(errors, f"{ns}/daemonset/{item['metadata']['name']} exists")
        for item in common.kubectl_json('-n', ns, 'get', 'pods')['items']:
            if item['status'].get('phase') in ('Pending', 'Running'):
                fail(errors, f"{ns}/pod/{item['metadata']['name']} is {item['status']['phase']}")
        for item in common.kubectl_json('-n', ns, 'get', 'cronjobs')['items']:
            if not item['spec'].get('suspend'):
                fail(errors, f"{ns}/cronjob/{item['metadata']['name']} is not suspended")
        for item in common.kubectl_json('-n', ns, 'get', 'jobs')['items']:
            if item['status'].get('active'):
                fail(errors, f"{ns}/job/{item['metadata']['name']} is active")
        for item in common.kubectl_json('-n', ns, 'get', 'endpointslices')['items']:
            ready = [a for e in item.get('endpoints') or [] if e.get('conditions', {}).get('ready') for a in e.get('addresses', [])]
            if ready:
                fail(errors, f"{ns}/endpointslice/{item['metadata']['name']} has ready addresses {ready}")
    common.log('reconcile.jsonl', zone=zone, disabled=True, ok=not errors, errors=errors)
    if errors:
        raise SystemExit(1)


def main():
    zone = sys.argv[1]
    errors = []
    if not common.namespace_enabled(zone):
        return check_disabled(zone, errors)
    for store, (kind, name, services) in STORES.items():
        item = replicas(zone, kind, name)
        if not item:
            fail(errors, f'{kind}/{name} does not exist')
            continue
        template = item['spec']['template']
        if template['spec'].get('runtimeClassName') != 'kata':
            fail(errors, f'{kind}/{name} does not use Kata')
        if template['metadata'].get('labels', {}).get(STORE_LABEL) != store:
            fail(errors, f'{kind}/{name} has no store label for {store}')
        if template['spec'].get('enableServiceLinks') is not False:
            fail(errors, f'{kind}/{name} publishes service links')
        for service in services:
            selector = common.kubectl_json('-n', zone, 'get', 'service', service)['spec'].get('selector') or {}
            if not selector or any(template['metadata'].get('labels', {}).get(k) != v for k, v in selector.items()):
                fail(errors, f'{service} does not select {kind}/{name}')
    common.log('reconcile.jsonl', zone=zone, ok=not errors, errors=errors)
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
