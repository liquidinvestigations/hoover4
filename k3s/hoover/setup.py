#!/usr/bin/env python3
"""Prepare the store tenants and the runtime Secrets for the Hoover of one zone. Each step is idempotent.

ClickHouse, Garage, Manticore and Temporal are shared by the site in the namespace hoover-stores (stores/shared.py,
stores/temporal.py), where each zone is a tenant.
The zone credentials are in the Secrets hoover-stores and garage-tenants of the zone namespace, so they go with the zone.

- ClickHouse: the settings profile <prefix>, which limits the memory of one user to half of the ClickHouse limit, the
  zone user <prefix> and a user for each service (stores/service_users.py), with the passwords of hoover-stores and
  the profile <prefix>. The grants name only the databases <prefix> and <prefix>_*, so a zone user reaches no database
  of another zone. A zone id has no _, so the prefix of one zone never starts the prefix of another.
- Garage: the zone key <zone>, the buckets <zone>-system and <zone>-c-demo with read and write access for the zone key.
  The zone key can create buckets, because Hoover creates the bucket <zone>-c-<collection> of each new collection.
  The services that use the collection buckets share it (stores/service_users.py). Each other Garage service gets its
  own key with read and write access to <zone>-system only. A key reaches only the buckets that it created or that
  this step allows. A bucket that Hoover creates through S3 has a local alias of the zone key, so its name is private
  to the zone. The keys are in the Secret garage-tenants.
- Manticore: the users <prefix>_read, <prefix>_write and <prefix>_schema in both shared daemons of the site, with
  the passwords of hoover-stores and the rights of stores/service_users.py MANTICORE_GRANTS on the tables <prefix>_*
  only. The services that only search get the read user, and the services that write rows get the write user and the
  proxy credential. Neither user can create, alter or drop a table. The Secret manticore-schema of the Hoover
  namespace holds the schema user and the proxy credential, and only the schema proxy of the zone mounts it.
- Temporal: the namespace <zone> with the retention of the setting main_services.temporal_retention of the zone, and
  the search attribute CollectionDataset. A present namespace gets the retention again and keeps its workflows.
- Secrets hoover-runtime and oauth2-proxy in namespace hoover-<zone>. hoover-runtime holds the store credentials of
  each service, which follow hoover-stores and garage-tenants, and the Temporal key of the zone (temporal-api-key),
  which follows the signing key of the site. Other existing values stay unchanged. The GPU token follows gpu.token, and
  the shared secrets of the MCP servers and of the browser fetch are random.
The script reads credentials from cluster Secrets and never prints a credential.
An installation with the local store layout (manifests.py) needs only the Secrets: setup.py <zone> local-secrets.
Usage: setup.py <zone> [garage] [clickhouse] [secrets] [temporal] [manticore]    Without steps it runs all of them.
       setup.py <zone> local-secrets
"""
import base64
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402
import gpu  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent / 'stores'))
import service_users  # noqa: E402
import shared  # noqa: E402
import temporal as site_temporal  # noqa: E402
K = ['kubectl', '--kubeconfig', settings.KUBECONFIG]
ZONES = settings.PRIVATE / 'zones/secrets.json'
ZONE = sys.argv[1]
NS = 'hoover-' + ZONE
PREFIX = ZONE.replace('-', '_')
STORES = ZONE


def kubectl(*args, input=None, check=True):
    r = subprocess.run(K + list(args), input=input, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f'kubectl {args[:4]} failed: {r.stderr.strip()[-300:]}')
    return r


def secret(namespace, name):
    r = kubectl('-n', namespace, 'get', 'secret', name, '-o', 'json', check=False)
    if r.returncode:
        return {}
    return {k: base64.b64decode(v).decode() for k, v in json.loads(r.stdout).get('data', {}).items()}


def apply(obj):
    kubectl('apply', '-f', '-', input=json.dumps(obj))


