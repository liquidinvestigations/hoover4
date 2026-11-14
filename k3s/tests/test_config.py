"""The site file schema, the per-node projection and the reader of a Compose ini (k3s/config.py)."""
import json
import os

import pytest

from conftest import FIXTURES, REPO, site_text

# The indentation of a host key and of a key of a Hoover installation in the YAML fixtures.
H = '\n      '
V = '\n        '
import config


def parse(name):
    return config.parse(site_text(name))


@pytest.mark.parametrize('name', ['single-node.yml', 'remote.yml'])
def test_round_trip(name):
    site = parse(name)
    text = config.dump(site)
    assert config.parse(text) == site
    assert config.dump(config.parse(text)) == text


def test_yaml_lists_and_comma_texts_give_the_same_site():
    text = site_text('remote.yml')
    listed = text.replace('node_roles: control-plane, worker, registry, data', 'node_roles: [control-plane, worker, registry, data]')
    assert config.parse(listed) == config.parse(text)


def test_the_site_id_comes_from_the_domain(tmp_path):
    site = parse('remote.yml')
    assert site.id == 'example-org'
    path = tmp_path / 'demo.yml'
    path.write_text(site_text('remote.yml'))
    assert config.read(path).state_folder() == tmp_path / 'demo'
    assert config.state_folder(tmp_path / 'sites' / 'a.yml') == tmp_path / 'sites' / 'a'
    with pytest.raises(config.SiteError, match='no site file is given'):
        config.read('')


def test_single_node_needs_no_network_or_public_address():
    site = parse('single-node.yml')
    node = site.nodes['dev']
    assert site.single and node.local
    assert set(node.roles) == {'control-plane', 'worker', 'public', 'registry', 'data'}
    assert not node.networks and not node.lan and not node.public_address
    assert config.node_address(site, node) == config.LOCAL_ADDRESS
    # A public node without a public address gets no host firewall.
    assert node.public_firewall is False


def test_storage_identity_is_independent_of_the_zone():
    site = parse('single-node.yml')
    main = site.hoovers['main']
    assert main.zone == 'zone-a'
    assert main.identity() == {'HOOVER4_CLICKHOUSE_DB_PREFIX': 'Hoover4', 'HOOVER4_MANTICORE_TABLE_PREFIX': '',
                               'S3_SYSTEM_BUCKET': 'hoover4-system', 'S3_COLLECTION_BUCKET_PREFIX': 'hoover4-c-'}


def problems_of(text):
    with pytest.raises(config.SiteError) as caught:
        config.parse(text)
    return str(caught.value)


def test_unknown_key_and_section_are_refused():
    text = site_text('single-node.yml')
    message = problems_of(text.replace('node_roles: single', 'node_roles: single' + H + 'worker_mem_limit: 4G')
                          + 'main_services:\n  vars:\n    common_workers: 3\n')
    assert 'hosts.dev worker_mem_limit is not a known key' in message
    assert 'the group main_services is not known' in message


def test_the_removed_site_keys_are_refused():
    text = site_text('remote.yml')
    message = problems_of(text.replace('    domain: example.org', '    domain: example.org\n    name: remote\n    suffix: example.org\n'
                                       '    operator_user: operator\n    state_path: /srv/state')
                          .replace('node_roles: calls', 'node_roles: calls' + H + 'ssh_address: 203.0.113.11'))
    for key in ('name', 'suffix', 'operator_user', 'state_path'):
        assert f'vars {key} is not a known key' in message
    assert 'hosts.calls ssh_address is not a known key' in message
    message = problems_of(text.replace('ssh_host: calls-public', 'ssh_host: 203.0.113.11'))
    assert 'hosts.calls ssh_host = 203.0.113.11 is an address' in message
    assert 'hosts.calls roles is not a known key' in problems_of(text.replace('node_roles: calls', 'roles: calls'))


def test_tunings_and_schedules_are_not_site_keys():
    text = site_text('single-node.yml').replace('      node: dev', '      node: dev\n      retention: 2')
    assert 'vars.backup retention is not a known key' in problems_of(text)


