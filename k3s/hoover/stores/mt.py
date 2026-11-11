#!/usr/bin/env python3
"""Run SQL from stdin in a Manticore daemon of a zone as admin or the zone user. Passwords stay in the pod environment.
MT_POD names the pod, manticore-kata-0 (the default) or manticore-vectors-kata-0.
Usage: mt.py <admin|zone>
"""
import os, subprocess, sys
import common

# KATA_NS names the zone namespace of the store.
NS = os.environ['KATA_NS']

POD = os.environ.get('MT_POD', 'manticore-kata-0')
USERS = {'admin': ('hoover_admin', '"$MT_ADMIN_PASSWORD"'), 'zone': (NS.replace('-', '_'), '"$MT_ZONE_PASSWORD"')}


def run(who, sql, check=True, quiet=False):
    user, password = USERS[who]
    r = subprocess.run(common.K + ['-n', NS, 'exec', '-i', POD, '-c', 'manticore', '--', 'sh', '-c',
                                   f'mysql -h0 -P9306 -u{user} -p{password} --batch --skip-column-names' + (' >/dev/null' if quiet else '')],
                       input=sql, capture_output=True, text=True, timeout=3600)
    err = '\n'.join(l for l in r.stderr.splitlines() if 'Using a password' not in l)
    if check and r.returncode:
        raise RuntimeError(err[-600:])
    r.stderr = err
    return r


if __name__ == '__main__':
    r = run(sys.argv[1], sys.stdin.read(), check=False)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    sys.exit(r.returncode)
