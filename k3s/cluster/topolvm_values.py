#!/usr/bin/env python3
"""Print the TopoLVM chart values of a site as JSON, which Helm reads as YAML. Usage: topolvm_values.py <hosts.json>

hosts.json is the form of the site file that `settings.py hosts` prints (config.legacy_hosts()), with the facts of
each node. Each node with storage gets its own lvmd configuration, selected by the label storage.hoover/lvmd=<node>.
The configuration has one device class per tier, on the volume group of that tier (storage of the site file). The
spare-gb of a class is the reserve of its volume group, 5 % of its size from the facts of the node
(config.storage_reserve()), so the cluster schedules at most 95 % of each tier on each node. Each tier gets the storage
classes <tier>-ext4 and <tier>-block. The default storage class is hdd-ext4 when a node has the tier hdd, else
ssd-ext4, else nvme-ext4, so a claim without a class binds on every site.
"""
import json
import sys

ORDER = ('hdd', 'ssd', 'nvme')


def values(hosts):
    configs, problems = [], []
    for name, host in sorted(hosts['hosts'].items()):
        storage = host.get('storage') or {}
        if not storage:
            continue
        tiers = [t for t in ORDER if t in storage]
        for tier in tiers:
            if storage[tier].get('spare_gb') is None:
                problems.append(f'{name} has no facts of the volume group {storage[tier]["volume_group"]} of the tier '
                                f'{tier}. Run deploy-k3s check --target {name}. Its facts play reads the volume groups '
                                'and refuses a missing one.')
        classes = [{'name': t, 'volume-group': storage[t]['volume_group'], 'default': t == tiers[0],
                    'spare-gb': storage[t].get('spare_gb')} for t in tiers]
        configs.append({'tolerations': [], 'nodeSelector': {'storage.hoover/lvmd': name}, 'deviceClasses': classes,
                        'nodes': [name]})
    if problems:
        raise SystemExit('\n'.join(problems))
    tiers_used = [t for t in ORDER if any(c['name'] == t for config in configs for c in config['deviceClasses'])]
    if not tiers_used:
        raise SystemExit('no node of the site has storage.')
    default = tiers_used[0]
    first = configs[0]
    out = {
        'lvmd': {'deviceClasses': first['deviceClasses'], 'nodeSelector': first['nodeSelector'],
                 'additionalConfigs': [{k: c[k] for k in ('tolerations', 'nodeSelector', 'deviceClasses')} for c in configs[1:]]},
        'node': {'nodeSelector': {'storage.hoover/enrolled': 'true'}},
        'storageClasses': [],
        # The volumes are thick LVs, and TopoLVM snapshots need thin LVs.
        'snapshot': {'enabled': False},
    }
    for tier in tiers_used:
        for kind in ('ext4', 'block'):
            out['storageClasses'].append({'name': f'{tier}-{kind}', 'storageClass': {
                'fsType': 'ext4', 'isDefaultClass': tier == default and kind == 'ext4',
                'volumeBindingMode': 'WaitForFirstConsumer', 'allowVolumeExpansion': True,
                'additionalParameters': {'topolvm.io/device-class': tier}}})
    if len(hosts['hosts']) == 1:
        # The chart runs two controllers on different nodes. A single-node site has one node for them.
        out['controller'] = {'replicaCount': 1}
    labels = {name: c['nodeSelector']['storage.hoover/lvmd'] for c in configs for name in c['nodes']}
    return out, labels


if __name__ == '__main__':
    hosts = json.load(open(sys.argv[1]))
    result, labels = values(hosts)
    if len(sys.argv) > 2 and sys.argv[2] == 'labels':
        for name, label in labels.items():
            print(name, f'storage.hoover/lvmd={label}')
    else:
        print(json.dumps(result, indent=1))