def test_removed_compose_keys_are_refused_in_the_site_file():
    text = site_text('single-node.yml').replace('zone: zone-a', 'zone: zone-a' + V + 'serena_enabled: false')
    assert 'vars.hoovers.main serena_enabled is not a known key' in problems_of(text)


def test_missing_resources():
    text = site_text('remote.yml')
    message = problems_of(text.replace('home_node: edge', 'home_node: nowhere')
                          .replace('      api_key_file: /home/operator/hoover4/gpu-api-key\n', '')
                          .replace('    hoovers:\n', '    backup:\n      node: missing\n      path: /srv/backups\n    hoovers:\n'))
    assert 'vars.hoovers.zone-a home_node = nowhere is not a node of the site.' in message
    assert 'vars.gpu_pool has no api_key_file' in message
    assert 'vars.backup node = missing is not a node of the site.' in message
    no_control = site_text('single-node.yml').replace('node_roles: single', 'node_roles: worker, public, registry, data')
    assert 'exactly one node with the role control-plane' in problems_of(no_control)
    no_storage = site_text('single-node.yml').replace('      storage: {nvme: hoover4}\n', '')
    assert 'hosts.dev has the role worker and no storage.' in problems_of(no_storage)


def test_incompatible_roles():
    text = site_text('remote.yml')
    message = problems_of(text.replace('node_roles: gpu', 'node_roles: gpu, worker'))
    assert 'combines gpu with worker' in message
    message = problems_of(text.replace('      public_address: 203.0.113.11\n', ''))
    assert 'hosts.calls has the role calls and no public_address.' in message
    message = problems_of(text.replace('node_roles: worker, data', 'node_roles: worker, data' + H + 'tls_dns_credentials_file: /etc/x'))
    assert 'hosts.worker-b tls_dns_credentials_file belongs to a node with the role public.' in message
    message = problems_of(text.replace('address: 10.0.0.3', 'address: 10.9.0.3'))
    assert 'hosts.worker-b networks.site address = 10.9.0.3 is outside vars.networks.site cidr = 10.0.0.0/24.' in message
    message = problems_of(text.replace('stores: zone', 'stores: zone' + V + 'source_ini: /srv/hoover4.ini'))
    assert 'A migrated Compose install uses stores = local.' in message
    message = problems_of(text.replace('clickhouse_database_prefix: zone_a', 'clickhouse_database_prefix: other'))
    assert 'Set clickhouse_database_prefix = zone_a' in message


def test_identity_patterns_come_from_storage_identity_json():
    text = site_text('single-node.yml').replace('clickhouse_database_prefix: Hoover4', 'clickhouse_database_prefix: 1bad')
    assert 'clickhouse_database_prefix = 1bad does not match' in problems_of(text)


def test_per_node_secret_isolation():
    site = parse('remote.yml')
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
    facts = {'worker-b': {'avx2': False, 'volume_groups': {'tier-hdd': {'size_bytes': 100 * 2 ** 30},
                                                           'tier-ssd': {'size_bytes': 21 * 2 ** 30}}},
             'server-a': {'avx2': True, 'volume_groups': {'tier-hdd': {'size_bytes': 400 * 2 ** 30,
                                                                       'k3s_volumes_bytes': 190 * 2 ** 30}}},
             'gpu-1': {'avx2': False, 'gpus': [{'name': 'GB10', 'memory_mib': 122000}, {'name': 'GB10', 'memory_mib': 98000}]}}
    hosts = config.legacy_hosts(parse('remote.yml'), facts)
    assert hosts['server'] == 'server-a'
    # A GPU node gets its flag, which cluster/setup.sh reads through settings.py hosts.
    assert hosts['hosts']['gpu-1']['gpu'] is True
    assert hosts['hosts']['edge']['node_ip'] == '10.0.0.1'
    # The node labels come from the facts.
    assert hosts['hosts']['worker-b']['avx2'] is False and hosts['hosts']['server-a']['avx2'] is True
    assert hosts['hosts']['gpu-1']['gpu_count'] == 2 and hosts['hosts']['gpu-1']['gpu_memory_mib'] == 98000
    assert hosts['hosts']['edge']['facts'] is False
    # The reserve is 5 % of each volume group, rounded up. The k3s data volumes of k3s_volume_group do not count.
    assert hosts['hosts']['worker-b']['storage'] == {'hdd': {'volume_group': 'tier-hdd', 'spare_gb': 5},
                                                     'ssd': {'volume_group': 'tier-ssd', 'spare_gb': 2}}
    assert hosts['hosts']['server-a']['storage']['hdd']['spare_gb'] == 11
    assert hosts['hosts']['edge']['storage']['nvme']['spare_gb'] is None


