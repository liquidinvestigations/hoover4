#!/usr/bin/env python3
"""Run SQL from stdin in the shared ClickHouse of the site as admin or as the zone user of a zone.

The admin password stays in the pod environment. The zone password comes from the Secret hoover-stores of the zone
namespace and goes to the client through stdin, so no password is on a command line.
Usage: KATA_NS=<zone> ch.py <admin|zone> [database] [extra clickhouse-client arguments]
"""
import base64, os, sys
import common, shared
import podexec  # noqa: E402  (common puts the k3s folder on the path)

# KATA_NS names the zone.
NS = os.environ['KATA_NS']


def run(who, sql, database=None, extra=(), check=True):
    args = '--multiquery' + (f' --database {database}' if database else '') + ''.join(f' {a}' for a in extra)
    if who == 'admin':
        command, text = f'exec clickhouse-client --user hoover_admin --password "$CH_ADMIN_PASSWORD" {args}', sql
    else:
        found = common.kubectl('-n', NS, 'get', 'secret', 'hoover-stores', '-o', 'jsonpath={.data.clickhouse-zone}')
        password = base64.b64decode(found).decode()
        command = f'read -r P; exec clickhouse-client --user {NS.replace("-", "_")} --password "$P" {args}'
        text = password + '\n' + sql
    # The standard input stays open until the client ends (../../podexec.py), because the output of the Kata pod stops
    # after 32 KiB once kubectl closes it.
    r = podexec.call(common.K + ['-n', shared.NS, 'exec', '-i', shared.ready_pod('clickhouse'), '-c', 'clickhouse'],
                     ['sh', '-c', command], text, timeout=3600)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip()[-600:])
    return r


if __name__ == '__main__':
    r = run(sys.argv[1], sys.stdin.read(), sys.argv[2] if len(sys.argv) > 2 else None, sys.argv[3:], check=False)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr[-1500:])
    sys.exit(r.returncode)
