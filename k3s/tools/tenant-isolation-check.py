#!/usr/bin/env python3
"""Check that a zone cannot read or write the data of another zone in the shared stores of the site.

The probe runs Python in the operations pod of hoover-<zone>, with the ClickHouse user and the Garage key of that pod.
- ClickHouse: the user reads its own database <prefix>_Processing. It cannot read, write or drop a table of
  <other prefix>_Processing, create a database with the other prefix, or list the other databases.
- Garage: the key lists its own system bucket. It cannot list, read or write the system bucket of the other zone, and
  the bucket list holds no bucket of the other zone.
- Manticore: the daemons of the other zone are in its zone namespace, and the network policies refuse the connection.
- Garage bucket names: a key that can create buckets can create a bucket with the name prefix of another zone. Garage
  gives such a bucket a local alias of the creating key, so the names of the other zone stay free. The case reports
  the result without a pass or fail, and the probe deletes the bucket at once.
Each line of the output is JSON. The check prints no credential. It exits with 1 when a case has another result than
expected.
Usage: tenant-isolation-check.py <zone> <other zone>
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

K = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG)]
PYTHON = '/opt/pysetup/.venv/bin/python3'
PROBE = r'''
import json, os, socket, sys, urllib.request, urllib.error
from minio import Minio
zone, other = sys.argv[1], sys.argv[2]
mine, theirs = zone.replace('-', '_') + '_Processing', other.replace('-', '_') + '_Processing'
def ch(sql):
    req = urllib.request.Request(os.environ['CLICKHOUSE_URL'] + '/', data=sql.encode(), headers={
        'X-ClickHouse-User': os.environ['CLICKHOUSE_USER'], 'X-ClickHouse-Key': os.environ['CLICKHOUSE_PASSWORD']})
    try:
        return 'allowed', urllib.request.urlopen(req, timeout=20).read().decode().strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return ('refused' if 'ACCESS_DENIED' in body or 'Not enough privileges' in body else 'error'), body[:160]
def s3(call):
    try:
        return 'allowed', str(call())[:160]
    except Exception as e:
        code = getattr(e, 'code', type(e).__name__)
        return ('refused' if code in ('AccessDenied', 'NoSuchBucket', 'Forbidden') else 'error'), str(code)
def tcp(host, port):
    try:
        socket.create_connection((host, port), 5).close()
        return 'allowed', 'open'
    except Exception as e:
        return 'refused', type(e).__name__
client = Minio(os.environ['S3_ENDPOINT'].split('://')[-1], os.environ['S3_ACCESS_KEY'], os.environ['S3_SECRET_KEY'], secure=False)
cases = [
    ('clickhouse', 'own database', 'allowed', ch(f'SELECT count() FROM {mine}.collections')),
    ('clickhouse', 'read other database', 'refused', ch(f'SELECT count() FROM {theirs}.collections')),
    ('clickhouse', 'write other database', 'refused', ch(f"INSERT INTO {theirs}.server_settings (key, value) VALUES ('p4', 'x')")),
    ('clickhouse', 'drop other table', 'refused', ch(f'DROP TABLE {theirs}.server_settings')),
    ('clickhouse', 'create database with other prefix', 'refused', ch(f"CREATE DATABASE {other.replace('-', '_')}_probe")),
    ('clickhouse', 'system log of other users', 'refused', ch('SELECT count() FROM system.query_log')),
    ('clickhouse', 'list other databases', 'allowed',
     ('allowed' if other.replace('-', '_') not in ch('SHOW DATABASES')[1] else 'refused', 'listed only own databases')),
    ('garage', 'own system bucket', 'allowed', s3(lambda: len(list(client.list_objects(f'{zone}-system'))))),
    ('garage', 'list other system bucket', 'refused', s3(lambda: len(list(client.list_objects(f'{other}-system'))))),
    ('garage', 'write other system bucket', 'refused',
     s3(lambda: client.put_object(f'{other}-system', 'p4-probe', __import__('io').BytesIO(b'x'), 1))),
    ('garage', 'read other object', 'refused', s3(lambda: client.get_object(f'{other}-system', 'p4-probe').read())),
    ('garage', 'bucket list', 'allowed',
     ('allowed' if not any(b.name.startswith(other + '-') for b in client.list_buckets()) else 'refused', 'no bucket of the other zone')),
    ('manticore', 'other zone daemon', 'refused', tcp(f'manticore.{other}.svc.cluster.local', 9306)),
]
name = f'{other}-c-p4probe'
created = s3(lambda: client.make_bucket(name))
if created[0] == 'allowed':
    s3(lambda: client.remove_bucket(name))
cases.append(('garage', 'create bucket with other prefix', None, created))
for store, case, expected, (result, detail) in cases:
    print(json.dumps({'store': store, 'case': case, 'expected': expected, 'result': result, 'detail': detail,
                      'pass': None if expected is None else result == expected}))
'''


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    zone, other = sys.argv[1:]
    r = subprocess.run(K + ['-n', f'hoover-{zone}', 'exec', 'deploy/hoover-operations', '--', PYTHON, '-c', PROBE, zone, other],
                       capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise SystemExit(f'the probe failed: {r.stderr.strip()[-600:]}')
    ok = True
    for line in r.stdout.splitlines():
        row = json.loads(line)
        ok &= row['pass'] is not False
        print(json.dumps({'zone': zone, 'other': other, **row}), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
