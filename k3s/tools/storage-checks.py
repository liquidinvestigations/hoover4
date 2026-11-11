#!/usr/bin/env python3
"""Run the storage checks of the cluster against TopoLVM volumes in Kata and gVisor. Each check prints JSON lines.

  t1 <zone>          PostgreSQL of the zone (Kata, raw block volume): pgbench in a scratch database, then pg_amcheck
                     over every database. The scratch database is dropped at the end.
  t5 <zone>          grows the block volume of the zone Redis by 1 GiB while its Kata pod runs, and reads the size of
                     the device inside the guest before and after. The volume keeps the new size.
  t6 <node>          a gVisor pod writes and syncs a file on a new ext4 volume. After the delete of the pod and the claim,
                     TopoLVM must remove the logical volume.
  t8 <node>          one ReadWriteOnce ext4 volume in one gVisor pod and two Kata pods on one node. The gVisor pod writes
                     a file, and both Kata pods read the same checksum.
t6 and t8 use the namespace storage-check and delete it at the end. The tier is the first tier of the node.
Usage: storage-checks.py t1|t5 <zone> | t6|t8 <node>
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'zones'))
import settings  # noqa: E402
import zonestate  # noqa: E402
K = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG)]
NS = 'storage-check'
IMAGE = 'docker.io/library/alpine:3.22'


def kubectl(*args, input=None, check=True, timeout=900):
    r = subprocess.run(K + list(args), input=input, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:5])}: {r.stderr.strip()[-500:]}')
    return r.stdout


def report(**row):
    print(json.dumps({'at': time.strftime('%H:%M:%S'), **row}), flush=True)


def psql(zone, sql, database='postgres', check=True):
    return kubectl('-n', zone, 'exec', '-i', 'postgresql-0', '-c', 'postgresql', '--', 'psql', '-U', 'postgres', '-d', database,
                   '-v', 'ON_ERROR_STOP=1', '-Atq', input=sql, check=check)


def t1(zone):
    psql(zone, 'DROP DATABASE IF EXISTS storage_check; CREATE DATABASE storage_check;')
    run = lambda *a: subprocess.run(K + ['-n', zone, 'exec', 'postgresql-0', '-c', 'postgresql', '--', *a], capture_output=True, text=True, timeout=1800)
    init = run('pgbench', '-U', 'postgres', '-i', '-s', '10', '-q', 'storage_check')
    report(check='t1', step='pgbench-init', exit=init.returncode, tail=init.stderr.strip().splitlines()[-1:])
    bench = run('pgbench', '-U', 'postgres', '-c', '4', '-j', '2', '-T', '60', 'storage_check')
    tps = [line for line in bench.stdout.splitlines() if line.startswith('tps')]
    report(check='t1', step='pgbench', exit=bench.returncode, result=tps, failed=[l for l in bench.stdout.splitlines() if 'failed' in l])
    amcheck = run('sh', '-c', 'psql -U postgres -d storage_check -qc "CREATE EXTENSION IF NOT EXISTS amcheck" && '
                  'pg_amcheck -U postgres --all --install-missing --heapallindexed --parent-check')
    report(check='t1', step='pg_amcheck', exit=amcheck.returncode, output=(amcheck.stdout + amcheck.stderr).strip().splitlines()[-3:])
    psql(zone, 'DROP DATABASE storage_check;')
    mount = run('sh', '-c', 'grep " /mnt/postgresql " /proc/mounts; cat /sys/block/*/queue/rotational 2>/dev/null | head -1')
    report(check='t1', step='volume', mount=mount.stdout.strip().splitlines())
    failures = re.search(r'number of failed transactions:\s*(\d+)', bench.stdout)
    if init.returncode or bench.returncode or amcheck.returncode or not tps or not failures or int(failures[1]):
        raise SystemExit(1)


def size_in_guest(zone, pod, container, device):
    return int(kubectl('-n', zone, 'exec', pod, '-c', container, '--', '/tools/busybox', 'blockdev', '--getsize64', device).strip())


def t5(zone):
    pvc, pod, device = 'redis-data-redis-master-0', 'redis-master-0', '/dev/block-redis-data'
    before = size_in_guest(zone, pod, 'redis', device)
    requested = kubectl('-n', zone, 'get', 'pvc', pvc, '-o', 'jsonpath={.spec.resources.requests.storage}')
    grown = f'{int(requested.rstrip("Gi")) + 1}Gi'
    kubectl('-n', zone, 'patch', 'pvc', pvc, '--type', 'merge', '-p', json.dumps({'spec': {'resources': {'requests': {'storage': grown}}}}))
    deadline = time.time() + 180
    capacity = ''
    while time.time() < deadline:
        capacity = kubectl('-n', zone, 'get', 'pvc', pvc, '-o', 'jsonpath={.status.capacity.storage}')
        if capacity == grown:
            break
        time.sleep(3)
    time.sleep(5)
    after = size_in_guest(zone, pod, 'redis', device)
    restarts = kubectl('-n', zone, 'get', 'pod', pod, '-o', 'jsonpath={.status.containerStatuses[0].restartCount}')
    report(check='t5', pvc=pvc, requested=[requested, grown], capacity=capacity, guest_bytes_before=before, guest_bytes_after=after,
           guest_sees_new_size=after > before, restarts=restarts)
    if capacity != grown:
        raise SystemExit(1)


def pod(name, node, runtime, command, claim):
    # A node selector, not nodeName: the scheduler binds a WaitForFirstConsumer claim only for a pod that it schedules.
    spec = {'nodeSelector': {'kubernetes.io/hostname': node}, 'restartPolicy': 'Never', 'terminationGracePeriodSeconds': 5,
            'containers': [{'name': 'main', 'image': IMAGE, 'command': ['sh', '-c', command],
                            'resources': {'limits': {'cpu': '1', 'memory': '128Mi'}},
                            'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
            'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}}]}
    if runtime:
        spec['runtimeClassName'] = runtime
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': NS}, 'spec': spec}


def claim(name, node):
    tier = [t for t in zonestate.TIER_ORDER if t in zonestate.node_tiers(node, settings.KUBECONFIG)][0]
    return {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name, 'namespace': NS},
            'spec': {'accessModes': ['ReadWriteOnce'], 'storageClassName': f'{tier}-ext4', 'resources': {'requests': {'storage': '1Gi'}}}}


def finished(name, seconds=300):
    deadline = time.time() + seconds
    while time.time() < deadline:
        phase = kubectl('-n', NS, 'get', 'pod', name, '-o', 'jsonpath={.status.phase}', check=False)
        if phase in ('Succeeded', 'Failed'):
            return phase, kubectl('-n', NS, 'logs', name, check=False).strip()
        time.sleep(2)
    return 'timeout', ''


def logical_volumes(volume):
    items = json.loads(kubectl('get', 'logicalvolumes.topolvm.io', '-o', 'json'))['items']
    return [i['metadata']['name'] for i in items if i['spec'].get('name') == volume]


def checksum(log):
    """Return the SHA-256 checksum from a successful file read."""
    match = re.search(r'^([0-9a-f]{64})\s+/data/\S+$', log, re.MULTILINE)
    return match[1] if match else None


def t6(node):
    kubectl('create', 'namespace', NS)
    try:
        kubectl('apply', '-f', '-', input=json.dumps(claim('t6', node)))
        kubectl('apply', '-f', '-', input=json.dumps(pod('t6', node, 'gvisor', 'dd if=/dev/urandom of=/data/f bs=1M count=64 conv=fsync && sha256sum /data/f', 't6')))
        phase, log = finished('t6')
        volume = kubectl('-n', NS, 'get', 'pvc', 't6', '-o', 'jsonpath={.spec.volumeName}')
        report(check='t6', step='write', phase=phase, log=log.splitlines(), volume=volume, logical_volumes=logical_volumes(volume))
        start = time.time()
        kubectl('-n', NS, 'delete', 'pod', 't6', '--wait=true')
        kubectl('-n', NS, 'delete', 'pvc', 't6', '--wait=true')
        while logical_volumes(volume) and time.time() - start < 180:
            time.sleep(2)
        left = logical_volumes(volume)
        pv_left = bool(kubectl('get', 'pv', volume, '--ignore-not-found', '-o', 'name').strip())
        report(check='t6', step='delete', seconds=round(time.time() - start, 1), logical_volumes_left=left, pv_left=pv_left)
        if phase != 'Succeeded' or not checksum(log) or left or pv_left:
            raise SystemExit(1)
    finally:
        kubectl('delete', 'namespace', NS, '--wait=true')


def t8(node):
    kubectl('create', 'namespace', NS)
    try:
        kubectl('apply', '-f', '-', input=json.dumps(claim('t8', node)))
        writer = 'dmesg | head -1; head -c 8388608 /dev/urandom > /data/upload && sync && sha256sum /data/upload'
        kubectl('apply', '-f', '-', input=json.dumps(pod('website', node, 'gvisor', writer, 't8')))
        phase, log = finished('website')
        report(check='t8', pod='website', runtime='gvisor', phase=phase, log=log.splitlines())
        expected = checksum(log)
        ok = phase == 'Succeeded' and expected is not None
        reader = 'uname -r; sha256sum /data/upload'
        for name in ('worker-1', 'worker-2'):
            kubectl('apply', '-f', '-', input=json.dumps(pod(name, node, 'kata', reader + ' && sleep 20', 't8')))
        for name in ('worker-1', 'worker-2'):
            phase, log = finished(name)
            report(check='t8', pod=name, runtime='kata', phase=phase, log=log.splitlines())
            ok &= phase == 'Succeeded' and checksum(log) == expected
        if not ok:
            raise SystemExit(1)
    finally:
        kubectl('delete', 'namespace', NS, '--wait=true')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('t1', 't5', 't6', 't8'):
        raise SystemExit(__doc__)
    globals()[sys.argv[1]](sys.argv[2])


if __name__ == '__main__':
    main()
