"""The secret store client (k3s/secretstore.py), the zone secrets of zones.py and the migration of the earlier cluster
copy (k3s/platform/secrets/openbao.py). Each test uses the file store of conftest.py, never a store of a site."""
import json
import multiprocessing
import sys

import pytest

from conftest import K3S

sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'zones'))
sys.path.insert(0, str(K3S / 'platform' / 'secrets'))
import secretstore  # noqa: E402


def test_keep_adds_missing_keys_and_never_replaces_a_stored_value():
    assert secretstore.keep('site/x', {'a': lambda: 'one'}) == {'a': 'one'}
    assert secretstore.keep('site/x', {'a': lambda: 'two', 'b': 'b'}) == {'a': 'one', 'b': 'b'}
    # A copy of an earlier version gives only the keys that the store lacks.
    assert secretstore.keep('site/x', copy={'c': 'c'}) == {'a': 'one', 'b': 'b', 'c': 'c'}
    # follow takes the value of another source, and drop removes a key.
    assert secretstore.keep('site/x', {'b': 'new'}, follow=('b',), drop=('c',)) == {'a': 'one', 'b': 'new'}


def test_a_copy_with_another_value_stops_the_write_and_names_no_value():
    secretstore.keep('zones/zone-a/secrets', {'turn_secret': 'stored-value'})
    with pytest.raises(secretstore.Mismatch) as error:
        secretstore.keep('zones/zone-a/secrets', {'new': 'n'}, copy={'turn_secret': 'live-value'}, source='the Secret x')
    assert 'turn_secret' in str(error.value) and 'the Secret x' in str(error.value)
    assert 'stored-value' not in str(error.value) and 'live-value' not in str(error.value)
    # The refused write changed nothing.
    assert secretstore.read('zones/zone-a/secrets') == {'turn_secret': 'stored-value'}


def test_a_write_over_a_newer_version_is_refused_and_update_repeats_the_change():
    store = secretstore.client()
    store.write('site/y', {'a': '1'}, 0)
    with pytest.raises(secretstore.CasConflict):
        store.write('site/y', {'a': '2'}, 0)
    reads = []
    real = store.read

    def read_with_a_writer_between(path):
        data = real(path)
        if not reads:
            # Another writer changes the path after the first read.
            store.write(path, {**data[0], 'other': 'x'}, data[1])
        reads.append(path)
        return data
    store.read = read_with_a_writer_between
    try:
        assert secretstore.update('site/y', lambda d: {**d, 'mine': 'y'}) == {'a': '1', 'other': 'x', 'mine': 'y'}
    finally:
        store.read = real
    assert len(reads) == 2


def _keep_in_process(address, zone):
    import os
    os.environ['HOOVER4_SECRET_STORE'] = address
    secretstore.reset()
    for n in range(20):
        secretstore.keep('site/zone-users', {f'{zone}-user-{n}': f'{zone}-{n}'})
        secretstore.keep(f'zones/{zone}/secrets', {f'key-{n}': f'{zone}-{n}'})


def test_two_zone_steps_at_the_same_time_keep_both_changes(secret_store):
    # The case of two zone steps that wrote one shared file at the same time: every value of both stays.
    address = f'file://{secret_store}'
    processes = [multiprocessing.Process(target=_keep_in_process, args=(address, z)) for z in ('zone-a', 'zone-b')]
    for p in processes:
        p.start()
    for p in processes:
        p.join(30)
        assert p.exitcode == 0
    users = secretstore.read('site/zone-users')
    assert len(users) == 40
    for zone in ('zone-a', 'zone-b'):
        assert len(secretstore.read(f'zones/{zone}/secrets')) == 20


def test_remove_deletes_every_path_of_a_zone_and_no_other():
    secretstore.keep('zones/zone-a/secrets', {'a': '1'})
    secretstore.keep('zones/zone-a/hoover/oauth2-proxy', {'b': '2'})
    secretstore.keep('zones/zone-ab/secrets', {'c': '3'})
    assert sorted(secretstore.remove('zones/zone-a')) == ['zones/zone-a/hoover/oauth2-proxy', 'zones/zone-a/secrets']
    assert secretstore.read('zones/zone-ab/secrets') == {'c': '3'}