def ensure_secret(name, wanted, follow=(), drop=()):
    """Create the Secret, or add only its missing keys. A present key keeps its value, except a key in follow.

    A key in follow always takes the wanted value, because another source owns it, for example the zone client secret.
    A key in drop is removed.
    """
    current = secret(NS, name)
    data = {k: v for k, v in {**wanted, **current, **{k: wanted[k] for k in follow}}.items() if k not in drop}
    if data != {k: v for k, v in current.items() if k not in drop}:
        apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name, 'namespace': NS}, 'type': 'Opaque', 'stringData': data})
    # An apply with stringData keeps the other keys of data, so a dropped key needs a patch.
    removed = [{'op': 'remove', 'path': f'/data/{k}'} for k in drop if k in current]
    if removed:
        kubectl('-n', NS, 'patch', 'secret', name, '--type=json', '-p', json.dumps(removed))
    return data


def temporal(runtime):
    """Create or update the Temporal namespace of the zone in the Temporal of the site (stores/temporal.py)."""
    retention = site_temporal.retention_of(ZONE)
    site_temporal.register(ZONE, retention)
    print(json.dumps({'step': 'temporal', 'namespace': ZONE, 'retention': retention,
                      'key': 'temporal-api-key' in runtime}))


def garage_keys(listed):
    """{key name: key id} of the Garage key list."""
    return {row[2]: row[0] for row in shared.table(listed) if len(row) > 2}


def created_key(out):
    return {'access_key': re.search(r'Key ID:\s+(\S+)', out).group(1), 'secret_key': re.search(r'Secret key:\s+(\S+)', out).group(1)}


def garage():
    run = shared.garage_cli
    tenants = json.loads(secret(STORES, 'garage-tenants').get('tenants.json', '{}'))
    keys = garage_keys(run('key', 'list'))
    # The key secret is in the output of key create only, so the Secret gets it at once.
    wanted = sorted({service_users.garage_key(ZONE, s) for s in service_users.using('garage')} | {ZONE})
    for name in wanted:
        if name not in tenants or name not in keys:
            tenants[name] = created_key(run('key', 'create', name))
            kubectl('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {
                'name': 'garage-tenants', 'namespace': STORES, 'labels': {'hoover.dev/kata-stores': 'credentials'}},
                'type': 'Opaque', 'stringData': {'tenants.json': json.dumps(tenants)}}))
    buckets = {row[2] for row in shared.table(run('bucket', 'list')) if len(row) > 2}
    for bucket in (f'{ZONE}-system', f'{ZONE}-c-demo'):
        if bucket not in buckets:
            run('bucket', 'create', bucket)
        run('bucket', 'allow', '--read', '--write', bucket, '--key', tenants[ZONE]['access_key'])
    run('key', 'allow', '--create-bucket', tenants[ZONE]['access_key'])
    own = [n for n in wanted if n != ZONE]
    for name in own:
        run('bucket', 'allow', '--read', '--write', f'{ZONE}-system', '--key', tenants[name]['access_key'])
    print(json.dumps({'step': 'garage', 'buckets': [f'{ZONE}-system', f'{ZONE}-c-demo'], 'service_keys': own}))


def clickhouse():
    # The statements go through stdin, so no password is on a command line. CREATE USER does nothing for a present
    # user, and ALTER USER then gives it the password of hoover-stores. GRANT adds only missing rights.
    stores = secret(STORES, 'hoover-stores')
    limit = shared.hoover.LIMITS['clickhouse']
    users = {PREFIX: (stores['clickhouse-zone'], service_users.zone_grants(ZONE))}
    for service in service_users.using('clickhouse'):
        users[service_users.user(ZONE, service)] = (stores[f'clickhouse-{service}'], service_users.clickhouse_grants(ZONE, service))
    sql = [f"CREATE SETTINGS PROFILE IF NOT EXISTS `{PREFIX}`;",
           f"ALTER SETTINGS PROFILE `{PREFIX}` SETTINGS INHERIT 'default', "
           f"max_memory_usage_for_user = {int(shared.hoover.gibibytes(limit) * 2 ** 30 / 2)};"]
    for name, (password, grants) in users.items():
        sql += [f"CREATE USER IF NOT EXISTS `{name}` IDENTIFIED WITH sha256_password BY '{password}' SETTINGS PROFILE `{PREFIX}`;",
                f"ALTER USER `{name}` IDENTIFIED WITH sha256_password BY '{password}' SETTINGS PROFILE `{PREFIX}`;"]
        sql += [f'{g} TO `{name}`;' for g in grants]
    shared.clickhouse_sql('\n'.join(sql) + '\n')
    print(json.dumps({'step': 'clickhouse', 'profile': PREFIX, 'users': sorted(users)}))


