"""The openDesk databases of a zone on the shared PostgreSQL of the site: the server, the values, the users and rights,
the move from the zone PostgreSQL, the backup and the removal (../zones/postgresql.py, ../hoover/stores/shared.py)."""
import json
import re
import sys

import pytest

from conftest import K3S, REPO

sys.path.insert(0, str(K3S / 'zones'))
sys.path.insert(0, str(K3S / 'platform' / 'backups'))
import backups  # noqa: E402
import config  # noqa: E402
import hoover  # noqa: E402
import postgresql  # noqa: E402
import shared  # noqa: E402
import zone  # noqa: E402
import zones  # noqa: E402

PASSWORDS = {key: f'p{n:02d}' + 'a' * 45 for n, key in enumerate(postgresql.DATABASES)}
# A verifier that PostgreSQL 15.13 stored for the password below (CREATE ROLE ... PASSWORD on the shared server).
VERIFIER = ('SCRAM-SHA-256$4096:zvtfjUHppo+GbXDqUevwgA==$QqYNS3QiZqfEjEJCwm9JC5RGbvJ18EKkYVv5PcQDwhw='
            ':Un5TJsXg4HbYC/6i7DftAuWtZmlVF23QqTz/YX+nJl8=')
VERIFIER_PASSWORD = 's4d-scram-probe'


def release(path):
    file = zones.OPENDESK / path
    if not file.exists():
        pytest.skip('the openDesk release is not unpacked in this checkout')
    return file.read_text()


def test_the_databases_are_the_postgresql_databases_of_the_release():
    text = release('helmfile/environments/default/database.yaml.gotmpl').split('databases:', 1)[1]
    found, options, limits = {}, {}, {}
    for key, body in re.findall(r'^  (\w+):\n((?:    .*\n|\n)+)', text, re.M):
        if key == 'defaults' or 'type: "postgresql"' not in body:
            continue
        found[key] = (re.search(r'^    name: "([^"]+)"', body, re.M).group(1), re.search(r'^    username: "([^"]+)"', body, re.M).group(1))
        extra = re.search(r'additionalParams: "([^"]+)"', body)
        if extra:
            options[key] = extra.group(1)
        limit = re.search(r'^    connectionLimit: (\d+)', body, re.M)
        if limit:
            limits[key] = int(limit.group(1))
    assert found == postgresql.DATABASES
    assert limits == postgresql.CONNECTION_LIMITS
    # The same options, in the CREATE DATABASE form of the server.
    normal = lambda text: re.sub(r"\s*=\s*", ' ', text).replace('template=', 'TEMPLATE ').upper()
    assert {k: normal(v) for k, v in options.items()} == {k: normal(v) for k, v in postgresql.CREATE_OPTIONS.items()}
    assert 'userConnectionLimit: 100' in text and postgresql.DEFAULT_CONNECTION_LIMIT == 100


def test_the_server_uses_the_postgresql_image_of_the_release():
    text = release('helmfile/environments/default/images.yaml.gotmpl')
    block = text.split('\n  postgresql:\n', 1)[1]
    tag = re.search(r'tag: "([^"]+)"', block).group(1)
    assert hoover.IMAGES['postgresql'] == f'docker.io/library/postgres:{tag}'


def test_the_names_carry_the_zone_prefix_and_fit_the_name_limit():
    assert postgresql.database_name('zone-a', 'synapse') == 'zone_a_matrix'
    assert postgresql.user_name('zone-a', 'nextcloud') == 'zone_a_nextcloud_user'
    longest = 'zone-' + 'a' * 12
    assert all(len(postgresql.user_name(longest, k)) <= 63 and len(postgresql.database_name(longest, k)) <= 63
               for k in postgresql.DATABASES)


def test_a_verifier_of_postgresql_matches_only_its_password():
    assert postgresql.scram_matches(VERIFIER, VERIFIER_PASSWORD)
    assert not postgresql.scram_matches(VERIFIER, VERIFIER_PASSWORD + 'x')
    assert not postgresql.scram_matches('md5abc', VERIFIER_PASSWORD) and not postgresql.scram_matches('', 'x')