def test_keep_files_moves_a_file_into_the_store_and_writes_the_copies(tmp_path):
    (tmp_path / 'client-secret').write_text('earlier')
    written = secretstore.keep_files('site/operator-login', tmp_path, [('client-secret', 'hex32'), ('cookie-secret', 'hex16'),
                                                                       ('admin-password.bcrypt', None)])
    assert written == ['cookie-secret']
    stored = secretstore.read('site/operator-login')
    assert stored['client-secret'] == 'earlier' and len(stored['cookie-secret']) == 32
    assert 'admin-password.bcrypt' not in stored and not (tmp_path / 'admin-password.bcrypt').exists()
    assert (tmp_path / 'cookie-secret').stat().st_mode & 0o077 == 0
    # A second run changes nothing. A file with another value than the store stops the run.
    assert secretstore.keep_files('site/operator-login', tmp_path, [('client-secret', 'hex32'), ('cookie-secret', 'hex16')]) == []
    (tmp_path / 'client-secret').write_text('changed')
    with pytest.raises(secretstore.Mismatch):
        secretstore.keep_files('site/operator-login', tmp_path, [('client-secret', 'hex32')])


def test_a_zone_step_writes_only_the_secrets_of_its_zone(monkeypatch):
    import zones
    entries = {'zone-a': {'stores': 'site'}, 'zone-b': {'stores': 'site'}}
    monkeypatch.setattr(zones, 'ENTRIES', entries)
    monkeypatch.setattr(zones, 'ZONES', list(entries))
    monkeypatch.setattr(zones, 'SCOPE', 'zone-a')
    # A zone step only reads the call secrets, which the step secret-store writes.
    with pytest.raises(SystemExit, match='steps secret-store'):
        zones.load_secrets()
    calls, users = zones.site_secrets()
    assert set(calls) == {'jvb_password'}
    assert set(users) == set(zones.fixture_users())
    data = zones.load_secrets()
    assert set(data) == {'calls', 'zone-a'}
    assert {'master_password', 'administrator_password', 'objectstore_key', 'postgresql', 'gate_cookie_secret'} <= set(data['zone-a'])
    assert secretstore.read('zones/zone-b/secrets') == {}
    # A second run keeps every value, and an installed zone gets no new Administrator password.
    secretstore.update('zones/zone-a/secrets', lambda d: {k: v for k, v in d.items() if k != 'administrator_password'})
    again = zones.load_secrets()['zone-a']
    assert 'administrator_password' not in again
    assert {k: v for k, v in data['zone-a'].items() if k != 'administrator_password'} == again


def test_the_user_copies_keep_the_order_and_form_of_zone_users_py(tmp_path, monkeypatch):
    import settings
    import zones
    monkeypatch.setattr(zones, 'out', tmp_path / 'zones')
    monkeypatch.setattr(settings, 'ZONE_USER_PASSWORDS', tmp_path / 'zones' / 'fixture-user-passwords.json')
    (tmp_path / 'zones' / 'zone-a').mkdir(parents=True)
    names = zones.fixture_users()
    # The store returns its keys in another order than zone-users.json.
    secretstore.keep('site/zone-users', {n: f'pw-{n}' for n in reversed(names)})
    secretstore.keep('zones/zone-a/test-user', {'password': 'tu'})
    zones.write_user_files(['zone-a'])
    text = (tmp_path / 'zones' / 'fixture-user-passwords.json').read_text()
    assert text == json.dumps({n: f'pw-{n}' for n in names}, indent=1) + '\n'
    assert (tmp_path / 'zones' / 'zone-a' / 'test-user-password').read_text() == 'tu\n'


def legacy(zone_entry, master=None):
    files = {'zones/secrets.json': json.dumps({'calls': {'jvb_password': 'j'}, 'zone-a': zone_entry}).encode(),
             'zones/fixture-user-passwords.json': b'{"anna": "p"}', 'zones/zone-a/test-user-password': b'tu\n',
             'zones/zone-a/opendesk-applied.json': b'{"digest": "d"}\n', 'zones/zone-a/values.yaml': b'derived',
             'zones/passwords.md': b'| view |'}
    if master is not None:
        files['zones/zone-a/master-password'] = master
    return files