def manticore():
    """Create the three Manticore users of the zone in both shared daemons, with their rights on <prefix>_* only.

    Manticore 29.9 stops searchd on a GRANT to an unknown user and on a DROP USER of an unknown user, so the step reads
    the users first. A present user gets the password of hoover-stores again. A missing right is granted, and a right
    of a zone user that MANTICORE_GRANTS does not name is revoked.
    """
    stores = secret(STORES, 'hoover-stores')
    target = f'{PREFIX}_*'
    for store in shared.MANTICORE:
        present = shared.manticore_users(store)
        sql = []
        for role in service_users.MANTICORE_ROLES:
            name, password = service_users.manticore_user(ZONE, role), stores[f'manticore-{role}']
            sql.append(f"SET PASSWORD '{password}' FOR '{name}';" if name in present else
                       f"CREATE USER '{name}' IDENTIFIED BY '{password}';")
        shared.manticore_sql(store, '\n'.join(sql) + '\n')
        users = {service_users.manticore_user(ZONE, r): r for r in service_users.MANTICORE_ROLES}
        rights = {(row[0], row[1], row[2]) for row in shared.manticore_rows(shared.manticore_sql(store, 'SHOW PERMISSIONS\n'))
                  if len(row) >= 4 and row[0] in users and row[3] == '1'}
        wanted = {(name, action, target) for name, role in users.items() for action in service_users.MANTICORE_GRANTS[role]}
        sql = [f"GRANT {a} ON '{t}' TO '{u}';" for u, a, t in sorted(wanted - rights)]
        sql += [f"REVOKE {a} ON '{t}' FROM '{u}';" for u, a, t in sorted(rights - wanted)]
        if sql:
            shared.manticore_sql(store, '\n'.join(sql) + '\n')
        print(json.dumps({'step': 'manticore', 'store': store, 'users': sorted(users), 'granted': len(wanted - rights),
                          'revoked': len(rights - wanted)}))


def runtime_secrets():
    stores = secret(STORES, 'hoover-stores')
    tenants = json.loads(secret(STORES, 'garage-tenants').get('tenants.json', '{}'))
    zone_data = json.loads(ZONES.read_text())[ZONE]
    if ZONE not in tenants:
        raise SystemExit(f'garage-tenants has no key for {ZONE}')
    # Each service gets its own store credentials (stores/service_users.py). The Secret no longer holds the shared ones.
    stored = {}
    for service, used in service_users.SERVICES.items():
        if 'clickhouse' in used:
            stored[f'clickhouse-{service}'] = stores[f'clickhouse-{service}']
        if 'manticore' in used:
            role = used['manticore']
            stored[f'manticore-{role}'] = stores[f'manticore-{role}']
            if role == 'write':
                stored['manticore-proxy-token'] = stores['manticore-proxy-token']
        if 'garage' in used:
            key = tenants[service_users.garage_key(ZONE, service)]
            stored[f's3-access-key-{service}'], stored[f's3-secret-key-{service}'] = key['access_key'], key['secret_key']
    runtime = ensure_secret('hoover-runtime', {
        **stored, 'proxy-secret': secrets.token_hex(32), 'temporal-api-key': site_temporal.token(ZONE),
        'gpu-token': gpu.token(ZONE), 'mcp-shared-secret': secrets.token_hex(32), 'browser-fetch-token': secrets.token_hex(32),
        'factcheck-api-key': ''},
        follow=('gpu-token', 'temporal-api-key', *stored),
        drop=('clickhouse-password', 'manticore-password', 's3-access-key', 's3-secret-key', 'temporal-db-password',
              *[f'manticore-{s}' for s in service_users.SERVICES if f'manticore-{s}' not in stored]))
    # Only the schema proxy of the zone mounts this Secret (../manifests.py schema_proxy()).
    ensure_secret('manticore-schema', {'password': stores['manticore-schema'], 'token': stores['manticore-proxy-token']},
                  follow=('password', 'token'))
    ensure_secret('oauth2-proxy', {'client-secret': zone_data['hoover_oidc_secret'], 'cookie-secret': secrets.token_hex(16),
                                   'proxy-secret': runtime['proxy-secret']}, follow=('client-secret',))
    print(json.dumps({'step': 'secrets', 'namespace': NS, 'secrets': ['hoover-runtime', 'oauth2-proxy', 'manticore-schema']}))
    return runtime


