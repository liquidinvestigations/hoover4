#!/usr/bin/env python3
"""Print the host facts of a hoover4 node as JSON. It reads files and commands and changes nothing.

architecture  the output of uname -m
avx2          true when the flags line of /proc/cpuinfo names avx2
gpus          [{name, memory_mib}] from nvidia-smi, or [] without a working NVIDIA driver
nvidia_container_runtime  true when the NVIDIA container toolkit is installed
volume_groups {name: {size_bytes, free_bytes}} from vgs. It needs root, so the play runs it with become.
The script runs with Python 3.9, the version of RHEL 9.
"""
import json
import os
import platform
import shutil
import subprocess


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
    return {r['vg_name']: {'size_bytes': int(r['vg_size']), 'free_bytes': int(r['vg_free'])} for r in rows}


print(json.dumps({'architecture': platform.machine(), 'avx2': avx2(), 'gpus': gpus(),
                  'nvidia_container_runtime': bool(shutil.which('nvidia-container-runtime')),
                  'volume_groups': volume_groups(), 'root': os.geteuid() == 0}, sort_keys=True))