@pytest.fixture
def render(monkeypatch):
    monkeypatch.setattr(zones, 'reduced_resources', lambda: {})
    monkeypatch.setattr(zones, 'ai_values', lambda: {})
    monkeypatch.setattr(zones, 'local_ca', lambda: {})
    monkeypatch.setattr(zones.settings, 'zone_host', lambda z, app: f'{z}-{app}.test')
    data = {'zone-a': {'master_password': 'm', 'turn_secret': 't', 'postgresql': PASSWORDS},
            'calls': {'livekit_secret': 'l', 'jvb_password': 'j'}}
    return lambda entry: zones.zone_values('zone-a', data, 'ssd-ext4', entry)


def test_a_zone_on_the_shared_server_renders_its_databases_and_no_postgresql(render):
    values = render({'stores': 'site', 'postgresql': 'site'})
    assert values['apps']['postgresql'] == {'enabled': False}
    databases = values['databases']
    assert set(databases) == set(postgresql.DATABASES)
    assert databases['synapse'] == {'host': 'postgresql.hoover-stores.svc.cluster.local', 'port': 5432, 'name': 'zone_a_matrix',
                                    'username': 'zone_a_matrix_user', 'password': {'value': PASSWORDS['synapse']}}


@pytest.mark.parametrize('entry', [{'stores': 'site'}, {'stores': 'local', 'postgresql': 'site'}, {}])
def test_a_zone_before_its_move_or_of_the_layout_local_keeps_its_postgresql(render, entry):
    values = render(entry)
    assert 'postgresql' not in values['apps'] and 'databases' not in values


def test_only_a_zone_of_the_store_layout_site_gets_database_passwords(monkeypatch, tmp_path):
    monkeypatch.setattr(zones, 'out', tmp_path)
    monkeypatch.setattr(zones, 'ZONES', ['zone-a', 'zone-b'])
    monkeypatch.setattr(zones, 'ENTRIES', {'zone-a': {'stores': 'site'}, 'zone-b': {'stores': 'local'}})
    data = zones.load_secrets()
    assert set(data['zone-a']['postgresql']) == set(postgresql.DATABASES) and 'postgresql' not in data['zone-b']
    assert len(set(data['zone-a']['postgresql'].values())) == len(postgresql.DATABASES)
    # A second run keeps the passwords.
    assert zones.load_secrets()['zone-a']['postgresql'] == data['zone-a']['postgresql']


def site():
    from test_shared_stores import remote
    return remote('{nodes: [server-a, worker-b]}')


def by(items, kind, name):
    return next(o for o in items if o['kind'] == kind and o['metadata']['name'] == name)


def test_the_site_runs_one_postgresql_in_kata_with_the_admin_secret_and_a_claim_for_each_zone():
    s = site()
    items = shared.objects(s, config.store_plan(s), 2, {})
    server = by(items, 'StatefulSet', 'postgresql')
    spec = server['spec']['template']['spec']
    assert server['metadata']['namespace'] == 'hoover-stores' and server['spec']['replicas'] == 1
    assert spec['runtimeClassName'] == 'kata' and spec['priorityClassName'] == 'hoover-node-bound'
    assert server['spec']['updateStrategy'] == {'type': 'OnDelete'}
    claim = server['spec']['volumeClaimTemplates'][0]['spec']
    assert claim['volumeMode'] == 'Block' and claim['resources']['requests']['storage'] == '40Gi'
    c = next(c for c in spec['containers'] if c['name'] == 'postgresql')
    env = {e['name']: e.get('value', e.get('valueFrom')) for e in c['env']}
    assert env['POSTGRES_PASSWORD'] == {'secretKeyRef': {'name': 'hoover-stores', 'key': 'postgresql-admin'}}
    assert env['PGDATA'] == '/var/lib/postgresql/data/pgdata' and env['BLOCK_MOUNTS'] == '/dev/block-data:/var/lib/postgresql/data'
    assert c['image'] == hoover.IMAGES['postgresql'] and c['image'].startswith('docker.io/library/postgres:15.')
    # After a power loss the start removes the stale lock file, then PostgreSQL replays its log.
    start = c['args'][-1]
    assert start.startswith('rm -f /var/lib/postgresql/data/pgdata/postmaster.pid; exec docker-entrypoint.sh postgres')
    assert '-c max_connections=1000' in start
    assert c['resources']['limits']['memory'] == '2Gi'
    assert by(items, 'Service', 'postgresql')['spec']['ports'] == [{'name': 'postgresql', 'port': 5432, 'targetPort': 5432}]


