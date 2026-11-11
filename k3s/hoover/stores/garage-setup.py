#!/usr/bin/env python3
"""Set up the Garage of a zone: a single-node layout and one key for the Hoover of the zone.

The key goes into the Secret garage-tenants as JSON, under the zone name. ../setup.py creates the buckets and gives
the key access to them. The script never prints a key secret. A second run changes nothing.
Usage: KATA_NS=<zone> garage-setup.py
"""
import json, os, re, subprocess
import common

NS, POD = os.environ['KATA_NS'], 'garage-kata-0'


def garage(*args, check=True):
    r = subprocess.run(common.K + ['-n', NS, 'exec', POD, '-c', 'garage', '--', '/garage', *args], capture_output=True, text=True, timeout=120)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip()[-400:])
    return r.stdout


node = garage('node', 'id', '-q').strip().split('@')[0]
if 'dc1' not in garage('layout', 'show'):
    garage('layout', 'assign', '-z', 'dc1', '-c', '20G', node[:16])
    garage('layout', 'apply', '--version', '1')
    common.log('garage.jsonl', step='layout', zone=NS, node=node[:16])
if NS not in garage('key', 'list'):
    out = garage('key', 'create', NS)
    keys = {NS: {'access_key': re.search(r'Key ID:\s+(\S+)', out).group(1), 'secret_key': re.search(r'Secret key:\s+(\S+)', out).group(1)}}
    common.apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'garage-tenants', 'namespace': NS, 'labels': {common.LABEL: 'credentials'}},
                  'type': 'Opaque', 'stringData': {'tenants.json': json.dumps(keys)}})
    common.log('garage.jsonl', step='key', zone=NS)