def test_the_migration_reads_the_secret_files_and_leaves_the_generated_files():
    import openbao
    values = openbao.legacy_values(legacy({'master_password': 'm', 'turn_secret': 't'}, b'm'))
    paths = {p: (d, k) for p, d, k in values}
    assert set(paths) == {'site/calls', 'zones/zone-a/secrets', 'site/zone-users', 'zones/zone-a/test-user',
                          'zones/zone-a/records/opendesk-applied.json'}
    assert paths['zones/zone-a/test-user'] == ({'password': 'tu'}, 'secret')
    assert paths['zones/zone-a/records/opendesk-applied.json'][1] == 'record'
    # A master password file that differs from the zone secrets stops the migration.
    with pytest.raises(SystemExit, match='master-password differs'):
        openbao.legacy_values(legacy({'master_password': 'm'}, b'other'))


def test_the_migration_writes_nothing_when_a_stored_value_differs(monkeypatch):
    import openbao
    files = legacy({'master_password': 'm', 'turn_secret': 't'})
    objects = {p: (f'state-{n}', d) for n, (p, d) in enumerate(files.items())}
    monkeypatch.setattr(openbao, 'legacy_objects', lambda: objects)
    secretstore.keep('zones/zone-a/secrets', {'turn_secret': 'other'})
    with pytest.raises(SystemExit, match='Nothing was written'):
        openbao.migrate()
    assert secretstore.read('site/calls') == {} and secretstore.read('zones/zone-a/secrets') == {'turn_secret': 'other'}


def test_the_migration_loads_checks_and_then_deletes_the_earlier_copy(monkeypatch, tmp_path):
    import openbao
    files = legacy({'master_password': 'm', 'turn_secret': 't'})
    objects = {p: (f'state-{n}', d) for n, (p, d) in enumerate(files.items())}
    monkeypatch.setattr(openbao, 'legacy_objects', lambda: dict(objects))
    monkeypatch.setattr(openbao.settings, 'PRIVATE', tmp_path)
    (tmp_path / 'zones').mkdir()
    (tmp_path / 'zones' / 'secrets.json').write_bytes(files['zones/secrets.json'])
    result = openbao.migrate()
    assert result['paths'] == 5 and result['checked_keys'] == 5
    assert secretstore.read('zones/zone-a/secrets') == {'master_password': 'm', 'turn_secret': 't'}
    assert secretstore.record('zone-a', 'opendesk-applied.json') == '{"digest": "d"}\n'
    # A second migration writes nothing.
    assert openbao.migrate()['written'] == 0
    deleted = []
    monkeypatch.setattr(openbao, 'kubectl', lambda *args, **kw: deleted.append(args) or '')
    done = openbao.finish()
    assert done['deleted_objects'] == len(objects) and 'zones/secrets.json' in done['deleted_files']
    assert not (tmp_path / 'zones' / 'secrets.json').exists()
    assert all(a[:3] == ('-n', 'operator-portal', 'delete') for a in deleted)
    # Without an earlier copy the finish changes nothing.
    monkeypatch.setattr(openbao, 'legacy_objects', lambda: {})
    assert openbao.finish() == {'deleted_objects': 0, 'checked_keys': 0, 'deleted_files': []}


def test_the_policies_give_a_zone_step_only_the_paths_of_its_zone():
    import openbao
    policy = openbao.POLICIES['zone-step']
    zone_lines = [line for line in policy.splitlines() if 'zones/' in line]
    assert zone_lines and all('{{identity.entity.aliases.ACCESSOR.name}}/*' in line for line in zone_lines)
    assert 'path "hoover/data/site/calls" { capabilities = ["read"] }' in policy
    assert 'site/stores' not in policy and 'sys/' not in policy
    assert 'auth/token/create/zone-step' in openbao.POLICIES['runner'] and 'sys/' not in openbao.POLICIES['runner']
    assert 'snapshot-force' in openbao.POLICIES['backup']
