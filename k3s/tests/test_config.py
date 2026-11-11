"""The site file schema, the per-node projection and the reader of a Compose ini (k3s/config.py)."""
import json
import os

import pytest

from conftest import FIXTURES, REPO, site_text
import config


def parse(name):
    return config.parse(site_text(name))


@pytest.mark.parametrize('name', ['single-node.ini', 'remote.ini'])
def test_round_trip(name):
    site = parse(name)
    text = config.dump(site)
    assert config.parse(text) == site
    assert config.dump(config.parse(text)) == text


def test_single_node_needs_no_vpn_or_public_address():
    site = parse('single-node.ini')
    node = site.nodes['dev']
    assert site.single and node.local
    assert set(node.roles) == {'control-plane', 'worker', 'public', 'registry', 'data'}
    assert not node.vpn_address and not node.public_address


def test_storage_identity_is_independent_of_the_zone():
    site = parse('single-node.ini')
    main = site.hoovers['main']
    assert main.zone == 'zone-a'
    assert main.identity() == {'HOOVER4_CLICKHOUSE_DB_PREFIX': 'Hoover4', 'HOOVER4_MANTICORE_TABLE_PREFIX': '',
                               'S3_SYSTEM_BUCKET': 'hoover4-system', 'S3_COLLECTION_BUCKET_PREFIX': 'hoover4-c-'}


def problems_of(text):
    with pytest.raises(config.SiteError) as caught:
        config.parse(text)
    return str(caught.value)


def test_unknown_key_and_section_are_refused():
    text = site_text('single-node.ini')
    message = problems_of(text.replace('[node.dev]', '[node.dev]\nworker_mem_limit = 4G')
                          + '\n[main_services]\ncommon_workers = 3\n')
    assert '[node.dev] worker_mem_limit is not a known key' in message
    assert '[main_services] is not a known section' in message


def test_tunings_and_schedules_are_not_site_keys():
    text = site_text('single-node.ini').replace('[backup]', '[backup]\nretention = 2')
    assert '[backup] retention is not a known key' in problems_of(text)


def test_removed_compose_keys_are_refused_in_the_site_file():
    text = site_text('single-node.ini').replace('[hoover.main]', '[hoover.main]\nserena_enabled = false')
    assert '[hoover.main] serena_enabled is not a known key' in problems_of(text)


def test_missing_resources():
    text = site_text('remote.ini')
    message = problems_of(text.replace('home_node = edge', 'home_node = nowhere')
                          .replace('api_key_file = /home/operator/hoover4/gpu-api-key\n', '')
                          + '\n[backup]\nnode = missing\npath = /srv/backups\n')
    assert '[hoover.zone-a] home_node = nowhere is not a node of the site.' in message
    assert '[gpu_pool] has no api_key_file' in message
    assert '[backup] node = missing is not a node of the site.' in message
    no_control = site_text('single-node.ini').replace('roles = single', 'roles = worker, public, registry, data')
    assert 'exactly one node with the role control-plane' in problems_of(no_control)
    no_tiers = site_text('single-node.ini').replace('storage_tiers = nvme\n', '')
    assert '[node.dev] has the role worker and no storage_tiers.' in problems_of(no_tiers)


def test_incompatible_roles():
    text = site_text('remote.ini')
    message = problems_of(text.replace('[node.gpu-1]\nroles = gpu', '[node.gpu-1]\nroles = gpu, worker'))
    assert 'combines gpu with worker' in message
    message = problems_of(text.replace('public_address = 203.0.113.11\n', ''))
    assert '[node.calls] has the role calls and no public_address.' in message
    message = problems_of(text.replace('roles = worker, data', 'roles = worker, data\ntls_dns_credentials_file = /etc/x'))
    assert '[node.worker-b] tls_dns_credentials_file belongs to a node with the role public.' in message
    message = problems_of(text.replace('vpn_address = 10.0.0.3', 'vpn_address = 10.9.0.3'))
    assert 'outside [site] vpn_cidr' in message
    message = problems_of(text.replace('stores = zone', 'stores = zone\nsource_ini = /srv/hoover4.ini'))
    assert 'A migrated Compose install uses stores = local.' in message
    message = problems_of(text.replace('clickhouse_database_prefix = zone_a', 'clickhouse_database_prefix = other'))
    assert 'Set clickhouse_database_prefix = zone_a' in message


def test_identity_patterns_come_from_storage_identity_json():
    text = site_text('single-node.ini').replace('clickhouse_database_prefix = Hoover4', 'clickhouse_database_prefix = 1bad')
    assert 'clickhouse_database_prefix = 1bad does not match' in problems_of(text)