def test_the_tier_of_the_shared_server_is_fast_and_the_zone_postgresql_keeps_its_tier():
    import zonestate
    assert 'postgresql' not in zonestate.TIERS
    assert shared.STORE_TIERS['postgresql'] == zonestate.FAST


def test_only_the_labelled_zone_namespaces_reach_postgresql():
    policies = {p['metadata']['name']: p['spec'] for p in shared.network()}
    rules = policies['postgresql-clients']['ingress']
    assert rules == [{'from': [{'namespaceSelector': {'matchLabels': {'hoover.dev/opendesk-postgresql': 'true'}}}],
                      'ports': [{'port': 5432}]}]
    # The closed policy covers the pod, and no other policy admits a client to it.
    assert all('postgresql' not in json.dumps(spec['podSelector']) for name, spec in policies.items()
               if name not in ('postgresql-clients', 'closed'))
    assert zone.POSTGRESQL_CLIENT_LABEL == shared.POSTGRESQL_CLIENT_LABEL


def test_a_zone_create_grows_the_claim(monkeypatch):
    assert shared.size('postgresql', 0) == '20Gi' and shared.size('postgresql', 3) == '60Gi'


def state_after(statements_zone):
    """The state that read_state() reads after the statements of a new zone."""
    users = {postgresql.user_name(statements_zone, k): {'verifier': VERIFIER, 'limit': postgresql.connection_limit(k),
                                                        'login': True, 'rights': False} for k in postgresql.DATABASES}
    present = {postgresql.database_name(statements_zone, k): {'owner': postgresql.user_name(statements_zone, k),
                                                              'acl': f'{{{postgresql.user_name(statements_zone, k)}=CTc/x}}'}
               for k in postgresql.DATABASES}
    present.update({d: {'owner': 'postgres', 'acl': '{postgres=CTc/postgres}'} for d in postgresql.SERVER_DATABASES})
    catalogs = {}
    for k in postgresql.DATABASES:
        acls = {c: '{postgres=arwdDxt/postgres}' for c in postgresql.HIDDEN}
        for c in postgresql.READERS.get(k, ()):
            acls[c] = f'{{postgres=arwdDxt/postgres,{postgresql.user_name(statements_zone, k)}=r/postgres}}'
        catalogs[postgresql.database_name(statements_zone, k)] = acls
    return users, present, catalogs


def test_a_new_zone_gets_its_users_databases_and_rights_and_a_second_run_changes_nothing(monkeypatch):
    empty = ({}, {d: {'owner': 'postgres', 'acl': ''} for d in postgresql.SERVER_DATABASES}, {})
    server, inside, changed = postgresql.statements('zone-a', PASSWORDS, empty)
    text = '\n'.join(server)
    assert 'REVOKE ALL ON DATABASE "postgres" FROM PUBLIC;' in text and 'REVOKE ALL ON DATABASE "template1" FROM PUBLIC;' in text
    assert (f'CREATE ROLE "zone_a_authsession_user" LOGIN NOCREATEDB NOCREATEROLE CONNECTION LIMIT 10 '
            f"PASSWORD '{PASSWORDS['umsAuthSession']}';") in server
    assert ('CREATE DATABASE "zone_a_matrix" OWNER "zone_a_matrix_user" ENCODING \'UTF8\' LC_COLLATE \'C\' LC_CTYPE \'C\' '
            'TEMPLATE template0;') in server
    assert 'CREATE DATABASE "zone_a_nextcloud" OWNER "zone_a_nextcloud_user";' in server
    assert sum(s.startswith('REVOKE ALL ON DATABASE "zone_a_') for s in server) == len(postgresql.DATABASES)
    assert set(inside) == {postgresql.database_name('zone-a', k) for k in postgresql.DATABASES}
    assert inside['zone_a_nextcloud'] == [f'REVOKE SELECT ON pg_catalog.{c} FROM PUBLIC;' for c in postgresql.HIDDEN]
    assert 'GRANT SELECT ON pg_catalog.pg_database TO "zone_a_matrix_user";' in inside['zone_a_matrix']
    assert not any('zone-b' in s or 'zone_b' in s for s in server)
    assert postgresql.statements('zone-a', {**PASSWORDS, 'nextcloud': VERIFIER_PASSWORD}, state_after('zone-a')) == (
        [f'ALTER ROLE "zone_a_{u}" PASSWORD \'{PASSWORDS[k]}\';' for k, (_, u) in postgresql.DATABASES.items() if k != 'nextcloud'],
        {}, [f'password of zone_a_{u}' for k, (_, u) in postgresql.DATABASES.items() if k != 'nextcloud'])


