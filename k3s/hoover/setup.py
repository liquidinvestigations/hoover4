#!/usr/bin/env python3
"""Prepare the store tenants and the runtime Secrets for the Hoover of one zone. Each step is idempotent.

PostgreSQL (openDesk chart) and the two Manticore daemons (stores/hoover.py) run in the zone namespace. ClickHouse and
Garage are the shared stores of the site in the namespace hoover-stores (stores/shared.py), where each zone is a tenant.
The zone credentials are in the Secrets hoover-stores and garage-tenants of the zone namespace, so they go with the zone.

- PostgreSQL: role <prefix>_temporal owns the databases <prefix>_temporal and <prefix>_temporal_visibility.
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
- Manticore: the zone user and the user of each service on both daemons, with the password of hoover-stores. The
  daemon starts with hoover_admin from its seed (stores/creds.py). A published bootstrap user manticore is removed.
- Temporal: when its database holds another shard count than zone_ini.SHARDS, the step stops Temporal, creates both
  databases again and starts Temporal, which then creates its tables with the new count. The workflow history goes.
- Secrets hoover-runtime and oauth2-proxy in namespace hoover-<zone>. hoover-runtime holds the store credentials of
  each service, which follow hoover-stores and garage-tenants. Other existing values stay unchanged. The GPU token
  follows gpu.token, and the shared secrets of the MCP servers and of the browser fetch are random.
The script reads credentials from cluster Secrets and never prints a credential.
An installation with the local store layout (manifests.py) needs only the Secrets: setup.py <zone> local-secrets.
Usage: setup.py <zone> [postgres] [garage] [clickhouse] [manticore] [secrets]    Without steps it runs all of them.
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
import zone_ini  # noqa: E402
import gpu  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent / 'stores'))
import service_users  # noqa: E402
import shared  # noqa: E402
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


def postgres(runtime):
    role = f'{PREFIX}_temporal'
    # The password goes in through stdin, so it is not on a command line.
    sql = (f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
           f"CREATE ROLE {role} LOGIN PASSWORD '{runtime['temporal-db-password']}'; END IF; END $$;\n")
    for db in (role, f'{role}_visibility'):
        sql += (f"SELECT 'CREATE DATABASE {db} OWNER {role}' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{db}')\\gexec\n"
                f"REVOKE ALL ON DATABASE {db} FROM PUBLIC;\n")
    kubectl('-n', STORES, 'exec', '-i', 'postgresql-0', '-c', 'postgresql', '--', 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-q',
            input=sql)
    print(json.dumps({'step': 'postgres', 'role': role}))


def psql(sql, database='postgres', check=True):
    return kubectl('-n', STORES, 'exec', '-i', 'postgresql-0', '-c', 'postgresql', '--', 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres',
                   '-qtA', '-d', database, input=sql, check=check)


def temporal_shards(runtime):
    role = f'{PREFIX}_temporal'
    found = psql('SELECT count(*) FROM shards;', role, check=False)
    count = int(found.stdout.strip() or 0) if found.returncode == 0 else 0
    if count in (0, zone_ini.SHARDS):
        print(json.dumps({'step': 'temporal-shards', 'shards': count or None, 'change': 'none'}))
        return
    present = kubectl('-n', NS, 'get', 'deployment', 'temporal', check=False).returncode == 0
    if present:
        kubectl('-n', NS, 'scale', 'deployment', 'temporal', '--replicas=0')
        kubectl('-n', NS, 'wait', '--for=delete', 'pod', '-l', 'app.kubernetes.io/name=temporal', '--timeout=180s', check=False)
    for db in (role, f'{role}_visibility'):
        psql(f'DROP DATABASE IF EXISTS {db} WITH (FORCE);')
    postgres(runtime)
    if present:
        kubectl('-n', NS, 'scale', 'deployment', 'temporal', '--replicas=1')
    print(json.dumps({'step': 'temporal-shards', 'shards': count, 'change': f'reset to {zone_ini.SHARDS}'}))


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
    # The statements go through stdin, so no password is on a command line. CREATE USER fails without effect for a
    # present user, and SET PASSWORD then gives it the password of hoover-stores.
    stores = secret(STORES, 'hoover-stores')
    users = {PREFIX: (stores['manticore-zone'], ('read', 'write', 'schema'))}
    for service in service_users.using('manticore'):
        grants = service_users.MANTICORE_GRANTS[service_users.SERVICES[service]['manticore']]
        users[service_users.user(ZONE, service)] = (stores[f'manticore-{service}'], grants)
    sql = ["DROP USER 'manticore';"]
    for name, (password, grants) in users.items():
        sql += [f"CREATE USER '{name}' IDENTIFIED BY '{password}';", f"SET PASSWORD '{password}' FOR '{name}';"]
        sql += [f"GRANT {a} ON '{PREFIX}_*' TO '{name}';" for a in grants]
    script = ('mysql -h0 -P9306 -uhoover_admin -p"$MT_ADMIN_PASSWORD" --batch --force >/dev/null 2>&1; '
              'mysql -h0 -P9306 -uhoover_admin -p"$MT_ADMIN_PASSWORD" --batch --skip-column-names -e "SHOW USERS" 2>/dev/null')
    for pod in ('manticore-kata-0', 'manticore-vectors-kata-0'):
        out = kubectl('-n', STORES, 'exec', '-i', pod, '-c', 'manticore', '--', 'sh', '-c', script, input='\n'.join(sql) + '\n').stdout
        print(json.dumps({'step': 'manticore', 'pod': pod, 'users': [w for w in out.split() if w.strip('|+-')]}))


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
            stored[f'manticore-{service}'] = stores[f'manticore-{service}']
        if 'garage' in used:
            key = tenants[service_users.garage_key(ZONE, service)]
            stored[f's3-access-key-{service}'], stored[f's3-secret-key-{service}'] = key['access_key'], key['secret_key']
    runtime = ensure_secret('hoover-runtime', {
        **stored, 'proxy-secret': secrets.token_hex(32), 'temporal-db-password': secrets.token_hex(24),
        'gpu-token': gpu.token(ZONE), 'mcp-shared-secret': secrets.token_hex(32), 'browser-fetch-token': secrets.token_hex(32),
        'factcheck-api-key': ''},
        follow=('gpu-token', *stored), drop=('clickhouse-password', 'manticore-password', 's3-access-key', 's3-secret-key'))
    ensure_secret('oauth2-proxy', {'client-secret': zone_data['hoover_oidc_secret'], 'cookie-secret': secrets.token_hex(16),
                                   'proxy-secret': runtime['proxy-secret']}, follow=('client-secret',))
    print(json.dumps({'step': 'secrets', 'namespace': NS, 'secrets': ['hoover-runtime', 'oauth2-proxy']}))
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
    steps = sys.argv[2:] or ['garage', 'clickhouse', 'secrets', 'postgres', 'manticore']
    if kubectl('get', 'namespace', NS, check=False).returncode:
        apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS, 'labels': {'hoover.dev/zone': 'true', shared.HOOVER_LABEL: 'true'}}})
    # The garage step creates the service keys, which the secrets step copies.
    if 'garage' in steps:
        garage()
    if 'clickhouse' in steps:
        clickhouse()
    runtime = runtime_secrets() if 'secrets' in steps or 'postgres' in steps else None
    if 'postgres' in steps:
        postgres(runtime)
        temporal_shards(runtime)
    if 'manticore' in steps:
        manticore()


if __name__ == '__main__':
    main()
