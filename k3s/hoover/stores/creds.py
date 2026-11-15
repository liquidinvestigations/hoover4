#!/usr/bin/env python3
"""Create the credentials Secret hoover-stores of a zone, and add its missing keys. The values are random and the
script never prints them.

Keys: clickhouse-zone and clickhouse-<service> for each ClickHouse service of service_users.py, manticore-read,
manticore-write and manticore-schema for the three Manticore users of the zone, and manticore-proxy-token, the
credential of the zone services at the schema proxy of the zone (../manifests.py).
The zone user of ClickHouse has the name of the zone prefix, for example zone_a. The operator tool ch.py uses it. No
Hoover service uses it.
The admin of the shared ClickHouse, the admin of the shared Manticore and the Garage secrets are in the Secret
hoover-stores of the namespace hoover-stores (shared.py).
A present key keeps its value.
Usage: creds.py <zone>
"""
import base64, hashlib, json, secrets, sys
import common, service_users

NAME = 'hoover-stores'
NS = sys.argv[1] if __name__ == '__main__' else None
KEYS = ['clickhouse-zone', 'manticore-proxy-token']
KEYS += [f'clickhouse-{s}' for s in service_users.using('clickhouse')]
KEYS += [f'manticore-{role}' for role in service_users.MANTICORE_ROLES]
ADMIN_ACTIONS = ('read', 'write', 'schema', 'replication', 'admin', 'backup')


def manticore_seed(password):
    """The auth.json of Manticore 29 with one user. Manticore keeps sha1(password) and sha256(salt bytes + password)."""
    salt = secrets.token_hex(20)
    hashes = {'password_sha1_no_salt': hashlib.sha1(password.encode()).hexdigest(),
              'password_sha256': hashlib.sha256(bytes.fromhex(salt) + password.encode()).hexdigest(), 'bearer_sha256': ''}
    return json.dumps({'version': 2, 'users': [{'username': 'hoover_admin', 'salt': salt, 'hashes': hashes}],
                       'permissions': [{'username': 'hoover_admin', 'action': a, 'target': '*', 'allow': True} for a in ADMIN_ACTIONS]})


def main():
    found = common.kubectl('-n', NS, 'get', 'secret', NAME, '--ignore-not-found', '-o', 'json').strip()
    current = {k: base64.b64decode(v).decode() for k, v in json.loads(found).get('data', {}).items()} if found else {}
    data = {**{k: secrets.token_hex(24) for k in KEYS}, **current}
    if data != current:
        common.apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': NAME, 'namespace': NS, 'labels': {common.LABEL: 'credentials'}},
                      'type': 'Opaque', 'stringData': data})
        print('created' if not current else f'added {len(data) - len(current)} keys')
    else:
        print('exists')


if __name__ == '__main__':
    main()