def test_an_unchanged_zone_gives_no_statement():
    passwords = {k: VERIFIER_PASSWORD for k in postgresql.DATABASES}
    assert postgresql.statements('zone-a', passwords, state_after('zone-a')) == ([], {}, [])


def test_a_public_right_or_a_lost_login_is_corrected():
    passwords = {k: VERIFIER_PASSWORD for k in postgresql.DATABASES}
    users, present, catalogs = state_after('zone-a')
    users['zone_a_xwiki_user']['login'] = False
    present['zone_a_xwiki']['acl'] = '{=Tc/zone_a_xwiki_user,zone_a_xwiki_user=CTc/zone_a_xwiki_user}'
    catalogs['zone_a_notes']['pg_roles'] = '{postgres=arwdDxt/postgres,=r/postgres}'
    server, inside, changed = postgresql.statements('zone-a', passwords, (users, present, catalogs))
    assert server == ['ALTER ROLE "zone_a_xwiki_user" LOGIN NOCREATEDB NOCREATEROLE CONNECTION LIMIT 100;',
                      'REVOKE ALL ON DATABASE "zone_a_xwiki" FROM PUBLIC;']
    assert inside == {'zone_a_notes': ['REVOKE SELECT ON pg_catalog.pg_roles FROM PUBLIC;']}


def test_a_name_or_password_outside_the_zone_form_is_refused():
    with pytest.raises(ValueError):
        postgresql.quote('zone_a"; DROP')
    with pytest.raises(ValueError):
        postgresql.literal("x' OR '1")


class Move:
    def __init__(self, monkeypatch, source, target):
        self.steps = []
        monkeypatch.setattr(postgresql, 'zone_server', lambda z: True)
        monkeypatch.setattr(postgresql, 'ensure', lambda z, p: self.steps.append('ensure') or [])
        monkeypatch.setattr(postgresql, 'logins', lambda z, allowed: self.steps.append('login' if allowed else 'no login'))
        monkeypatch.setattr(postgresql, 'zone_counts', lambda z: source)
        monkeypatch.setattr(postgresql, 'drop_databases', lambda z, keys: self.steps.append(('drop', sorted(keys))))
        monkeypatch.setattr(postgresql, 'copy_database', lambda z, key, folder: self.steps.append(('copy', key)) or 10)
        monkeypatch.setattr(postgresql, 'shared_counts', lambda z, keys: target)
        monkeypatch.setattr(postgresql, 'nextcloud_config', lambda z, p: self.steps.append('nextcloud') or True)
        monkeypatch.setattr(postgresql, 'volume', lambda z: 'pv-zone')
        monkeypatch.setattr(postgresql, 'kubectl', lambda *a, **kw: self.steps.append(a[:3]) or '')
        monkeypatch.setattr(postgresql, 'write_record', lambda z, r: self.steps.append('record'))
        monkeypatch.setattr(postgresql, 'step', lambda *a, **kw: None)


def test_the_move_copies_each_database_checks_the_counts_and_keeps_the_volume(monkeypatch):
    counts = {'nextcloud': {'public.oc_users': 3}, 'synapse': {'public.events': 9}}
    move = Move(monkeypatch, counts, json.loads(json.dumps(counts)))
    record = postgresql.move('zone-a', PASSWORDS)
    assert move.steps == ['ensure', 'no login', ('drop', ['nextcloud', 'synapse']), 'ensure', ('copy', 'nextcloud'),
                          ('copy', 'synapse'), 'nextcloud', ('patch', 'pv', 'pv-zone'), 'record']
    assert record['databases'] == {'nextcloud': {'tables': 1, 'rows': 3, 'shared_rows': 3},
                                   'matrix': {'tables': 1, 'rows': 9, 'shared_rows': 9}}
    assert record['volumes'] == ['pv-zone']


