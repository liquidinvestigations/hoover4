#!/usr/bin/env python3
"""Measure the CPU speed and the write speed of the storage tiers of a hoover4 node, and print them as JSON.

Usage: hoover4-speed.py '{"tier": "volume group", ...}'   (as root)

The script measures only on a node at rest. It refuses, and prints {"refused": reason}, when k3s runs, when a
container runs (a containerd shim or a conmon process), or when the 1-minute load of the node is above MAX_LOAD.
Other work on the node lowers the result, so a value of a busy node does not compare with the other nodes.

threads    the threads of the node (os.cpu_count())
cpu_speed  the work that one thread of the node does in one CPU second while every thread works, the geometric mean
           of a zlib compression and a Python integer loop, each run for PROBE_SECONDS on all threads at once. The
           hashing extensions of a CPU do not change it. ../../../../config.py compares it between the nodes.
disks      {tier: {volume_group, write_mib_s}}: the speed of one write of WRITE_BYTES with direct I/O into a new
           logical volume of the volume group of the tier. The script deletes the volume after the write. A tier
           without the free space or without the volume group has {volume_group, error} instead.
The script runs with Python 3.9, the version of RHEL 9.
"""
import json
import mmap
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
import zlib

# The refusal limit of the 1-minute load.
MAX_LOAD = 5.0
# The seconds of each probe of cpu_speed(). The two probes take about one second.
PROBE_SECONDS = 0.5
PROBE_DATA = bytes((i * 7919 + (i >> 3)) % 251 for i in range(65536))
# The test volume of the write probe.
TEST_VOLUME = 'hoover4-speed-test'
WRITE_BYTES = 1 << 30
BLOCK = 4 << 20
# Process names of a running container: the shims of containerd (k3s, Docker) and conmon (Podman).
CONTAINER_PROCESSES = ('containerd-shim', 'conmon')
K3S_UNITS = ('k3s', 'k3s-agent')


def run(argv):
    if not shutil.which(argv[0]):
        return 127, ''
    proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    return proc.returncode, proc.stdout


def process_names():
    names = []
    for pid in os.listdir('/proc'):
        if pid.isdigit():
            try:
                with open(f'/proc/{pid}/comm') as f:
                    names.append(f.read().strip())
            except OSError:
                pass
    return names


def load():
    with open('/proc/loadavg') as f:
        return float(f.read().split()[0])


def refusal(names=None, units=None, load_now=None):
    """The reason why the node is not at rest, or ''."""
    names = process_names() if names is None else names
    units = [u for u in K3S_UNITS if run(['systemctl', 'is-active', u])[1].strip() == 'active'] if units is None else units
    if units or any(n.startswith('k3s') for n in names):
        return f'k3s runs ({", ".join(units) or "a k3s process"}). Stop k3s and its containers first.'
    found = sorted({n for n in names if n.startswith(CONTAINER_PROCESSES)})
    if found:
        return f'a container runs ({", ".join(found)} processes). Stop every container on the node first.'
    load_now = load() if load_now is None else load_now
    if load_now > MAX_LOAD:
        return f'the 1-minute load is {load_now:.2f}, above {MAX_LOAD:g}. Wait until the node is at rest.'
    return ''


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


def write_speed(group, size=WRITE_BYTES):
    """{volume_group, write_mib_s} of one direct write of size bytes into a new volume of group, or {volume_group, error}."""
    out = {'volume_group': group}
    volume = f'{group}/{TEST_VOLUME}'
    # A volume of an interrupted earlier run goes first.
    if run(['lvs', volume])[0] == 0:
        run(['lvremove', '-y', volume])
    code, text = run(['lvcreate', '-y', '-Wn', '-Zn', '-L', f'{size}b', '-n', TEST_VOLUME, group])
    if code:
        out['error'] = f'lvcreate failed: {text.strip()[-300:]}'
        return out
    try:
        buffer = mmap.mmap(-1, BLOCK)
        buffer.write(os.urandom(BLOCK))
        fd = os.open(f'/dev/{volume}', os.O_WRONLY | os.O_DIRECT)
        try:
            start = time.monotonic()
            written = 0
            while written < size:
                written += os.write(fd, buffer)
            os.fsync(fd)
            seconds = time.monotonic() - start
        finally:
            os.close(fd)
        out['write_mib_s'] = round(size / 2 ** 20 / seconds)
    except OSError as error:
        out['error'] = f'the write failed: {error}'
    finally:
        code, text = run(['lvremove', '-y', volume])
        if code:
            out['error'] = f'lvremove {volume} failed: {text.strip()[-300:]}'
    return out


def main(argv):
    tiers = json.loads(argv[1]) if len(argv) > 1 else {}
    reason = refusal()
    if reason:
        return {'refused': reason}
    return {'measured': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'threads': os.cpu_count(),
            'load': load(), 'cpu_speed': cpu_speed(),
            'disks': {tier: write_speed(group) for tier, group in sorted(tiers.items())}}


if __name__ == '__main__':
    print(json.dumps(main(sys.argv), sort_keys=True))