def test_check_files_reports_missing_secret_files_of_the_local_node(tmp_path):
    key = tmp_path / 'gpu-key'
    text = site_text('single-node.yml').replace('/etc/hoover4/gpu-api-key', str(key))
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
    assert (FIXTURES / 'single-node.yml').exists() and (FIXTURES / 'remote.yml').exists()


def test_a_wireguard_key_with_spaces_is_refused():
    good = 'a' * 42 + 'E='
    for key, accepted in ((good, True), (good[:20] + ' ' + good[21:], False), ('ab;c=', False)):
        text = site_text('remote.yml').replace('public_key: server-a-public-key', f"public_key: '{key}'", 1)
        if accepted:
            assert config.parse(text).nodes['server-a'].networks['site'].public_key == key
        else:
            with pytest.raises(config.SiteError, match='not a WireGuard public key'):
                config.parse(text)


def test_the_host_facts_are_no_site_keys():
    text = site_text('remote.yml')
    message = problems_of(text.replace('node_roles: gpu', 'node_roles: gpu' + H + 'architecture: arm64' + H + 'avx2: false'))
    assert 'hosts.gpu-1 architecture is not a known key' in message and 'hosts.gpu-1 avx2 is not a known key' in message


def test_the_earlier_node_keys_are_refused():
    text = site_text('remote.yml').replace('    networks:\n      site:', '    vpn_cidr: 10.0.0.0/24\n    networks:\n      site:')
    earlier = ('vpn_address: 10.0.0.9', 'wireguard_public_key: k', 'wireguard_port: 1', 'vpn_interface: wg0',
               'wireguard_peers: edge', 'wireguard_via: edge', 'lan_address: 192.0.2.9', 'onprem: true',
               'storage_tiers: hdd', 'lvm_volume_group: x', 'lvm_physical_volumes: /dev/sdb2')
    message = problems_of(text.replace('node_roles: calls', 'node_roles: calls' + H + H.join(earlier)))
    assert 'vars vpn_cidr is not a known key' in message
    for line in earlier:
        assert f'hosts.calls {line.split(":")[0]} is not a known key' in message


def test_the_storage_maps_each_tier_to_its_own_volume_group():
    site = parse('remote.yml')
    assert site.nodes['worker-b'].storage == {'hdd': 'tier-hdd', 'ssd': 'tier-ssd'}
    assert site.nodes['worker-b'].tiers == ('hdd', 'ssd')
    text = site_text('remote.yml')
    message = problems_of(text.replace('storage: {hdd: tier-hdd, ssd: tier-ssd}', 'storage: {hdd: one, ssd: one}'))
    assert 'hosts.worker-b storage gives the volume group one to more than one tier.' in message
    message = problems_of(text.replace('storage: {hdd: tier-hdd, ssd: tier-ssd}', 'storage: {tape: t}'))
    assert 'hosts.worker-b storage.tape is not a storage tier.' in message


def test_the_switches_have_their_defaults():
    site = parse('remote.yml')
    assert config.switches(site.nodes['server-a']) == {'stop_docker': True, 'k3s_volume_group': 'tier-hdd',
                                                       'public_firewall': False, 'wireguard': {'site': 'managed'}}
    assert config.switches(site.nodes['gpu-1'])['wireguard'] == {'site': 'kept'}
    # A public or calls node with a public address gets the host firewall unless the site file turns it off.
    assert site.nodes['edge'].public_firewall and site.nodes['calls'].public_firewall
    text = site_text('remote.yml')
    assert not config.parse(text.replace('node_roles: calls', 'node_roles: calls' + H + 'public_firewall: false')).nodes['calls'].public_firewall
    message = problems_of(text.replace('node_roles: worker, data', 'node_roles: worker, data' + H + 'public_firewall: true'))
    assert 'hosts.worker-b public_firewall belongs to a node with the role public or calls and a public_address.' in message


