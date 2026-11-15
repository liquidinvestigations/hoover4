#!/usr/bin/env python3
"""Print the host facts of a hoover4 node as JSON. It reads files and commands and changes nothing.

architecture  the output of uname -m
avx2          true when the flags line of /proc/cpuinfo names avx2
gpus          [{name, memory_mib}] from nvidia-smi, or [] without a working NVIDIA driver
nvidia_container_runtime  true when the NVIDIA container toolkit is installed
volume_groups {name: {size_bytes, free_bytes, k3s_volumes_bytes}} from vgs and lvs. k3s_volumes_bytes is the size of
              the logical volumes rancher and kubelet of the group, the k3s data volumes of k3s_volume_group. It needs
              root, so the play runs it with become.
addresses     {IPv4 address: interface} of every global address of the host
cpu_speed     the work that one thread of the node does in one CPU second while every thread works, the geometric mean
              of a zlib compression and a Python integer loop, each run for PROBE_SECONDS on all threads at once. The
              hashing extensions of a CPU do not change it. ../../../../config.py compares it between the nodes.
The script runs with Python 3.9, the version of RHEL 9.
"""
import json
import multiprocessing
import os
import platform
import shutil
import subprocess
import time
import zlib

# The k3s data volumes that the role hoover4_host creates in k3s_volume_group.
K3S_VOLUMES = ('rancher', 'kubelet')


def run(argv):
    if not shutil.which(argv[0]):
        return 127, ''
    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return proc.returncode, proc.stdout


def avx2():
    try:
        with open('/proc/cpuinfo') as f:
            for line in f:
                if line.startswith('flags'):
                    return 'avx2' in line.split(':', 1)[1].split()
    except OSError:
        pass
    return False


def gpus():
    code, out = run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'])
    if code:
        return []
    found = []
    for line in out.splitlines():
        name, _, memory = line.rpartition(',')
        if name.strip():
            found.append({'name': name.strip(), 'memory_mib': int(memory.strip()) if memory.strip().isdigit() else 0})
    return found


def volume_groups():
    code, out = run(['vgs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'vg_name,vg_size,vg_free'])
    if code:
        return {}
    try:
        rows = json.loads(out)['report'][0]['vg']
    except (ValueError, KeyError, IndexError):
        return {}
    groups = {r['vg_name']: {'size_bytes': int(r['vg_size']), 'free_bytes': int(r['vg_free']), 'k3s_volumes_bytes': 0}
              for r in rows}
    code, out = run(['lvs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'vg_name,lv_name,lv_size'])
    try:
        volumes = json.loads(out)['report'][0]['lv'] if not code else []
    except (ValueError, KeyError, IndexError):
        volumes = []
    for row in volumes:
        if row.get('lv_name') in K3S_VOLUMES and row.get('vg_name') in groups:
            groups[row['vg_name']]['k3s_volumes_bytes'] += int(row['lv_size'])
    return groups


# The seconds of each probe of cpu_speed(). The two probes take about one second.
PROBE_SECONDS = 0.5
PROBE_DATA = bytes((i * 7919 + (i >> 3)) % 251 for i in range(65536))


def probe_work(kind):
    if kind == 'zlib':
        zlib.compress(PROBE_DATA, 6)
        return
    x = 0
    for i in range(2000):
        x = (x * 31 + i) % 1000003


def probe_worker(kind, queue):
    count, end = 0, time.monotonic() + PROBE_SECONDS
    start = time.process_time()
    while time.monotonic() < end:
        probe_work(kind)
        count += 1
    queue.put(count / max(time.process_time() - start, 1e-3))


def probe_rate(kind):
    """The mean work per CPU second of one thread while every thread of the node runs the probe."""
    # fork starts the workers without a new import of this file, which Ansible runs from a temporary path.
    context = multiprocessing.get_context('fork')
    queue = context.Queue()
    workers = [context.Process(target=probe_worker, args=(kind, queue)) for _ in range(os.cpu_count() or 1)]
    for w in workers:
        w.start()
    rates = [queue.get() for _ in workers]
    for w in workers:
        w.join()
    return sum(rates) / len(rates)


def cpu_speed():
    return round((probe_rate('zlib') * probe_rate('loop')) ** 0.5)


def addresses():
    code, out = run(['ip', '-o', '-4', 'addr', 'show', 'scope', 'global'])
    found = {}
    for line in out.splitlines() if not code else []:
        fields = line.split()
        if len(fields) > 3 and fields[2] == 'inet':
            found[fields[3].split('/')[0]] = fields[1]
    return found


if __name__ == '__main__':
    print(json.dumps({'architecture': platform.machine(), 'avx2': avx2(), 'gpus': gpus(),
                      'nvidia_container_runtime': bool(shutil.which('nvidia-container-runtime')),
                      'volume_groups': volume_groups(), 'addresses': addresses(), 'root': os.geteuid() == 0,
                      'cpu_speed': cpu_speed()}, sort_keys=True))
