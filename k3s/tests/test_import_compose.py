"""The Compose import suite: the ini reader, the folder checks, the renames, the refusal of a second import, and the
offline copy with its hashes and owner mapping.

The copy tests run root_copy.py as root inside the test container, on temporary folders. No test changes a host or a
cluster.
"""
import importlib.util
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import K3S, REPO, write_site
import config

sys.path.insert(0, str(K3S / 'import_compose'))
import probe  # noqa: E402
import renames  # noqa: E402
import root_copy  # noqa: E402
import source as compose_source  # noqa: E402

ROOTLESS_UIDS = '         0       1001          1\n         1     165536      65536\n'
# The copy tests run in a rootless test container, which has 65536 ids. Their source runtime has a smaller range.
SMALL_UIDS = '0 1001 1\n1 20000 30000\n'
SCRIPT = K3S / 'import_compose' / 'root_copy.py'
SERENA = REPO / 'scripts/deploy.py_tests/fixtures/source-ini/compose-with-serena.ini'
ZONE_A = config.Hoover(zone='zone-a', home_node='dev', stores='local', temporal_backend='cassandra')


def importer():
    spec = importlib.util.spec_from_file_location('import_compose', K3S / 'import_compose' / 'import_compose.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The ini reader and the folder arguments ------------------------------------------------------------------------------

def test_the_ini_reader_accepts_and_reports_removed_serena_settings():
    source = compose_source.read_ini(SERENA)
    assert source.dropped == ['[main_services] serena_enabled', '[main_services] serena_port']
    assert 'serena_enabled' not in source.values['main_services']
    assert [m['container_path'] for m in source.dataset_mounts] == ['/testdata', '/uploads']
    assert 'clickhouse_data' in source.volumes and 'temporal_cassandra' in source.volumes
    assert source.not_imported == {'[storage] volumes_path': '/srv/hoover4-volumes'}


def test_the_ini_reader_refuses_unknown_keys(tmp_path):
    path = tmp_path / 'hoover4.ini'
    path.write_text(SERENA.read_text().replace('[main_services]', '[main_services]\nworker_count = 3'))
    with pytest.raises(compose_source.SourceError, match=r'\[main_services\] worker_count is not a known key'):
        compose_source.read_ini(path)


def test_the_history_shard_count_is_the_explicit_value_or_the_deploy_default(tmp_path):
    assert compose_source.effective(compose_source.read_ini(SERENA), 'main_services', 'temporal_history_shards') == '128'
    path = tmp_path / 'hoover4.ini'
    path.write_text(SERENA.read_text().replace('[main_services]', '[main_services]\ntemporal_history_shards = 64'))
    assert compose_source.effective(compose_source.read_ini(path), 'main_services', 'temporal_history_shards') == '64'


@pytest.mark.parametrize('text,problem', [('/mnt/volumes', 'absolute path'), ('a/../../etc', 'contains `..`'),
                                          ('', 'is empty'), ('./', 'names the data root')])
def test_a_folder_argument_is_relative_to_the_data_root(text, problem):
    with pytest.raises(compose_source.SourceError, match=problem):
        compose_source.relative_folder(text)


def test_a_folder_argument_is_normalized():
    assert compose_source.relative_folder('./compose//volumes/') == 'compose/volumes'


# The checks on the source node (probe.py) -----------------------------------------------------------------------------

def source_root(tmp_path):
    root = tmp_path / 'hoover-data'
    for name in compose_source.REQUIRED:
        (root / 'compose' / name).mkdir(parents=True)
    (root / 'compose' / 'clickhouse_data' / 'part.bin').write_bytes(b'x' * 1000)
    (root / 'uploads').mkdir()
    return root


def request(root, **extra):
    return {'root': str(root), 'folder': 'compose', 'volumes': list(compose_source.REQUIRED) + ['ops_backups'],
            'required': list(compose_source.REQUIRED), 'datasets': {}, **extra}


def test_the_probe_measures_each_folder_and_skips_a_missing_optional_folder(tmp_path):
    root = source_root(tmp_path)
    out = probe.probe(request(root, datasets={'uploads': 'uploads'}))
    assert out['problems'] == []
    assert out['volumes']['clickhouse_data']['bytes'] == 1000
    assert out['volumes']['clickhouse_data']['path'] == str(root / 'compose' / 'clickhouse_data')
    assert 'ops_backups' not in out['volumes']
    assert out['datasets']['uploads']['path'] == str(root / 'uploads')


def test_the_probe_refuses_a_missing_store_and_a_link_out_of_the_root(tmp_path):
    root = source_root(tmp_path)
    (root / 'compose' / 'temporal_cassandra').rmdir()
    outside = tmp_path / 'elsewhere'
    outside.mkdir()
    os.symlink(outside, root / 'linked')
    out = probe.probe(request(root, datasets={'uploads': 'linked'}))
    assert any('temporal_cassandra does not exist' in p for p in out['problems'])
    assert any('leaves the data root' in p for p in out['problems'])
    os.symlink(outside, root / 'compose-link')
    assert 'leaves the data root' in probe.probe(request(root, folder='compose-link'))['problems'][0]


def test_the_probe_refuses_a_dataset_inside_the_volume_folder(tmp_path):
    root = source_root(tmp_path)
    (root / 'compose' / 'uploads').mkdir()
    out = probe.probe(request(root, datasets={'uploads': 'compose/uploads'}))
    assert any('overlaps the volume folder' in p for p in out['problems'])


# The renames ------------------------------------------------------------------------------------------------------------

def test_the_compose_names_become_the_zone_names():
    databases = renames.database_renames({'Hoover4_Processing', 'Hoover4_Collection_my_docs', 'default'}, ZONE_A)
    assert databases == [('Hoover4_Collection_my_docs', 'zone_a_Collection_my_docs'), ('Hoover4_Processing', 'zone_a_Processing')]
    assert renames.table_renames(['my_docs_vfs', 'my_docs_1'], ZONE_A) == [('my_docs_1', 'zone_a_my_docs_1'),
                                                                            ('my_docs_vfs', 'zone_a_my_docs_vfs')]
    assert renames.bucket_name('hoover4-system', ZONE_A) == 'zone-a-system'
    assert renames.bucket_name('hoover4-c-my-docs', ZONE_A) == 'zone-a-c-my-docs'
    assert renames.bucket_name('other', ZONE_A) is None


def test_the_names_follow_the_storage_identity_cases():
    """The second case of storage_identity.json names the zone-a values, the first case the Compose defaults."""
    cases = json.loads(renames.STORAGE_IDENTITY.read_text())['cases']
    compose, zone = cases[0], cases[1]
    assert renames.database_renames([compose['global_database'], compose['collection_database']], ZONE_A) == sorted(
        [(compose['global_database'], zone['global_database']), (compose['collection_database'], zone['collection_database'])])
    assert renames.table_renames([compose['manticore_table']], ZONE_A) == [(compose['manticore_table'], zone['manticore_table'])]
    assert renames.bucket_name(compose['collection_bucket'], ZONE_A) == zone['collection_bucket']


BUCKETS = [{'id': 'b2', 'created': '', 'globalAliases': [], 'localAliases': [{'accessKeyId': 'GK1', 'alias': 'hoover4-c-my-docs'}]},
           {'id': 'b1', 'created': '', 'globalAliases': ['hoover4-system'], 'localAliases': []}]


def test_the_bucket_aliases_change_and_keep_their_access_key():
    changes = renames.bucket_renames(BUCKETS, ZONE_A)
    assert changes == [{'bucketId': 'b1', 'old': 'hoover4-system', 'new': 'zone-a-system', 'accessKeyId': ''},
                       {'bucketId': 'b2', 'old': 'hoover4-c-my-docs', 'new': 'zone-a-c-my-docs', 'accessKeyId': 'GK1'}]
    assert renames.alias_request(changes[0], 'new') == {'bucketId': 'b1', 'globalAlias': 'zone-a-system'}
    assert renames.alias_request(changes[1], 'old') == {'bucketId': 'b2', 'localAlias': 'hoover4-c-my-docs', 'accessKeyId': 'GK1'}
    assert renames.renamed_aliases(BUCKETS, changes) == {'b1': ['zone-a-system'], 'b2': ['zone-a-c-my-docs@GK1']}
    with pytest.raises(renames.RenameError, match='other-bucket'):
        renames.bucket_renames(BUCKETS + [{'id': 'b3', 'globalAliases': ['other-bucket'], 'localAliases': []}], ZONE_A)


def test_a_manticore_table_without_the_compose_prefix_stops_the_renames():
    source = {**renames.compose_identity(), 'manticore_table_prefix': 'old_'}
    with pytest.raises(renames.RenameError, match='does not have the Compose prefix'):
        renames.table_renames(['vfs'], ZONE_A, source)


def test_the_s3_path_columns_get_the_new_bucket_names():
    columns = [('zone_a_Collection_x', 'blobs', 's3_path', False), ('zone_a_Collection_x', 'blobs', 'blob_hash', True),
               ('zone_a_Processing', 'feedback_reports', 'screenshot_s3_path', False)]
    statements = renames.s3_path_updates(columns, {'hoover4-c-x': 'zone-a-c-x', 'hoover4-system': 'zone-a-system'})
    assert len(statements) == 2
    blobs = statements[0]
    assert blobs.startswith('ALTER TABLE `zone_a_Collection_x`.`blobs` UPDATE `s3_path` = multiIf(')
    # substring() of ClickHouse counts from 1, so the key starts after the length of the old prefix.
    old = 's3://hoover4-c-x/'
    assert f"startsWith(`s3_path`, '{old}'), concat('s3://zone-a-c-x/', substring(`s3_path`, {len(old) + 1}))" in blobs
    assert blobs.endswith("WHERE startsWith(`s3_path`, 's3://hoover4-c-x/') OR startsWith(`s3_path`, 's3://hoover4-system/')")
    assert '`screenshot_s3_path`' in statements[1]
    with pytest.raises(renames.RenameError, match='sorting key'):
        renames.s3_path_updates([('d', 't', 's3_path', True)], {'a': 'b'})


def test_the_dataset_rows_move_below_data():
    mounts = [{'name': 'testdata', 'container_path': '/testdata'}, {'name': 'uploads', 'container_path': '/uploads/'},
              {'name': 'kept', 'container_path': '/data/kept'}]
    paths = renames.dataset_paths(mounts)
    assert paths == {'/testdata': '/data/testdata', '/uploads': '/data/uploads'}
    statement = renames.dataset_path_update('zone_a_Processing', paths)
    assert statement.startswith('ALTER TABLE `zone_a_Processing`.`dataset` UPDATE `dataset_path` = multiIf(')
    assert "`dataset_path` = '/uploads', '/data/uploads'" in statement
    assert f"startsWith(`dataset_path`, '/uploads/'), concat('/data/uploads/', substring(`dataset_path`, {len('/uploads') + 2}))" in statement
    assert renames.dataset_path_update('zone_a_Processing', {}) is None


def test_the_record_gets_the_new_names_for_the_checks():
    databases = [('Hoover4_Processing', 'zone_a_Processing')]
    assert renames.renamed_counts({'Hoover4_Processing.dataset': 3, 'default.t': 1}, databases) == {
        'zone_a_Processing.dataset': 3, 'default.t': 1}
    assert renames.renamed_tables({'x_vfs': 5}, [('x_vfs', 'zone_a_x_vfs')]) == {'zone_a_x_vfs': 5}


def test_a_string_literal_and_an_identifier_are_quoted():
    assert renames.quote("a'b\\c") == "'a\\'b\\\\c'"
    assert renames.ident('a`b') == '`a``b`'


# The plan rules and the refusal of a second import --------------------------------------------------------------------

def run_of(tmp_path, zone='zone-b'):
    module = importer()
    site_path = write_site(tmp_path, 'single-node.yml')
    return module, module.Run(config.read(site_path), zone, site_path)


def test_an_existing_zone_stops_the_import(tmp_path):
    module, r = run_of(tmp_path, 'zone-a')
    assert 'exists. The import creates a new zone' in module.refusal(r, {'zone-a'})
    assert module.refusal(r, set()) is None


def test_a_finished_import_stops_a_second_run(tmp_path):
    module, r = run_of(tmp_path)
    r.write('inputs.json', {'folder': 'compose', 'home': 'dev'})
    for step in module.STEPS[:5]:
        r.finish(step, {})
    # The zone step created the zone, so an interrupted import continues.
    assert module.refusal(r, {'zone-b'}) is None
    assert 'was deleted after the zone step' in module.refusal(r, set())
    for step in module.STEPS[5:]:
        r.finish(step, {})
    message = module.refusal(r, {'zone-b'})
    assert 'holds the import of compose' in message and 'runs once per zone' in message


def test_the_import_keeps_its_records_on_the_workstation(tmp_path):
    import clusterstate
    _, r = run_of(tmp_path)
    assert str(r.folder.relative_to(r.site.state_folder())) + '/' == 'operator/import/zone-b/'
    assert any(str(r.folder.relative_to(r.site.state_folder())).startswith(f.rstrip('/')) for f in clusterstate.EXCLUDED_FOLDERS)


def test_each_writable_dataset_needs_a_folder_or_a_choice_to_leave_it_out():
    module = importer()
    source = compose_source.read_ini(SERENA)
    chosen, problems = module.dataset_choices(source, {}, set())
    assert chosen == {} and len(problems) == 1 and '--dataset uploads=' in problems[0]
    chosen, problems = module.dataset_choices(source, {'uploads': 'up', 'testdata': 'td'}, set())
    assert chosen == {'uploads': 'up', 'testdata': 'td'} and problems == []
    chosen, problems = module.dataset_choices(source, {'archive': 'a'}, {'uploads'})
    assert chosen == {} and problems == ['the ini has no dataset mount archive.']


def test_each_copied_folder_has_its_claim():
    module = importer()
    source = compose_source.read_ini(SERENA)
    probed = {'volumes': {name: {'path': f'/srv/hoover-data/compose/{name}'} for name in source.volumes},
              'datasets': {'uploads': {'path': '/srv/hoover-data/uploads'}}}
    claims = module.folder_claims(source, probed, {'uploads': 'uploads'})
    root = '/srv/hoover-data/compose'
    assert claims[f'{root}/clickhouse_data'] == 'clickhouse-data'
    assert claims[f'{root}/temporal_cassandra'] == 'temporal-cassandra'
    assert claims[f'{root}/worker_temp_files'] == 'worker-temp-files-hoover-workers-0'
    assert claims[f'{root}/hoover4-upload-tmp'] == 'upload-tmp'
    assert claims['/srv/hoover-data/uploads'] == 'dataset-uploads'
    # The build folder of the development website and the model cache are not copied.
    assert f'{root}/hoover4-website-target' not in claims and f'{root}/easyocr_models_cache' not in claims


def test_the_render_of_a_new_zone_has_every_claim_of_the_copy(tmp_path):
    """The plan renders the zone before the zone state holds it."""
    module, r = run_of(tmp_path)
    r.planned = {'home': 'dev'}
    import manifests
    target = module.render_target(r, '0' * 40)
    assert target.hoover.namespace == 'hoover-zone-b' and target.local and target.cassandra and target.enabled
    items = json.loads(manifests.render(target))['items']
    claims = {i['metadata']['name'] for i in items if i['kind'] == 'PersistentVolumeClaim'}
    assert {'clickhouse-data', 'manticore-data', 'manticore-vectors-data', 'garage-meta', 'garage-data', 'temporal-cassandra',
            'temporal-elasticsearch', 'ops-backups', 'upload-tmp', 'dataset-uploads', 'dataset-testdata'} <= claims
    subset = module.store_subset(items)
    assert not [i for i in subset if i['kind'] == 'Job' and i['metadata']['name'].startswith('garage-init')]
    assert [i for i in subset if i['kind'] == 'StatefulSet' and i['metadata']['name'] == 'clickhouse']
    assert not [i for i in subset if i['metadata']['name'] in ('hoover-workers', 'hoover-website')]


def test_a_changed_input_stops_every_later_step(tmp_path):
    module, r = run_of(tmp_path)
    ini = tmp_path / 'compose.ini'
    ini.write_text(SERENA.read_text())
    module.Source.engine, module.Source.node = 'docker', r.site.nodes['dev']
    with pytest.raises(SystemExit, match='no inputs.json'):
        module.check_inputs(r, 'a' * 40)
    r.write('inputs.json', {'revision': 'a' * 40, 'engine': 'docker', 'source_node': 'dev', 'ini': 'compose.ini',
                            'site_fingerprint': module.digest(r.site_path), 'ini_fingerprint': module.digest(ini)})
    assert module.check_inputs(r, 'a' * 40)['source_node'] == 'dev'
    with pytest.raises(SystemExit, match='is not the pinned'):
        module.check_inputs(r, 'b' * 40)
    module.Source.engine = 'podman'
    with pytest.raises(SystemExit, match='the source is podman'):
        module.check_inputs(r, 'a' * 40)
    module.Source.engine = 'docker'
    ini.write_text(SERENA.read_text() + '\n')
    with pytest.raises(SystemExit, match='the Compose ini changed'):
        module.check_inputs(r, 'a' * 40)
    args = SimpleNamespace(folder='other', home=None, ini=None, source_node=None, engine_given=None)
    r.write('inputs.json', {'folder': 'compose'})
    with pytest.raises(SystemExit, match='folder is other, and the plan has compose'):
        module.check_arguments(r, args)


def test_the_ini_stays_below_the_folder_of_the_site_file(tmp_path):
    module, r = run_of(tmp_path)
    with pytest.raises(compose_source.SourceError, match='absolute path'):
        module.ini_path(r, '/etc/hoover4.ini')
    outside = tmp_path.parent / f'{tmp_path.name}-outside.ini'
    outside.write_text('')
    os.symlink(outside, tmp_path / 'linked.ini')
    with pytest.raises(SystemExit, match='leaves the folder of the site file'):
        module.ini_path(r, 'linked.ini')


def test_the_command_line_needs_a_zone_id():
    module = importer()
    with pytest.raises(SystemExit):
        module.parse(['zone_a', 'compose', '--site', '/nonexistent/site.yml'])
    args = module.parse(['zone-a', 'compose', '--home', 'dev', '--ini', 'hoover4.ini', '--dataset', 'uploads=up',
                         '--site', '/nonexistent/site.yml'])
    assert args.dataset == [('uploads', 'up')] and args.engine_given is None


# Source runtime and images ------------------------------------------------------------------------------------------------

def test_image_references_and_manticore_answers():
    module = importer()
    assert module.full_reference('cassandra:3.11.9') == 'docker.io/library/cassandra:3.11.9'
    assert module.full_reference('docker.io/library/cassandra:3.11.9') == 'docker.io/library/cassandra:3.11.9'
    assert module.full_reference('temporalio/auto-setup:1.23.1') == 'docker.io/temporalio/auto-setup:1.23.1'
    table = '+-------+------+\n| Table | Type |\n+-------+------+\n| a_vfs | rt   |\n+-------+------+\n'
    assert module.cells(table) == [['Table', 'Type'], ['a_vfs', 'rt']]
    assert module.cells('Table\tType\na_vfs\trt\n') == [['Table', 'Type'], ['a_vfs', 'rt']]
    assert module.parse_size('20Gi') == 20 * 2**30


def test_rootful_docker_keeps_the_owners_and_rootless_docker_is_refused(monkeypatch, tmp_path):
    module, r = run_of(tmp_path)
    module.Source.engine, module.Source.node = 'docker', r.site.nodes['dev']
    monkeypatch.setattr(module, 'src', lambda argv, **kw: '["name=seccomp,profile=builtin"]')
    uid, gid = module.owner_maps()
    assert root_copy.inside_id(165636, root_copy.parse_map(uid)) == 165636
    monkeypatch.setattr(module, 'src', lambda argv, **kw: '["name=rootless"]')
    with pytest.raises(SystemExit, match='rootless'):
        module.owner_maps()
    module.Source.engine = 'podman'
    monkeypatch.setattr(module, 'src', lambda argv, **kw: ROOTLESS_UIDS)
    assert module.owner_maps() == (ROOTLESS_UIDS, ROOTLESS_UIDS)
    # The source node runs each command over SSH with its arguments quoted. The local node is localhost.
    argv = module.Source.argv(['docker', 'exec', 'clickhouse', 'sh', '-c', 'echo a b'])
    assert argv[0] == 'ssh' and 'localhost' in argv and argv[-1] == "docker exec clickhouse sh -c 'echo a b'"


# The offline copy (root_copy.py) ------------------------------------------------------------------------------------------

def test_the_owner_map_of_rootless_podman_gives_the_container_ids():
    rows = root_copy.parse_map(ROOTLESS_UIDS)
    assert root_copy.inside_id(1001, rows) == 0
    # ClickHouse (101), Cassandra (999) and Elasticsearch (1000) write with ids of the subordinate range.
    assert root_copy.inside_id(165636, rows) == 101
    assert root_copy.inside_id(166534, rows) == 999
    assert root_copy.inside_id(166535, rows) == 1000
    assert root_copy.inside_id(5, rows) == 5


@pytest.fixture
def tree(tmp_path):
    if os.geteuid() != 0:
        pytest.skip('the copy tests run as root in the test container')
    src = tmp_path / 'source'
    (src / 'data' / 'part').mkdir(parents=True)
    (src / 'data' / 'part' / 'columns.bin').write_bytes(os.urandom(300_000))
    (src / 'commitlog').mkdir()
    (src / 'commitlog' / 'segment').write_text('segment')
    os.symlink('data/part', src / 'latest')
    for path, uid in ((src, 1001), (src / 'data', 20100), (src / 'data' / 'part', 20100),
                      (src / 'data' / 'part' / 'columns.bin', 20100), (src / 'commitlog', 20998),
                      (src / 'commitlog' / 'segment', 20998)):
        os.chown(path, uid, uid)
    os.chmod(src / 'commitlog' / 'segment', 0o600)
    maps = tmp_path / 'maps'
    maps.mkdir()
    (maps / 'uid_map').write_text(SMALL_UIDS)
    (maps / 'gid_map').write_text(SMALL_UIDS)
    target = tmp_path / 'target'
    (target / 'lost+found').mkdir(parents=True)
    return src, target, maps, tmp_path / 'manifest.jsonl'


def copy(src, target, maps, manifest):
    return subprocess.run([sys.executable, SCRIPT, 'copy', src, target, maps / 'uid_map', maps / 'gid_map', manifest],
                          capture_output=True, text=True)


def verify(target, manifest):
    r = subprocess.run([sys.executable, SCRIPT, 'verify', target, manifest], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])


