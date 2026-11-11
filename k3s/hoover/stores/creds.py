#!/usr/bin/env python3
"""Create the credentials Secret of the Hoover stores of a zone, and add its missing keys. The values are random and
the script never prints them.

Keys: clickhouse-admin, clickhouse-zone, manticore-admin, manticore-zone, garage-rpc-secret (32 bytes hex),
garage-admin-token, and clickhouse-<service> and manticore-<service> for each service of service_users.py.
manticore-seed is the auth.json of a new Manticore daemon. It holds the user hoover_admin with the password
manticore-admin, so a new daemon has no published default user.
The zone user of ClickHouse and Manticore has the name of the zone prefix, for example zone_a. The operator tools
ch.py and mt.py use it. No Hoover service uses it.
A present key keeps its value.
Usage: creds.py <zone>
"""
import base64, hashlib, json, secrets, sys
import common, service_users

NAME = 'hoover-stores'
NS = sys.argv[1]
KEYS = ['clickhouse-admin', 'clickhouse-zone', 'manticore-admin', 'manticore-zone', 'garage-admin-token']
KEYS += [f'clickhouse-{s}' for s in service_users.using('clickhouse')]
KEYS += [f'manticore-{s}' for s in service_users.using('manticore')]
ADMIN_ACTIONS = ('read', 'write', 'schema', 'replication', 'admin', 'backup')


def manticore_seed(password):
    """The auth.json of Manticore 29 with one user. Manticore keeps sha1(password) and sha256(salt bytes + password)."""
    salt = secrets.token_hex(20)
    hashes = {'password_sha1_no_salt': hashlib.sha1(password.encode()).hexdigest(),
              'password_sha256': hashlib.sha256(bytes.fromhex(salt) + password.encode()).hexdigest(), 'bearer_sha256': ''}
    return json.dumps({'version': 2, 'users': [{'username': 'hoover_admin', 'salt': salt, 'hashes': hashes}],
                       'permissions': [{'username': 'hoover_admin', 'action': a, 'target': '*', 'allow': True} for a in ADMIN_ACTIONS]})


found = common.kubectl('-n', NS, 'get', 'secret', NAME, '--ignore-not-found', '-o', 'json').strip()
current = {k: base64.b64decode(v).decode() for k, v in json.loads(found).get('data', {}).items()} if found else {}
data = {**{k: secrets.token_hex(24) for k in KEYS}, 'garage-rpc-secret': secrets.token_hex(32), **current}
data.setdefault('manticore-seed', manticore_seed(data['manticore-admin']))
if data != current:
    common.apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': NAME, 'namespace': NS, 'labels': {common.LABEL: 'credentials'}},
                  'type': 'Opaque', 'stringData': data})
    print('created' if not current else f'added {len(data) - len(current)} keys')
else:
    print('exists')
