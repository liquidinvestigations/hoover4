#!/usr/bin/env python3
"""Set the swap and zswap quota of each pod slice of the kubelet from the memory limit of the pod.

Usage: hoover4-pod-swap SETTINGS [--once | --check]

SETTINGS is a JSON file with swap_percent, zswap_percent, writeback and interval_seconds. Without an option the
script repeats a pass every interval_seconds. --once runs one pass. --check changes nothing, prints each slice that
differs, and exits with 1 when one differs.

One pass sets MemoryZSwapWriteback of kubepods.slice, which applies to every pod below it. Then it gives each pod
slice the swap quota swap_percent and the zswap quota zswap_percent of its memory.max. A pod without a memory limit
gets the quotas 0. systemd owns the pod slices and writes its own values again, so the script writes the cgroup files
only through systemctl set-property --runtime. The runc containers keep the kubelet value NoSwap in their own scopes.
The script needs root and runs with Python 3.9.
"""
import glob
import json
import os
import subprocess
import sys
import time

CGROUP = '/sys/fs/cgroup/kubepods.slice'
CONTROL = '/run/systemd/system.control'
PAGE = 4096


def wanted(limit_text, settings):
    """(swap bytes, zswap bytes) for the memory.max text of a pod slice."""
    if limit_text.strip() == 'max':
        return 0, 0
    limit = int(limit_text)
    return (limit * settings['swap_percent'] // 100 // PAGE * PAGE,
            limit * settings['zswap_percent'] // 100 // PAGE * PAGE)


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def number(text):
    return 0 if text in (None, 'max') else int(text)


def writeback_word(on):
    return 'yes' if on else 'no'


def pod_slices():
    found = glob.glob(os.path.join(CGROUP, 'kubepods-*pod*.slice'))
    found += glob.glob(os.path.join(CGROUP, 'kubepods-*.slice', 'kubepods-*pod*.slice'))
    return sorted(found)


def differences(settings):
    """[(unit, cgroup path, properties, row)] for kubepods.slice and each pod slice whose values differ from the
    wanted values."""
    out = []
    writeback = '1' if settings['writeback'] else '0'
    if read(os.path.join(CGROUP, 'memory.zswap.writeback')) not in (None, writeback):
        out.append(('kubepods.slice', CGROUP, [f'MemoryZSwapWriteback={writeback_word(settings["writeback"])}'],
                    {'slice': 'kubepods.slice', 'writeback': settings['writeback']}))
    for path in pod_slices():
        limit = read(os.path.join(path, 'memory.max'))
        if limit is None:
            continue
        swap, zswap = wanted(limit, settings)
        have = (read(os.path.join(path, 'memory.swap.max')), read(os.path.join(path, 'memory.zswap.max')),
                read(os.path.join(path, 'memory.zswap.writeback')))
        if None in have:
            continue
        if (number(have[0]), number(have[1]), have[2]) != (swap, zswap, writeback) or 'max' in have[:2]:
            unit = os.path.basename(path)
            out.append((unit, path, [f'MemorySwapMax={swap}', f'MemoryZSwapMax={zswap}',
                               f'MemoryZSwapWriteback={writeback_word(settings["writeback"])}'],
                        {'slice': unit, 'limit': limit, 'swap': swap, 'zswap': zswap, 'writeback': settings['writeback']}))
    return out


def remove_stale_dropins():
    """Remove the runtime drop-in folders of the pod slices that no longer exist."""
    present = {os.path.basename(p) for p in pod_slices()}
    for folder in glob.glob(os.path.join(CONTROL, 'kubepods-*pod*.slice.d')):
        if os.path.basename(folder)[:-2] not in present:
            for name in os.listdir(folder):
                try:
                    os.unlink(os.path.join(folder, name))
                except OSError:
                    pass
            try:
                os.rmdir(folder)
            except OSError:
                pass


def apply(settings):
    for unit, path, properties, row in differences(settings):
        result = subprocess.run(['systemctl', 'set-property', '--runtime', unit, *properties],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # A pod that stopped between the read and the command is no error.
        if result.returncode:
            if os.path.isdir(path):
                print(json.dumps({'slice': unit, 'error': result.stderr.strip()}), flush=True)
            continue
        print(json.dumps(row), flush=True)
    remove_stale_dropins()


def main(argv):
    if not argv or argv[0].startswith('-'):
        raise SystemExit(__doc__)
    with open(argv[0]) as f:
        settings = json.load(f)
    if '--check' in argv:
        rows = [row for _, _, _, row in differences(settings)]
        for row in rows:
            print(json.dumps(row))
        return 1 if rows else 0
    if '--once' in argv:
        apply(settings)
        return 0
    while True:
        apply(settings)
        time.sleep(settings.get('interval_seconds', 15))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
