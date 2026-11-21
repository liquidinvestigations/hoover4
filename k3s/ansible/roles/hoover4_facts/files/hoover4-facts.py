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
memory        total_bytes of /proc/meminfo, swap_devices [{name, size_bytes, used_bytes}] of /proc/swaps, zswap
              {enabled, compressor, max_pool_percent, shrinker_enabled}, huge_pages (the selected mode of
              transparent_hugepage/enabled), page_cluster, and oom_daemons (the active units of OOM_DAEMONS). A value
              that the script cannot read is empty.
The CPU speed and the disk speeds are no facts: the role hoover4_speed measures them once, on a node at rest.
The script runs with Python 3.9, the version of RHEL 9.
"""
import json
import os
import platform
import shutil
import subprocess

# The k3s data volumes that the role hoover4_host creates in k3s_volume_group.
K3S_VOLUMES = ('rancher', 'kubelet')
# The user space OOM daemons. Each can stop k3s and the stores when the memory of the host is low.
OOM_DAEMONS = ('systemd-oomd', 'earlyoom', 'nohang', 'nohang-desktop')


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


def addresses():
    code, out = run(['ip', '-o', '-4', 'addr', 'show', 'scope', 'global'])
    found = {}
    for line in out.splitlines() if not code else []:
        fields = line.split()
        if len(fields) > 3 and fields[2] == 'inet':
            found[fields[3].split('/')[0]] = fields[1]
    return found


def read_text(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ''


def memory():
    total = ''
    for line in read_text('/proc/meminfo').splitlines():
        if line.startswith('MemTotal:'):
            total = int(line.split()[1]) * 1024
    swaps = []
    for line in read_text('/proc/swaps').splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 4 and fields[2].isdigit() and fields[3].isdigit():
            swaps.append({'name': fields[0], 'size_bytes': int(fields[2]) * 1024, 'used_bytes': int(fields[3]) * 1024})
    zswap = {k: read_text('/sys/module/zswap/parameters/' + k)
             for k in ('enabled', 'compressor', 'max_pool_percent', 'shrinker_enabled')}
    mode = read_text('/sys/kernel/mm/transparent_hugepage/enabled')
    huge = mode[mode.index('[') + 1:mode.index(']')] if '[' in mode and ']' in mode else ''
    daemons = [name for name in OOM_DAEMONS if run(['systemctl', 'is-active', name])[1].strip() == 'active']
    return {'total_bytes': total, 'swap_devices': swaps, 'zswap': zswap, 'huge_pages': huge,
            'page_cluster': read_text('/proc/sys/vm/page-cluster'), 'oom_daemons': daemons}


if __name__ == '__main__':
    print(json.dumps({'architecture': platform.machine(), 'avx2': avx2(), 'gpus': gpus(),
                      'nvidia_container_runtime': bool(shutil.which('nvidia-container-runtime')),
                      'volume_groups': volume_groups(), 'addresses': addresses(), 'memory': memory(),
                      'root': os.geteuid() == 0},
                     sort_keys=True))