def test_a_lan_site_uses_the_lan_addresses():
    site = config.parse(LAN)
    assert {n.name: config.node_address(site, n) for n in site.nodes.values()} == {
        'a': '192.168.1.2', 'b': '192.168.1.3', 'c': '192.168.1.4'}
    assert config.node_interface(site, site.nodes['a']) == ''
    assert config.admin_ranges(site) == ['192.168.1.0/24']
    assert config.legacy_settings(site)['frontend_bind'] == ['192.168.1.3']
    assert config.ansible_variables(site, '/s')['hoover4_nodes']['a']['wireguard'] == []
    message = problems_of(LAN.replace('      lan: {home: 192.168.1.4}\n', ''))
    assert 'hosts.c has no lan address.' in message
    message = problems_of(LAN.replace('lan: {home: 192.168.1.4}', 'lan: {home: 10.1.1.4}'))
    assert 'hosts.c lan.home = 10.1.1.4 is outside vars.lans.home cidr = 192.168.1.0/24.' in message
    message = problems_of(LAN.replace('lan: {home: 192.168.1.2}', 'lan: {away: 192.168.1.2}'))
    assert 'hosts.a lan.away: the site has no LAN away in vars.lans.' in message


LAN = """hoover4:
  vars:
    domain: lan.example
    control_plane: a
    lans:
      home: {cidr: 192.168.1.0/24}
  hosts:
    a:
      node_roles: [control-plane, worker, data]
      lan: {home: 192.168.1.2}
      storage: {ssd: a-vg}
    b:
      node_roles: [public, worker, registry]
      lan: {home: 192.168.1.3}
      public_address: 192.168.1.3
      storage: {ssd: b-vg}
      tls_mode: internal
    c:
      node_roles: [worker]
      lan: {home: 192.168.1.4}
      storage: {ssd: c-vg}
"""


# The TLS mode of the HTTPS frontend ------------------------------------------------------------------------------------

CLOUDFLARE = 'tls_dns_credentials_file: /etc/letsencrypt/cloudflare.ini'


def test_the_tls_mode_of_the_public_node_needs_the_keys_of_its_mode():
    text = site_text('remote.yml')
    site = config.parse(text)
    assert config.tls_mode(site.nodes['edge']) == 'cloudflare'
    assert config.legacy_settings(site)['frontend_tls_mode'] == 'cloudflare'
    message = problems_of(text.replace(CLOUDFLARE, ''))
    assert ('hosts.edge tls_mode (default cloudflare) needs tls_dns_credentials_file. Set tls_dns_credentials_file, '
            'or set tls_mode to one of internal, files.') in message
    assert 'settings.json' not in message
    message = problems_of(text.replace(CLOUDFLARE, 'tls_mode: files' + H + 'tls_certificate_file: /etc/hoover/site.pem'))
    assert 'hosts.edge tls_mode = files needs tls_key_file.' in message
    message = problems_of(text.replace(CLOUDFLARE, CLOUDFLARE + H + 'tls_mode: internal'))
    assert 'hosts.edge tls_dns_credentials_file is not used with tls_mode = internal.' in message
    message = problems_of(text.replace(CLOUDFLARE, 'tls_mode: acme'))
    assert 'hosts.edge tls_mode = acme is not one of cloudflare, internal, files.' in message
    message = problems_of(text.replace('node_roles: worker, data', 'node_roles: worker, data' + H + 'tls_mode: internal'))
    assert 'hosts.worker-b tls_mode belongs to a node with the role public.' in message


