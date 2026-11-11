#!/usr/bin/env python3
"""Sample the memory, CPU and OOM counters of every pod and container on the host, once each second.

Run it on the k3s host as root (it reads the pod cgroups). It writes one JSON line per second to the output file:
{"t": epoch, "host": {...}, "pods": {"<pod uid>": {"mem": bytes, "swap": bytes, "cpu": usec, "max": bytes or null,
"oom_kill": n, "oom": n, "high": n, "c": {"<container id>": {"mem": .., "cpu": .., "oom_kill": ..}}}}}
Each minute it also writes {"t": epoch, "map": {...}} with the pod uid to namespace/name and the container id to name map,
from `kubectl get pods -A -o json`. KUBECONFIG must name the cluster. The sampler stops at SIGTERM or after --seconds.
Usage: sampler.py <output.jsonl> [--seconds N]
"""
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time

# The kubelet uses the systemd cgroup driver, so the pods are below kubepods.slice.
ROOT = '/sys/fs/cgroup/kubepods.slice'
POD_RE = re.compile(r'pod([0-9a-f_]{36})\.slice$')
CTR_RE = re.compile(r'cri-containerd-([0-9a-f]{64})\.scope$')
running = True


def stop(*_):
    global running
    running = False


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def number(path):
    text = read(path)
    if text is None:
        return None
    text = text.strip()
    return None if text == 'max' else int(text)


def keyed(path):
    text = read(path) or ''
    return dict((k, int(v)) for k, v in (line.split() for line in text.splitlines() if line))


def cgroup(path):
    events = keyed(path + '/memory.events')
    return {'mem': number(path + '/memory.current'), 'swap': number(path + '/memory.swap.current'),
            'cpu': keyed(path + '/cpu.stat').get('usage_usec'), 'max': number(path + '/memory.max'),
            'oom_kill': events.get('oom_kill', 0), 'oom': events.get('oom', 0), 'high': events.get('high', 0)}


def pod_dirs():
    # Guaranteed pods sit directly under the kubepods slice. Burstable and best-effort pods sit one level lower.
    return glob.glob(ROOT + '/*pod*.slice') + glob.glob(ROOT + '/*/*pod*.slice')


def host():
    info = keyed_meminfo()
    load = (read('/proc/loadavg') or '').split()
    return {'avail': info.get('MemAvailable'), 'swapfree': info.get('SwapFree'), 'load1': float(load[0]) if load else None,
            'slice': number(ROOT + '/memory.current'),
            'cpu': keyed(ROOT + '/cpu.stat').get('usage_usec')}


def keyed_meminfo():
    out = {}
    for line in (read('/proc/meminfo') or '').splitlines():
        name, value = line.split(':', 1)
        out[name] = int(value.split()[0]) * 1024
    return out


def pod_map():
    try:
        data = json.loads(subprocess.run(['kubectl', 'get', 'pods', '-A', '-o', 'json'], capture_output=True, text=True,
                                         timeout=30, check=True).stdout)
    except Exception as error:  # A failed list keeps the previous map.
        return {'error': str(error)[:200]}
    pods, containers = {}, {}
    for item in data['items']:
        meta, status = item['metadata'], item.get('status', {})
        pods[meta['uid'].replace('-', '_')] = {'ns': meta['namespace'], 'name': meta['name'],
                                               'runtime': item['spec'].get('runtimeClassName')}
        for c in status.get('containerStatuses', []) + status.get('initContainerStatuses', []):
            cid = (c.get('containerID') or '').split('//')[-1]
            if cid:
                last = (c.get('lastState') or {}).get('terminated') or {}
                containers[cid] = {'name': c['name'], 'restarts': c.get('restartCount', 0), 'last_reason': last.get('reason'),
                                   'pod': meta['uid'].replace('-', '_')}
    return {'pods': pods, 'containers': containers}


def main():
    out_path = sys.argv[1]
    seconds = int(sys.argv[sys.argv.index('--seconds') + 1]) if '--seconds' in sys.argv else 7200
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    end = time.time() + seconds
    next_map = 0
    with open(out_path, 'a', buffering=1) as out:
        while running and time.time() < end:
            tick = time.time()
            if tick >= next_map:
                out.write(json.dumps({'t': round(tick, 2), 'map': pod_map()}, separators=(',', ':')) + '\n')
                next_map = tick + 60
            pods = {}
            for path in pod_dirs():
                match = POD_RE.search(path)
                if not match:
                    continue
                entry = cgroup(path)
                entry['c'] = {}
                for scope in glob.glob(path + '/cri-containerd-*.scope'):
                    cmatch = CTR_RE.search(scope)
                    if cmatch:
                        c = cgroup(scope)
                        entry['c'][cmatch.group(1)[:16]] = {'mem': c['mem'], 'cpu': c['cpu'], 'oom_kill': c['oom_kill'], 'max': c['max']}
                pods[match.group(1)] = entry
            out.write(json.dumps({'t': round(tick, 2), 'host': host(), 'pods': pods}, separators=(',', ':')) + '\n')
            time.sleep(max(0.0, 1.0 - (time.time() - tick)))


if __name__ == '__main__':
    main()