def test_a_different_count_gives_the_zone_users_their_login_again(monkeypatch):
    move = Move(monkeypatch, {'nextcloud': {'public.oc_users': 3}}, {'nextcloud': {'public.oc_users': 2}})
    with pytest.raises(SystemExit, match='oc_users: the zone server has 3 rows, the shared server 2'):
        postgresql.move('zone-a', PASSWORDS)
    assert move.steps[-1] == 'login' and 'record' not in move.steps and not any(s[:1] == ('patch',) for s in move.steps)


def test_the_nextcloud_configuration_gets_the_shared_server(monkeypatch):
    stored = {'dbhost': 'postgresql:5432', 'dbname': 'nextcloud', 'dbuser': 'nextcloud_user', 'dbpassword': 'old',
              'instanceid': 'oc1'}
    sent = []

    def sql(text, database='postgres', check=True):
        sent.append((text, database))
        return json.dumps(stored) if text.startswith('SELECT') else ''
    monkeypatch.setattr(postgresql, 'server_sql', sql)
    assert postgresql.nextcloud_config('zone-a', PASSWORDS) is True
    update, database = sent[1]
    assert database == 'zone_a_nextcloud'
    value = json.loads(update.split('$hoover$')[1])
    assert value == {'dbhost': 'postgresql.hoover-stores.svc.cluster.local:5432', 'dbname': 'zone_a_nextcloud',
                     'dbuser': 'zone_a_nextcloud_user', 'dbpassword': PASSWORDS['nextcloud'], 'instanceid': 'oc1'}
    stored.update(value)
    sent.clear()
    assert postgresql.nextcloud_config('zone-a', PASSWORDS) is False and len(sent) == 1


def test_the_finish_restarts_the_holders_and_deletes_the_claim_of_the_removed_server(monkeypatch):
    import objectstore
    record = {'zone': 'zone-a', 'switch_started': 100.0}
    monkeypatch.setattr(postgresql, 'read_record', lambda z: record)
    monkeypatch.setattr(postgresql, 'write_record', lambda z, r: None)
    monkeypatch.setattr(postgresql, 'step', lambda *a, **kw: None)
    monkeypatch.setattr(postgresql, 'zone_server_installed', lambda z: False)
    deleted = []
    monkeypatch.setattr(postgresql, 'kubectl', lambda *a, **kw: deleted.append(a) or '')
    monkeypatch.setattr(objectstore, 'restart_holders', lambda z, text, since: [f'{text}:{since}'])
    done = postgresql.finish('zone-a')
    assert done['restarted'] == ['postgresql.hoover-stores.svc.cluster.local:100.0']
    assert deleted == [('-n', 'zone-a', 'delete', 'pvc', 'data-postgresql-0', '--ignore-not-found', '--wait=false')]
    assert done['pause_seconds'] > 0 and postgresql.finish('zone-a') is None


def test_the_holders_are_the_workloads_that_name_the_shared_server_and_nextcloud():
    import base64
    import objectstore

    def workload(name, env=None, secret=None):
        container = {'name': 'c', 'env': env or []}
        if secret:
            container['envFrom'] = [{'secretRef': {'name': secret}}]
        return {'kind': 'Deployment', 'metadata': {'name': name}, 'spec': {'template': {'spec': {'containers': [container]}}}}
    workloads = [workload('keycloak', env=[{'name': 'KC_DB_URL_HOST', 'value': postgresql.HOST}]),
                 workload('synapse', secret='synapse-config'), workload('opendesk-nextcloud-aio'), workload('redis')]
    secrets = [{'metadata': {'name': 'synapse-config'}, 'data': {'c': base64.b64encode(f'host: {postgresql.HOST}'.encode()).decode()}}]
    assert objectstore.consumers(workloads, secrets, [], postgresql.HOST) == [
        'deployment/keycloak', 'deployment/opendesk-nextcloud-aio', 'deployment/synapse']