def test_the_internal_and_files_modes_give_the_frontend_values(tmp_path):
    text = site_text('remote.yml')
    site = config.parse(text.replace(CLOUDFLARE, 'tls_mode: internal'))
    values = config.legacy_settings(site)
    assert values['frontend_tls_mode'] == 'internal'
    assert not {'frontend_tls', 'frontend_dns_credentials', 'frontend_tls_certificate'} & set(values)
    site = config.parse(text.replace(CLOUDFLARE, 'tls_mode: files' + H + 'tls_certificate_file: /etc/hoover/site.pem' + H
                                     + 'tls_key_file: /etc/hoover/site.key'))
    values = config.legacy_settings(site)
    assert (values['frontend_tls_mode'], values['frontend_tls_certificate'], values['frontend_tls_key']) == \
        ('files', '/etc/hoover/site.pem', '/etc/hoover/site.key')
    assert config.parse(config.dump(site)) == site
    values = config.legacy_settings(config.parse(text))
    assert values['frontend_tls_certificate'] == f'/etc/letsencrypt/live/{site.domain}/fullchain.pem'


def test_the_local_node_keeps_the_local_ca():
    text = site_text('single-node.yml')
    site = config.parse(text)
    assert config.tls_mode(site.nodes['dev']) == 'internal'
    message = problems_of(text.replace('local: true', 'local: true' + H + 'tls_mode: cloudflare'))
    assert 'hosts.dev tls_mode = cloudflare: the frontend of the local node uses the local CA only.' in message


def test_the_pods_trust_the_local_ca_of_a_remote_internal_frontend(tmp_path):
    text = site_text('remote.yml')
    path = tmp_path / 'site.yml'
    path.write_text(text.replace(CLOUDFLARE, 'tls_mode: internal'))
    ca = tmp_path / 'site' / 'frontend' / 'local-ca.crt'
    ca.parent.mkdir(parents=True)
    ca.write_text('-----BEGIN CERTIFICATE-----\n')
    assert config.local_ca(config.read(path)) == '-----BEGIN CERTIFICATE-----\n'
    path.write_text(text)
    assert config.local_ca(config.read(path)) == ''


def test_a_lan_node_with_one_address_gets_each_listen_address_once():
    text = site_text('remote.yml').replace('public_address: 203.0.113.10', 'public_address: 10.0.0.1')
    values = config.legacy_settings(config.parse(text))
    assert values['frontend_bind'] == ['10.0.0.1']


# The site file names the state folder ---------------------------------------------------------------------------------

def run_python(code, env):
    import subprocess
    import sys
    clean = {k: v for k, v in os.environ.items() if k not in ('HOOVER4_SITE', 'HOOVER4_OPERATOR_IMAGE')}
    return subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env={**clean, **env},
                          cwd=str(REPO / 'k3s'))


def test_every_private_path_follows_the_site_file(tmp_path):
    site = tmp_path / 'sites' / 'lab.yml'
    site.parent.mkdir()
    site.write_text(site_text('remote.yml'))
    code = ('import sys; sys.path.insert(0, "zones"); import settings, zonestate; '
            'print(settings.PRIVATE, zonestate.PATH, settings.KUBECONFIG, settings.SITE.id)')
    out = run_python(code, {'HOOVER4_SITE': str(site)})
    assert out.returncode == 0, out.stderr
    state = tmp_path / 'sites' / 'lab'
    assert out.stdout.split() == [str(state), str(state / 'zone-state.json'), str(state / 'kubeconfig'), 'example-org']


def test_no_command_has_a_default_site_file():
    out = run_python('import settings', {})
    assert out.returncode != 0 and 'HOOVER4_SITE names no site file' in out.stderr
    import subprocess
    import sys
    clean = {k: v for k, v in os.environ.items() if k not in ('HOOVER4_SITE', 'HOOVER4_OPERATOR_IMAGE')}
    out = subprocess.run([sys.executable, str(REPO / 'k3s/deploy-k3s'), 'status'], capture_output=True, text=True, env=clean)
    assert out.returncode != 0 and 'give the site file with --site FILE, or set HOOVER4_SITE' in out.stderr
