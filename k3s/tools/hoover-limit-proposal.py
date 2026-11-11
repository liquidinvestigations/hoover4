#!/usr/bin/env python3
"""Propose new memory limits for the Kata pods of the Hoover of a zone, from their peaks.

Usage: hoover-limit-proposal.py <zone> [--accept] [--watch SECONDS]

A Kata VM holds its whole limit, so the limit of a Kata pod is memory that no other pod gets. The Temporal tuner of each
worker lowers the activity slots when the VM runs short of memory (HOOVER4_SLOT_TUNER in ../hoover/manifests.py).
This tool proposes the limit for the next upgrade.
The tool reads memory.peak and memory.max of the container cgroup inside each VM with kubectl exec. Inside the VM the
cgroup counts only the container, and memory.peak is its peak since the start. The proposal uses the rule of the
cluster. It takes the larger of 1.5 times the peak and the peak plus 256 MiB, and rounds it up to 128 MiB. A worker pod gets at least the sum of
its derived processes (../hoover/zone_ini.py). It writes the proposal to k3s/private/zones/<zone>/hoover-budget-proposal.json.
--accept writes the proposed worker memory into hoover_budget of k3s/private/settings.json, and the next zone upgrade
applies it. --watch repeats the reading, keeps the highest peak of each pod, and writes the proposal after each round.
The operator accepts a proposal. The tool changes no cluster object.
"""
import json
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hoover'))
import settings  # noqa: E402
import zone_ini  # noqa: E402

settings.use_kubeconfig()
MIB = 1 << 20
# The Deployments with Kata pods, and the budget key of each.
KATA = {'hoover-workers': 'worker_memory_mib', 'hoover-singletons': None, 'hoover-operations': None}


def rule(peak_mib, key):
    limit = math.ceil(max(1.5 * peak_mib, peak_mib + 256) / 128) * 128
    # A worker pod needs at least the memory of its derived processes.
    return max(limit, zone_ini.PROCESS_MIB + zone_ini.SLOT_MIB + zone_ini.OTHER_MIB) if key else limit


def read(zone):
    pods = json.loads(subprocess.run(['kubectl', '-n', f'hoover-{zone}', 'get', 'pods', '-o', 'json'], capture_output=True,
                                     text=True, check=True).stdout)['items']
    found = {}
    for pod in pods:
        name = pod['metadata'].get('labels', {}).get('app.kubernetes.io/name')
        if name not in KATA or pod['status'].get('phase') != 'Running':
            continue
        out = subprocess.run(['kubectl', '-n', f'hoover-{zone}', 'exec', pod['metadata']['name'], '-c', name, '--', 'cat',
                              '/sys/fs/cgroup/memory.peak', '/sys/fs/cgroup/memory.max'], capture_output=True, text=True)
        values = out.stdout.split()
        if out.returncode or len(values) != 2:
            continue
        found[pod['metadata']['name']] = {'deployment': name, 'peak_mib': int(values[0]) // MIB,
                                          'max_mib': None if values[1] == 'max' else int(values[1]) // MIB}
    return found


def proposal(zone, peaks):
    out = {'zone': zone, 'time': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'pods': peaks, 'deployments': {}}
    for deployment, key in KATA.items():
        rows = [p for p in peaks.values() if p['deployment'] == deployment]
        if not rows:
            continue
        peak = max(p['peak_mib'] for p in rows)
        out['deployments'][deployment] = {'peak_mib': peak, 'limit_mib': rows[0]['max_mib'], 'proposed_mib': rule(peak, key),
                                          'budget_key': key}
    return out


def accept(zone, result):
    path = settings.PRIVATE / 'settings.json'
    data = json.loads(path.read_text())
    budget = data.setdefault('hoover_budget', {}).setdefault(zone, {})
    for row in result['deployments'].values():
        if row['budget_key']:
            budget[row['budget_key']] = row['proposed_mib']
    path.write_text(json.dumps(data, indent=1) + '\n')
    return budget


def main():
    args = sys.argv[1:]
    if not args or args[0].startswith('-'):
        sys.exit(__doc__)
    zone = args[0]
    watch = int(args[args.index('--watch') + 1]) if '--watch' in args else 0
    target = settings.PRIVATE / 'zones' / zone / 'hoover-budget-proposal.json'
    peaks = {}
    while True:
        for pod, row in read(zone).items():
            if pod not in peaks or row['peak_mib'] > peaks[pod]['peak_mib']:
                peaks[pod] = row
        result = proposal(zone, peaks)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=1) + '\n')
        print(json.dumps(result['deployments']), flush=True)
        if not watch:
            break
        time.sleep(watch)
    if '--accept' in args:
        print(json.dumps({'accepted': accept(zone, result)}))


if __name__ == '__main__':
    main()