def test_the_zone_step_moves_a_zone_of_an_earlier_version_only_with_the_admin_kubeconfig(monkeypatch, tmp_path):
    state = {'zones': {'zone-a': {'stores': 'site'}}}
    monkeypatch.setattr(zone.zonestate, 'load', lambda: json.loads(json.dumps(state)))
    monkeypatch.setattr(zone.zonestate, 'save', lambda data: state.update(data))
    monkeypatch.setattr(zone.clusterstate, 'checkpoint', lambda folder: None)
    monkeypatch.setattr(zone, 'PRIVATE', tmp_path)
    (tmp_path / 'zones').mkdir()
    (tmp_path / 'zones' / 'secrets.json').write_text(json.dumps({'zone-a': {'postgresql': PASSWORDS}}))
    ran, moved = [], []
    monkeypatch.setattr(zone, 'run', lambda *a, **kw: ran.append(str(a[-1])))
    monkeypatch.setattr(postgresql, 'zone_server_installed', lambda z: True)
    monkeypatch.setattr(postgresql, 'move', lambda z, p: moved.append(z))
    monkeypatch.setattr(postgresql, 'ensure', lambda z, p: ['user x'])
    monkeypatch.setattr(postgresql, 'can_keep_volumes', lambda: False)
    assert zone.databases('zone-a') is False and moved == [] and 'postgresql' not in state['zones']['zone-a']
    monkeypatch.setattr(postgresql, 'can_keep_volumes', lambda: True)
    assert zone.databases('zone-a') is True and moved == ['zone-a'] and state['zones']['zone-a']['postgresql'] == 'site'
    assert ran[-1].endswith('zones.py')
    # A zone on the shared server only gets its missing parts.
    moved.clear()
    assert zone.databases('zone-a') is False and moved == []
    state['zones']['zone-a'] = {'stores': 'local'}
    assert zone.databases('zone-a') is False


def test_a_new_site_zone_starts_on_the_shared_server(monkeypatch):
    saved = []
    monkeypatch.setattr(zone.zonestate, 'load', lambda: {'schemaVersion': 1, 'zones': {}})
    monkeypatch.setattr(zone.zonestate, 'save', lambda data: saved.append(data))
    monkeypatch.setattr(config, 'zone_problems', lambda z, entry, s: [])
    monkeypatch.setattr(zone, 'step', lambda *a, **kw: None)
    zone.register('zone-c')
    assert saved[0]['zones']['zone-c']['postgresql'] == 'site'


def test_the_openDesk_namespace_of_a_site_zone_gets_the_client_label(monkeypatch, tmp_path):
    monkeypatch.setattr(zone.zonestate, 'load', lambda: {'zones': {'zone-a': {'stores': 'site'}}})
    applied = []
    monkeypatch.setattr(zone, 'apply_manifest', lambda text, namespace=None: applied.append(json.loads(text) if text.startswith('{') else text))
    monkeypatch.setattr(zone, 'PRIVATE', tmp_path)
    (tmp_path / 'zones' / 'zone-a').mkdir(parents=True)
    (tmp_path / 'zones' / 'zone-a' / 'hoover-oidc-secret.json').write_text('{}')
    zone.namespaces('zone-a')
    labels = {o['metadata']['name']: o['metadata']['labels'] for o in applied if isinstance(o, dict) and o.get('kind') == 'Namespace'}
    assert labels == {'zone-a': {'hoover.dev/zone': 'true', 'hoover.dev/opendesk-postgresql': 'true'},
                      'hoover-zone-a': {'hoover.dev/zone': 'true'}}


def test_the_move_record_is_no_input_of_the_waves_and_the_module_is_one():
    source = (K3S / 'zones/zone.py').read_text()
    assert 'postgresql.RECORD' in source and "'zones/postgresql.py'" in source


def test_the_removal_drops_the_databases_and_the_users_of_the_zone_only(monkeypatch):
    sent = []

    def sql(text, database='postgres', check=True, timeout=3600):
        sent.append(text)
        return 'database\tzone_a_nextcloud\nuser\tzone_a_nextcloud_user\n' if text.startswith('SELECT') else ''
    monkeypatch.setattr(shared, 'postgresql_sql', sql)
    monkeypatch.setattr(shared.common, 'log', lambda *a, **k: None)
    assert shared.postgresql_tenant('zone-a') == [('database', 'zone_a_nextcloud'), ('user', 'zone_a_nextcloud_user')]
    assert "starts_with(datname, 'zone_a_')" in sent[0]
    shared.remove_postgresql('zone-a')
    assert sent[-1] == 'DROP DATABASE IF EXISTS "zone_a_nextcloud" WITH (FORCE);\nDROP ROLE IF EXISTS "zone_a_nextcloud_user";\n'


