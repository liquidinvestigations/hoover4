#!/usr/bin/env python3
"""Print the TopoLVM chart values of a site as JSON, which Helm reads as YAML. Usage: topolvm_values.py <hosts.json>

Each node with storage tiers gets one lvmd configuration with one device class per tier, on the volume group of the
node (`lvm_volume_group` of the site file). Nodes with the same tiers and volume group share a configuration, and the
node selectors of the configurations do not overlap. Each tier gets the storage classes <tier>-ext4 and <tier>-block.
The default storage class is hdd-ext4 when a node has the tier hdd, else ssd-ext4, else nvme-ext4, so a claim without
a class binds on every site. A hosts.json without a volume group name (the earlier form) keeps tier-<tier>.
"""
import json
import sys

ORDER = ('hdd', 'ssd', 'nvme')


def values(hosts):
    groups = {}
    for name, host in sorted(hosts['hosts'].items()):
        tiers = tuple(t for t in ORDER if t in host.get('tiers', []))
        if tiers:
            groups.setdefault((tiers, host.get('vg') or ''), []).append(name)
    tiers_used = [t for t in ORDER if any(t in key[0] for key in groups)]
    if not tiers_used:
        raise SystemExit('no node of the site has storage tiers.')
    default = tiers_used[0]
    configs = []
    for (tiers, vg), names in sorted(groups.items()):
        classes = [{'name': t, 'volume-group': vg or f'tier-{t}', 'default': t == tiers[0], 'spare-gb': 10} for t in tiers]
        configs.append({'tolerations': [], 'nodeSelector': {'storage.hoover/lvmd': '-'.join(tiers) + ('.' + vg if vg else '')},
                        'deviceClasses': classes, 'nodes': names})
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