# The store credentials of the local store layout (manifests.py LOCAL_CREDENTIALS). The stores of that layout start
# with the Compose values: ClickHouse creates its user from the environment, the Manticore seed file holds its user,
# and garage-init imports the key. An install of the Compose import keeps them, because its copied stores hold them.
COMPOSE_STORE_VALUES = {
    'clickhouse-user': 'hoover4', 'clickhouse-password': 'hoover4', 'manticore-user': 'manticore',
    'manticore-password': 'manticore', 's3-access-key': 'hoover4-blobs-rw', 's3-secret-key': 'hoover4-garage-blob-secret-key-0',
    'garage-rpc-secret': 'cbc5a1dbd1c832a3bdcb0abff4e5ffc950035febf867de39e9b079cec8863e1d',
    'garage-admin-token': 'hoover4-garage-admin-token',
}


def local_secrets():
    """The Secrets of an installation with the local store layout. Present values stay unchanged."""
    zone_data = json.loads(ZONES.read_text())[ZONE]
    runtime = ensure_secret('hoover-runtime', {
        **COMPOSE_STORE_VALUES, 'proxy-secret': secrets.token_hex(32), 'gpu-token': gpu.token(ZONE),
        'mcp-shared-secret': secrets.token_hex(32), 'browser-fetch-token': secrets.token_hex(32), 'factcheck-api-key': ''},
        follow=('gpu-token',))
    ensure_secret('oauth2-proxy', {'client-secret': zone_data['hoover_oidc_secret'], 'cookie-secret': secrets.token_hex(16),
                                   'proxy-secret': runtime['proxy-secret']}, follow=('client-secret',))
    print(json.dumps({'step': 'local-secrets', 'namespace': NS, 'secrets': ['hoover-runtime', 'oauth2-proxy']}))


def main():
    if sys.argv[2:] == ['local-secrets']:
        if kubectl('get', 'namespace', NS, check=False).returncode:
            apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS, 'labels': {'hoover.dev/zone': 'true'}}})
        local_secrets()
        return
    steps = sys.argv[2:] or ['garage', 'clickhouse', 'secrets', 'temporal', 'manticore']
    if kubectl('get', 'namespace', NS, check=False).returncode:
        apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS, 'labels': {'hoover.dev/zone': 'true', shared.HOOVER_LABEL: 'true'}}})
    # The garage step creates the service keys, which the secrets step copies.
    if 'garage' in steps:
        garage()
    if 'clickhouse' in steps:
        clickhouse()
    runtime = runtime_secrets() if 'secrets' in steps or 'temporal' in steps else None
    if 'temporal' in steps:
        temporal(runtime)
    if 'manticore' in steps:
        manticore()


if __name__ == '__main__':
    main()
