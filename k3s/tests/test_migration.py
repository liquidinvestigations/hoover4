"""The migration suite: the offline copy, its hashes and owner mapping, interruption, and the migration plan rules.

The copy tests run root_copy.py as root inside the test container, on temporary folders. They change no host.
"""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

from conftest import K3S, REPO, site_text
import config

sys.path.insert(0, str(K3S / 'migration'))
import root_copy  # noqa: E402

ROOTLESS_UIDS = '         0       1001          1\n         1     165536      65536\n'
# The copy tests run in a rootless test container, which has 65536 ids. Their source runtime has a smaller range.
SMALL_UIDS = '0 1001 1\n1 20000 30000\n'
SCRIPT = K3S / 'migration' / 'root_copy.py'


def migrate_module():
    spec = importlib.util.spec_from_file_location('migrate', K3S / 'migration' / 'migrate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_owner_map_of_rootless_podman_gives_the_container_ids():
    rows = root_copy.parse_map(ROOTLESS_UIDS)
    assert root_copy.inside_id(1001, rows) == 0
    # ClickHouse (101), Cassandra (999) and Elasticsearch (1000) write with ids of the subordinate range.
    assert root_copy.inside_id(165636, rows) == 101
    assert root_copy.inside_id(166534, rows) == 999
    assert root_copy.inside_id(166535, rows) == 1000
    assert root_copy.inside_id(5, rows) == 5


@pytest.fixture
def source(tmp_path):
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


def test_the_copy_keeps_content_and_maps_each_owner(source):
    src, target, maps, manifest = source
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


def test_verify_finds_changed_content_owner_and_extra_files(source):
    src, target, maps, manifest = source
    copy(src, target, maps, manifest)
    with open(target / 'data/part/columns.bin', 'r+b') as f:
        f.write(b'x')
    os.chown(target / 'commitlog/segment', 0, 0)
    (target / 'stray').write_text('not copied')
    code, result = verify(target, manifest)
    problems = {d['path']: d['problem'] for d in result['first']}
    assert code == 1
    assert problems == {'data/part/columns.bin': 'content', 'commitlog/segment': 'owner', 'stray': 'not in the manifest'}


def test_an_interrupted_copy_is_cleared_and_copied_again(source):
    src, target, maps, manifest = source
    (target / 'data').mkdir()
    (target / 'data' / 'half').write_text('a partial copy')
    refused = copy(src, target, maps, manifest)
    assert refused.returncode != 0 and 'not empty' in refused.stderr + refused.stdout
    subprocess.run([sys.executable, SCRIPT, 'clear', target], check=True)
    assert sorted(os.listdir(target)) == ['lost+found']
    assert copy(src, target, maps, manifest).returncode == 0
    assert verify(target, manifest)[0] == 0


def test_the_plan_maps_each_source_folder_to_its_claim_and_reads_a_serena_ini(tmp_path):
    migrate = migrate_module()
    text = (REPO / 'scripts/deploy.py_tests/fixtures/source-ini/compose-with-serena.ini').read_text()
    path = tmp_path / 'hoover4.ini'
    path.write_text(text)
    source = config.read_source_ini(path, check_paths=False)
    assert '[main_services] serena_enabled' in source.dropped
    claims = migrate.folder_claims(source)
    root = source.volumes_path
    assert claims[f'{root}/clickhouse_data'] == 'clickhouse-data'
    assert claims[f'{root}/temporal_cassandra'] == 'temporal-cassandra'
    assert claims[f'{root}/temporal_elasticsearch'] == 'temporal-elasticsearch'
    assert claims[f'{root}/worker_temp_files'] == 'worker-temp-files-hoover-workers-0'
    assert claims[f'{root}/hoover4-upload-tmp'] == 'upload-tmp'
    # The build folder of the development website and the model cache are not copied.
    assert f'{root}/hoover4-website-target' not in claims and f'{root}/easyocr_models_cache' not in claims
    writable = [m for m in source.dataset_mounts if m['writable']]
    read_only = [m for m in source.dataset_mounts if not m['writable']]
    assert all(claims[m['host_path']].startswith('dataset-') for m in writable)
    assert not [m for m in read_only if m['host_path'] in claims]


def test_a_nondefault_storage_identity_reaches_the_migrated_render(tmp_path):
    import manifests
    text = site_text('single-node.ini').replace('clickhouse_database_prefix = Hoover4', 'clickhouse_database_prefix = Archive2') \
        .replace('collection_bucket_prefix = hoover4-c-', 'collection_bucket_prefix = archive2-c-')
    site = tmp_path / 'site.ini'
    site.write_text(text)
    target = manifests.target_from_site(site, 'main', revision='0123456789abcdef0123', state=tmp_path / 'no-state', nfs={})
    items = json.loads(manifests.render(target))['items']
    workers = next(i for i in items if i['kind'] == 'StatefulSet' and i['metadata']['name'] == 'hoover-workers')
    env = {e['name']: e.get('value') for e in workers['spec']['template']['spec']['containers'][0]['env']}
    assert 'Archive2' in env.values() and 'archive2-c-' in env.values()


def test_image_references_and_manticore_answers():
    migrate = migrate_module()
    assert migrate.full_reference('cassandra:3.11.9') == 'docker.io/library/cassandra:3.11.9'
    assert migrate.full_reference('docker.io/library/cassandra:3.11.9') == 'docker.io/library/cassandra:3.11.9'
    assert migrate.full_reference('temporalio/auto-setup:1.23.1') == 'docker.io/temporalio/auto-setup:1.23.1'
    table = '+-------+------+\n| Table | Type |\n+-------+------+\n| a_vfs | rt   |\n+-------+------+\n'
    assert migrate.cells(table) == [['Table', 'Type'], ['a_vfs', 'rt']]
    assert migrate.cells('Table\tType\na_vfs\trt\n') == [['Table', 'Type'], ['a_vfs', 'rt']]
    assert migrate.parse_size('20Gi') == 20 * 2**30


def test_a_step_waits_for_the_steps_before_it(tmp_path, monkeypatch):
    migrate = migrate_module()
    site = tmp_path / 'site.ini'
    site.write_text(site_text('single-node.ini').replace('[site]\n', f'[site]\nstate_path = {tmp_path / "state"}\n', 1))
    with pytest.raises(SystemExit) as stopped:
        migrate.main(['copy', 'main', '--site', str(site)])
    assert 'needs the steps plan, freeze, record, stop, images first' in str(stopped.value)