def test_the_copy_keeps_content_and_maps_each_owner(tree):
    src, target, maps, manifest = tree
    assert copy(src, target, maps, manifest).returncode == 0
    rows = {r['path']: r for r in map(json.loads, manifest.read_text().splitlines())}
    assert rows['data/part/columns.bin']['owner'] == [101, 101]
    assert rows['data/part/columns.bin']['source_owner'] == [20100, 20100]
    assert rows['commitlog/segment']['owner'] == [999, 999] and rows['commitlog/segment']['mode'] == 0o600
    assert rows['latest'] == {**rows['latest'], 'kind': 'link', 'link': 'data/part'}
    assert os.stat(target / 'data/part/columns.bin').st_uid == 101
    assert os.stat(target).st_uid == 0
    assert (target / 'data/part/columns.bin').read_bytes() == (src / 'data/part/columns.bin').read_bytes()
    code, result = verify(target, manifest)
    assert code == 0 and result['differences'] == 0 and result['files'] == 2


def test_verify_finds_changed_content_owner_and_extra_files(tree):
    src, target, maps, manifest = tree
    copy(src, target, maps, manifest)
    with open(target / 'data/part/columns.bin', 'r+b') as f:
        f.write(b'x')
    os.chown(target / 'commitlog/segment', 0, 0)
    (target / 'stray').write_text('not copied')
    code, result = verify(target, manifest)
    problems = {d['path']: d['problem'] for d in result['first']}
    assert code == 1
    assert problems == {'data/part/columns.bin': 'content', 'commitlog/segment': 'owner', 'stray': 'not in the manifest'}