def test_per_node_secret_isolation():
    site = parse('remote.ini')
    secrets = {'/etc/letsencrypt/cloudflare.ini', '/root/vllm-key', '/home/operator/hoover4/gpu-api-key'}
    expected = {'edge': {'/etc/letsencrypt/cloudflare.ini'}, 'gpu-1': {'/root/vllm-key'},
                'server-a': {'/home/operator/hoover4/gpu-api-key'}, 'worker-b': set(), 'calls': set()}
    for node, own in expected.items():
        projection = config.project(site, node)
        text = json.dumps(projection)
        assert {s for s in secrets if s in text} == own, node
        assert set(projection['secret_files'].values()) == own
        # Every node knows its peers for the VPN and the k3s join.
        assert set(projection['nodes']) == set(site.nodes)
    assert 'hoovers' in config.project(site, 'server-a')
    assert 'hoovers' not in config.project(site, 'edge')


def test_legacy_hosts_projection_for_the_host_scripts():
    hosts = config.legacy_hosts(parse('remote.ini'))
    assert hosts['server'] == 'server-a'
    assert 'gpu-1' not in hosts['hosts']
    assert hosts['hosts']['edge']['public'] == '203.0.113.10:51820'
    assert hosts['hosts']['worker-b']['avx2'] is False


def test_check_files_reports_missing_secret_files_of_the_local_node(tmp_path):
    key = tmp_path / 'gpu-key'
    text = site_text('single-node.ini').replace('/etc/hoover4/gpu-api-key', str(key))
    message = problems_of_files(text)
    assert f'gpu_pool.api_key_file = {key} is not an existing file' in message
    key.write_text('k')
    ok = config.parse(text, check_files=True)
    assert ok.gpu_pool['api_key_file'] == str(key)


def problems_of_files(text):
    with pytest.raises(config.SiteError) as caught:
        config.parse(text, check_files=True)
    return str(caught.value)


# The reader of a Compose ini --------------------------------------------------------------------------------------

SERENA = REPO / 'scripts/deploy.py_tests/fixtures/source-ini/compose-with-serena.ini'


def test_source_ini_accepts_and_reports_removed_serena_settings():
    source = config.read_source_ini(SERENA, check_paths=False)
    assert source.dropped == ['[main_services] serena_enabled', '[main_services] serena_port']
    assert 'serena_enabled' not in source.values['main_services']
    assert [m['container_path'] for m in source.dataset_mounts] == ['/testdata', '/uploads']
    assert source.volumes['clickhouse_data'] == '/srv/hoover4-volumes/clickhouse_data'
    assert source.ops_backup_dir == '/srv/hoover4-volumes/ops_backups'


def test_source_ini_refuses_unknown_keys(tmp_path):
    path = tmp_path / 'hoover4.ini'
    path.write_text(SERENA.read_text().replace('[main_services]', '[main_services]\nworker_count = 3'))
    with pytest.raises(config.SiteError, match=r'\[main_services\] worker_count is not a known key'):
        config.read_source_ini(path, check_paths=False)


def source_tree(tmp_path, inside=False):
    volumes = tmp_path / 'volumes'
    for name in ('clickhouse_data', 'manticore_data_v14', 'garage_meta', 'garage_data', 'temporal_cassandra',
                 'temporal_elasticsearch'):
        (volumes / name).mkdir(parents=True)
    data = volumes / 'testdata' if inside else tmp_path / 'testdata'
    data.mkdir()
    (tmp_path / 'uploads').mkdir()
    text = (SERENA.read_text().replace('/srv/hoover4-volumes', str(volumes))
            .replace('/srv/hoover4-testdata', str(data)).replace('/srv/hoover4-uploads', str(tmp_path / 'uploads')))
    path = tmp_path / 'hoover4.ini'
    path.write_text(text)
    return path, volumes


def test_source_ini_paths_are_checked_before_any_copy(tmp_path):
    path, volumes = source_tree(tmp_path)
    before = sorted(os.walk(tmp_path))
    source = config.read_source_ini(path)
    assert source.volumes_path == str(volumes)
    assert sorted(os.walk(tmp_path)) == before
    (volumes / 'temporal_cassandra').rmdir()
    with pytest.raises(config.SiteError, match='temporal_cassandra does not exist'):
        config.read_source_ini(path)


def test_source_ini_refuses_a_dataset_inside_the_volumes_folder(tmp_path):
    path, _ = source_tree(tmp_path, inside=True)
    with pytest.raises(config.SiteError, match='host_path is inside volumes_path'):
        config.read_source_ini(path)


def test_source_ini_refuses_missing_dataset_folder(tmp_path):
    path, _ = source_tree(tmp_path)
    (tmp_path / 'uploads').rmdir()
    with pytest.raises(config.SiteError, match='uploads'):
        config.read_source_ini(path)


def test_fixture_folder_is_tracked_with_both_sites():
    assert (FIXTURES / 'single-node.ini').exists() and (FIXTURES / 'remote.ini').exists()