def test_the_zone_backup_dumps_each_database_of_the_shared_server(monkeypatch, tmp_path):
    pods = {'items': []}
    monkeypatch.setattr(backups, 'kubectl', lambda *a, **kw: json.dumps(pods) if a[2] == 'get' else '{"items": []}')
    monkeypatch.setattr(backups, 'shared_databases', lambda ns: postgresql if ns == 'zone-a' else None)
    monkeypatch.setattr(backups, 'opendesk_garage_key', lambda ns: None)
    monkeypatch.setattr(shared, 'ready_pod', lambda store: 'postgresql-0')
    dumped = []

    def dump_out(ns, args, target):
        dumped.append((ns, args[0], args[-1], target.relative_to(tmp_path).as_posix()))
        target.write_bytes(b'-- data\n-- PostgreSQL database dump complete\n\n')
    monkeypatch.setattr(backups, 'dump_out', dump_out)
    backups.copy_namespace('zone-a', tmp_path)
    assert sorted(d[3] for d in dumped) == sorted(f'postgresql/{name}.sql' for name, _ in postgresql.DATABASES.values())
    assert {(d[0], d[1]) for d in dumped} == {('hoover-stores', 'postgresql-0')}
    assert ('hoover-stores', 'postgresql-0', 'zone_a_matrix', 'postgresql/matrix.sql') in dumped
    assert backups.dump_complete(tmp_path / 'postgresql' / 'matrix.sql')
    (tmp_path / 'postgresql' / 'cut.sql').write_bytes(b'-- data\n')
    assert not backups.dump_complete(tmp_path / 'postgresql' / 'cut.sql')
    assert 'postgresql/' in backups.online_parts()


def test_the_restore_replaces_each_database_as_its_user(monkeypatch, tmp_path):
    import podexec
    folder = tmp_path / 'postgresql'
    folder.mkdir()
    for name in ('nextcloud', 'matrix'):
        (folder / f'{name}.sql').write_bytes(b'CREATE TABLE t ();\n-- PostgreSQL database dump complete\n')
    steps = []
    monkeypatch.setattr(backups, 'shared_databases', lambda zone: postgresql)
    monkeypatch.setattr(postgresql, 'zone_passwords', lambda zone: PASSWORDS)
    monkeypatch.setattr(postgresql, 'drop_databases', lambda zone, keys: steps.append(('drop', sorted(keys))))
    monkeypatch.setattr(postgresql, 'ensure', lambda zone, passwords: steps.append('ensure'))
    monkeypatch.setattr(postgresql, 'shared_exec', lambda: ['kubectl', 'exec'])
    monkeypatch.setattr(postgresql, 'nextcloud_config', lambda zone, passwords: steps.append('nextcloud'))

    def run(argv, command, parts, stdout=None, stderr=None):
        steps.append((command[-1], parts[0]))
        return 0
    monkeypatch.setattr(podexec, 'run', run)
    backups.restore_shared_databases(folder, 'zone-b')
    assert steps == [('drop', ['nextcloud', 'synapse']), 'ensure', ('zone_b_matrix', b'SET ROLE "zone_b_matrix_user";\n'),
                     ('zone_b_nextcloud', b'SET ROLE "zone_b_nextcloud_user";\n'), 'nextcloud']
    (folder / 'other.sql').write_bytes(b'')
    with pytest.raises(SystemExit, match='other.sql'):
        backups.restore_shared_databases(folder, 'zone-b')


def test_the_readme_and_the_capability_row_name_the_shared_server():
    readme = (K3S / 'Readme.md').read_text()
    assert '### Keep the openDesk databases on the shared PostgreSQL.' in readme
    assert 'F-admin-64' in (REPO / 'docs/technical-specification/Features.md').read_text()


def test_the_server_has_its_measured_cpu_request_and_the_source_of_the_measurement():
    s = site()
    server = by(shared.objects(s, config.store_plan(s), 2, {}), 'StatefulSet', 'postgresql')
    annotations = server['spec']['template']['metadata']['annotations']
    assert annotations['hoover.dev/cpu-baseline'] == '54m'
    assert annotations['hoover.dev/cpu-request-basis'].endswith('move of two zones and browser checks of 2026-11-18')
