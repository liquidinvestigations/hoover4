#!/usr/bin/env python3
"""Run SQL from stdin in the ClickHouse of a zone as admin or as the zone user. The password stays in the pod environment.
Usage: ch.py <admin|zone> [database] [extra clickhouse-client arguments]
"""
import os, subprocess, sys
import common

# KATA_NS names the zone namespace of the store.
NS = os.environ['KATA_NS']

USERS = {'admin': ('hoover_admin', 'CH_ADMIN_PASSWORD'), 'zone': (NS.replace('-', '_'), 'CH_ZONE_PASSWORD')}


def run(who, sql, database=None, extra=(), check=True):
    user, var = USERS[who]
    args = f'--user {user} "--password=${var}" --multiquery' + (f' --database {database}' if database else '') + ''.join(f' {a}' for a in extra)
    r = subprocess.run(common.K + ['-n', NS, 'exec', '-i', 'clickhouse-kata-0', '-c', 'clickhouse', '--', 'sh', '-c',
                                   f'clickhouse-client {args}'], input=sql, capture_output=True, text=True, timeout=3600)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip()[-600:])
    return r


if __name__ == '__main__':
    r = run(sys.argv[1], sys.stdin.read(), sys.argv[2] if len(sys.argv) > 2 else None, sys.argv[3:], check=False)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr[-1500:])
    sys.exit(r.returncode)