def test_an_interrupted_copy_is_cleared_and_copied_again(tree):
    src, target, maps, manifest = tree
    (target / 'data').mkdir()
    (target / 'data' / 'half').write_text('a partial copy')
    refused = copy(src, target, maps, manifest)
    assert refused.returncode != 0 and 'not empty' in refused.stderr + refused.stdout
    subprocess.run([sys.executable, SCRIPT, 'clear', target], check=True)
    assert sorted(os.listdir(target)) == ['lost+found']
    assert copy(src, target, maps, manifest).returncode == 0
    assert verify(target, manifest)[0] == 0


def test_the_stream_pack_extracts_into_a_target_that_verifies(tree):
    src, target, maps, manifest = tree
    packer = subprocess.Popen([sys.executable, SCRIPT, 'pack', src, SMALL_UIDS, SMALL_UIDS], stdout=subprocess.PIPE)
    extract = subprocess.run([sys.executable, '-c', importer().EXTRACT.replace("'/target'", repr(str(target)))],
                             stdin=packer.stdout)
    packer.stdout.close()
    assert packer.wait() == 0 and extract.returncode == 0
    os.replace(target / root_copy.PACK_MANIFEST, manifest)
    rows = {r['path']: r for r in map(json.loads, manifest.read_text().splitlines())}
    assert rows['data/part/columns.bin']['owner'] == [101, 101]
    assert os.stat(target / 'data/part/columns.bin').st_uid == 101
    assert os.stat(target / 'commitlog/segment').st_mode & 0o777 == 0o600
    assert os.readlink(target / 'latest') == 'data/part'
    code, result = verify(target, manifest)
    assert code == 0 and result['differences'] == 0 and result['files'] == 2


def test_the_plan_saves_the_ini_values_and_stops_hoover_of_a_new_zone_on_an_applied_site(tmp_path):
    module, r = run_of(tmp_path)
    module_settings = module.operator_settings()
    state = module_settings.State(r.site.operator_state())
    first = state.save(state.revision(), {'zone:zone-a': {'app.hoover': 'true'}})
    state.record_all(first, 'up-1', 'a' * 40)
    path = tmp_path / 'hoover4.ini'
    path.write_text(SERENA.read_text().replace('[main_services]', '[main_services]\ntemporal_history_shards = 64'))
    source = compose_source.read_ini(path)
    # An applied site refuses a change of a fixed value in a scope that runs.
    with pytest.raises(module_settings.SettingsError, match='fixed after the first apply'):
        state.save(state.revision(), {'hoover:zone-b': {module.HISTORY_SHARDS: '64'}})
    revision = module.seed_settings(r, source, '64')
    assert state.effective('hoover:zone-b', revision)[module.HISTORY_SHARDS] == '64'
    assert state.effective('zone:zone-b', revision)['app.hoover'] == 'false'
    assert 'hoover:zone-b' in state._desired()['seeded']
