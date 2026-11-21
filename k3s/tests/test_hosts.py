"""The host steps: the variables of the host plays, the k3s configuration of servers and agents, the WireGuard
peers, the datastore script of the k3s server, and the removal of a local installation.

The tests render the templates of ../ansible/roles with Jinja and load the module and the scripts of the roles as
Python modules with replaced paths. No test runs a root command or contacts a host.
"""
import importlib.util
import json
import os
import sys

import jinja2
import pytest
import yaml

from conftest import K3S, site_text
import config

ROLES = K3S / 'ansible' / 'roles'
# The indentation of a host key in the YAML fixtures.
H = '\n      '
REMOTE = site_text('remote.yml')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GROUP_VARS = K3S / 'ansible' / 'playbooks' / 'group_vars' / 'hoover4.yml'


def host_vars(text, node, state='/state', architecture=None):
    """The variables of one node in the host plays: the extra variables of the driver, and the node values that
    playbooks/group_vars/hoover4.yml maps to hoover4_* names. The k3s role reads the architecture on the host, and the
    test gives it: arm64 on a GPU node, else amd64."""
    variables = config.ansible_variables(config.parse(text), state)
    own = variables['hoover4_nodes'][node]
    values = {k: v for k, v in variables.items() if k != 'hoover4_nodes'}
    for name, template in yaml.safe_load(GROUP_VARS.read_text()).items():
        if template.startswith('{{ hoover4_node.'):
            values[name] = own[template.removeprefix('{{ hoover4_node.').removesuffix(' }}')]
    values['hoover4_architecture'] = architecture or ('arm64' if values['hoover4_gpu'] else 'amd64')
    return {**values, 'inventory_hostname': node,
            'hoover4_kata': values['hoover4_architecture'] == 'amd64' and not values['hoover4_gpu']}


def test_the_group_variables_name_every_node_value():
    own = config.ansible_variables(config.parse(site_text('remote.yml')), '/state')['hoover4_nodes']['edge']
    mapped = {t.removeprefix('{{ hoover4_node.').removesuffix(' }}') for t in yaml.safe_load(GROUP_VARS.read_text()).values()
              if t.startswith('{{ hoover4_node.')}
    assert set(own) <= mapped


def render(template, values):
    # Ansible renders templates with trim_blocks, and the filter bool of Ansible keeps a bool.
    environment = jinja2.Environment(trim_blocks=True, undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    environment.filters['bool'] = bool
    return environment.from_string((ROLES / 'hoover4_k3s/templates' / template).read_text()).render(**values)


def test_every_server_initializes_etcd_and_no_agent_does():
    server = render('config.yaml.j2', host_vars(site_text('remote.yml'), 'server-a'))
    agent = render('config.yaml.j2', host_vars(site_text('remote.yml'), 'worker-b'))
    assert 'cluster-init: true\n' in server and 'agent-token-file: /etc/rancher/k3s/agent-token\n' in server
    assert 'cluster-init' not in agent and agent.startswith('server: https://10.0.0.2:6443\ntoken-file: /etc/rancher/k3s/agent-token\n')
    assert 'node-ip: 10.0.0.3\nflannel-iface: wg0\n' in agent


def test_the_configuration_of_a_lan_server_names_the_scheduler_configuration():
    text = site_text('remote.yml')
    values = host_vars(text, 'server-a') | {'hoover4_node_address': '192.0.2.25', 'hoover4_flannel_iface': 'enp3s0',
                                            'inventory_hostname': 'lan-3', 'hoover4_reserved': '',
                                            'hoover4_kubelet_reserved': ''}
    assert render('config.yaml.j2', values) == """# The server keeps its datastore in embedded etcd, also on a site with one node. etcd gives the snapshots of
# the platform backup. One server is not highly available.
cluster-init: true
advertise-address: 192.0.2.25
tls-san:
  - 192.0.2.25
flannel-backend: vxlan
# The Secrets are encrypted at rest (tasks/secrets-encryption.yml).
secrets-encryption: true
token-file: /etc/rancher/k3s/token
agent-token-file: /etc/rancher/k3s/agent-token
write-kubeconfig-mode: "0600"
# The scheduler scores the nodes by their requested CPU and memory shares (scheduler-config.yaml.j2).
kube-scheduler-arg:
  - config=/etc/rancher/k3s/scheduler-config.yaml
# The public host runs the frontend. TopoLVM replaces the local-path volumes.
disable:
  - traefik
  - servicelb
  - local-storage
node-name: lan-3
node-ip: 192.0.2.25
flannel-iface: enp3s0
kubelet-arg:
  # One node can hold several zones. A zone has about 50 pods, and the node pod network is a /24.
  - max-pods=250
  # The pods must not use the memory of the system and k3s, because memory is not overcommitted.
  - eviction-hard=memory.available<500Mi,nodefs.available<5%,imagefs.available<5%
"""


def test_a_gpu_node_keeps_its_own_vpn_interface_and_gets_the_gpu_handler():
    values = host_vars(REMOTE, 'gpu-1')
    assert values['hoover4_flannel_iface'] == 'wg-site' and values['hoover4_wireguard'] == []
    text = render('config.yaml.j2', values)
    assert 'node-taint:\n  - hoover.dev/gpu=true:NoSchedule\n' in text
    runtimes = render('runtimes.toml.j2', values)
    assert 'runtimes.runsc-nvproxy]' in runtimes and 'runtimes.kata]' not in runtimes
    assert 'runtimes.kata]' in render('runtimes.toml.j2', host_vars(REMOTE, 'server-a'))


def test_the_switches_reach_the_host_roles():
    server = host_vars(REMOTE, 'server-a')
    assert server['hoover4_stop_docker'] is True and server['hoover4_k3s_volume_group'] == 'tier-hdd'
    assert server['hoover4_storage'] == {'hdd': 'tier-hdd'} and server['hoover4_public_firewall'] is False
    calls = host_vars(REMOTE, 'calls')
    # The media node with a public address gets the chain coturn_peers, and the WireGuard port of its network.
    assert calls['hoover4_public_firewall'] and calls['hoover4_coturn_peers'] and calls['hoover4_wireguard_ports'] == [51820]
    edge = host_vars(REMOTE, 'edge')
    assert edge['hoover4_public_firewall'] and not edge['hoover4_coturn_peers']
    roles = (K3S / 'ansible/roles/hoover4_host/tasks/main.yml').read_text()
    assert 'when: hoover4_k3s_volume_group | length > 0' in roles and 'when: hoover4_stop_docker | bool' in roles
    firewall = (ROLES / 'hoover4_public_firewall/tasks/main.yml').read_text()
    assert 'when: hoover4_coturn_peers | bool' in firewall
    assert firewall.count('when: hoover4_public_if | length > 0 and hoover4_public_if != hoover4_cluster_if') == 2


def test_the_nodes_connect_with_their_name_or_alias_and_keep_the_state_paths(tmp_path):
    variables = config.ansible_variables(config.parse(site_text('remote.yml')), tmp_path)
    assert variables['hoover4_kubeconfig'] == str(tmp_path / 'kubeconfig')
    assert variables['hoover4_tokens_dir'] == str(tmp_path / 'staging/tokens')
    assert variables['hoover4_domain'] == 'example.org'
    nodes = variables['hoover4_nodes']
    assert nodes['server-a']['convert_sqlite'] is True and nodes['worker-b']['convert_sqlite'] is False
    assert nodes['server-a']['ssh_host'] == 'server-a' and nodes['calls']['ssh_host'] == 'calls-public'
    local = config.ansible_variables(config.parse(site_text('single-node.yml')), tmp_path)['hoover4_nodes']['dev']
    assert local['ssh_host'] == 'localhost' and local['single_local'] is True


# edge is the hub of the network site. server-a and worker-b share the LAN office. calls is on no LAN, so it peers only
# with edge, and the managed nodes reach each other through edge. gpu-1 keeps its own interface.
def peers(site, node):
    return {p['name']: p for w in config.wireguard(site, site.nodes[node]) for p in w['peers']}


def test_a_spoke_peers_with_the_hubs_and_the_nodes_of_its_lan():
    site = config.parse(REMOTE)
    assert set(peers(site, 'edge')) == {'server-a', 'worker-b', 'calls', 'gpu-1'}
    assert set(peers(site, 'server-a')) == {'worker-b', 'edge'}
    assert set(peers(site, 'calls')) == {'edge'}
    # A LAN peer uses the LAN address, a public peer the public address. A peer without either waits for the handshake.
    assert peers(site, 'server-a')['worker-b']['endpoint'] == '192.0.2.11:51820'
    assert peers(site, 'server-a')['edge']['endpoint'] == '203.0.113.10:51820'
    assert peers(site, 'edge')['server-a']['endpoint'] == ''
    # Each side routes the other through the hub, and the hub only forwards. No route goes to gpu-1, which keeps the
    # routes of its own VPN.
    assert peers(site, 'server-a')['edge']['allowed_ips'] == ['10.0.0.1/32', '10.0.0.4/32']
    assert peers(site, 'calls')['edge']['allowed_ips'] == ['10.0.0.1/32', '10.0.0.2/32', '10.0.0.3/32']
    assert peers(site, 'edge')['calls']['allowed_ips'] == ['10.0.0.4/32']
    assert config.parse(config.dump(site)) == site


def test_without_hubs_every_node_peers_with_every_node():
    site = config.parse(REMOTE.replace('        hubs: [edge]\n', ''))
    assert set(peers(site, 'calls')) == {'server-a', 'worker-b', 'edge', 'gpu-1'}
    assert peers(site, 'calls')['edge']['allowed_ips'] == ['10.0.0.1/32']


def test_the_network_check_names_unreachable_peers():
    with pytest.raises(config.SiteError, match='hubs names nowhere, which has no address in this network'):
        config.parse(REMOTE.replace('hubs: [edge]', 'hubs: [edge, nowhere]'))
    # Two managed nodes without a public address and without a shared LAN cannot start a handshake.
    with pytest.raises(config.SiteError, match='hosts.server-a and hosts.worker-b peer in site, and neither can start'):
        config.parse(REMOTE.replace('        hubs: [edge]\n', '').replace('lan: {office: 192.0.2.11}', 'lan: {}'))
    # A node that keeps its interface needs its key in the site file, because the installer cannot read it.
    with pytest.raises(config.SiteError, match='hosts.gpu-1 networks.site has no public_key'):
        config.parse(REMOTE.replace('public_key: gpu-1-public-key, ', ''))
    with pytest.raises(config.SiteError, match='has no address in the network site'):
        config.parse(REMOTE.replace("        site: {address: 10.0.0.4, public_key: calls-public-key}\n", ''))
    with pytest.raises(config.SiteError, match='the site has no network other in vars.networks'):
        config.parse(REMOTE.replace('site: {address: 10.0.0.4,', 'other: {address: 10.0.0.4,'))


def test_the_peer_table_names_the_peers_that_the_person_adds_by_hand():
    rows = config.peer_table(config.parse(REMOTE))
    hand = [r for r in rows if r['by'] == 'hand']
    assert hand == [{'network': 'site', 'node': 'gpu-1', 'interface': 'wg-site', 'peer': 'edge',
                     'endpoint': '203.0.113.10:51820', 'allowed_ips': ['10.0.0.1/32'], 'by': 'hand', 'key': 'present'}]


def test_a_managed_node_without_a_key_gets_its_interface_and_no_peer():
    site = config.parse(REMOTE.replace('public_key: calls-public-key', 'port: 51821'))
    interface = config.wireguard(site, site.nodes['calls'])[0]
    assert interface['public_key'] == '' and interface['address'] == '10.0.0.4/24' and interface['port'] == 51821
    # The other nodes add the peer after the key is in the site file.
    assert 'calls' not in peers(site, 'edge')
    assert next(r for r in config.peer_table(site) if r['peer'] == 'calls')['key'] == 'missing'


def test_the_direct_peer_for_a_node_behind_nat_has_no_endpoint(tmp_path):
    values = host_vars(REMOTE, 'edge')
    peer = next(p for p in values['hoover4_wireguard'][0]['peers'] if p['name'] == 'gpu-1')
    assert peer == {'name': 'gpu-1', 'key': 'gpu-1-public-key', 'endpoint': '', 'allowed_ips': ['10.0.0.5/32']}
    block = wireguard_module().peer_blocks('[Interface]\n', [peer])
    assert 'AllowedIPs = 10.0.0.5/32' in block and not any(line.startswith('Endpoint') for line in block)


def wireguard_module():
    return load(ROLES / 'hoover4_wireguard/library/hoover4_wireguard_peers.py', 'hoover4_wireguard_peers')


def test_the_wireguard_peers_add_routed_addresses_and_remove_none():
    wg = wireguard_module()
    values = host_vars(REMOTE, 'server-a')['hoover4_wireguard'][0]
    # server-a has a hub peer for the whole range and a peer for edge from an earlier run.
    lines = ('[Interface]\nPrivateKey = private\n\n[Peer]\nPublicKey = hub-key\nAllowedIPs = 10.0.0.0/24\n\n'
             '[Peer]\nPublicKey = edge-public-key\nAllowedIPs = 10.0.0.1/32\n').splitlines()
    new = wg.widen_allowed_ips(wg.set_listen_port(lines, values['port'], pytest.fail), values['peers'])
    new += wg.peer_blocks('\n'.join(lines), values['peers'])
    text = '\n'.join(new)
    assert f'ListenPort = {values["port"]}' in text and 'AllowedIPs = 10.0.0.0/24' in text
    assert 'AllowedIPs = 10.0.0.1/32, 10.0.0.4/32' in text
    assert 'calls-public-key' not in text and 'PublicKey = worker-b-public-key' in text
    # On calls the new peer for edge carries the addresses that edge forwards.
    calls = host_vars(REMOTE, 'calls')['hoover4_wireguard'][0]['peers']
    blocks = '\n'.join(wg.peer_blocks('[Interface]\n', calls))
    assert blocks.count('[Peer]') == 1 and 'AllowedIPs = 10.0.0.1/32, 10.0.0.2/32, 10.0.0.3/32' in blocks


def test_the_vpn_interface_must_be_a_valid_name():
    with pytest.raises(config.SiteError, match='is not a network interface name'):
        config.parse(REMOTE.replace('interface: wg-site', "interface: 'a b'"))
    with pytest.raises(config.SiteError, match='uses the interface wg0 in more than one network'):
        config.parse(REMOTE.replace('    lans:', '      other: {cidr: 10.1.0.0/24}\n    lans:').replace(
            'site: {address: 10.0.0.4, public_key: calls-public-key}',
            'site: {address: 10.0.0.4, public_key: calls-public-key}\n        other: 10.1.0.4'))


def test_the_wireguard_module_writes_a_missing_interface():
    wg = wireguard_module()
    assert wg.interface_text('private', '10.0.0.4/24', 51821).splitlines() == [
        '# Written by hoover4. The installer adds the peers of the site file.', '[Interface]', 'PrivateKey = private',
        'Address = 10.0.0.4/24', 'ListenPort = 51821']
    tasks = (ROLES / 'hoover4_wireguard/tasks/interface.yml').read_text()
    assert "Set public_key: '{{ hoover4_wireguard_change.public_key }}'" in tasks


@pytest.fixture
def datastore(tmp_path, monkeypatch):
    """The datastore script with its server folders below tmp_path. run() records the commands."""
    module = load(ROLES / 'hoover4_k3s/files/k3s-datastore.py', 'k3s_datastore')
    for name, path in (('SERVER_DIR', 'server'), ('DB_DIR', 'server/db'), ('K3S_DIR', 'etc')):
        monkeypatch.setattr(module, name, str(tmp_path / path))
    (tmp_path / 'server/db').mkdir(parents=True)
    (tmp_path / 'etc').mkdir()
    module.commands = []
    monkeypatch.setattr(module, 'run', lambda cmd, check=True: module.commands.append(cmd) or '')
    return module


def test_the_datastore_of_the_server_folder(datastore, tmp_path):
    assert datastore.datastore() == 'none'
    (tmp_path / 'server/db/state.db').write_text('sqlite')
    assert datastore.datastore() == 'sqlite'
    (tmp_path / 'server/db/etcd/member').mkdir(parents=True)
    assert datastore.datastore() == 'etcd'


def test_the_sqlite_copy_verifies_before_the_conversion(datastore, tmp_path):
    (tmp_path / 'server/db/state.db').write_text('sqlite')
    (tmp_path / 'server/token').write_text('K10abc::server:secret')
    (tmp_path / 'etc/config.yaml').write_text('cluster-init: true\n')
    target = datastore.preserve(tmp_path / 'recovery')
    assert datastore.commands == [['systemctl', 'stop', 'k3s']]
    sums = (tmp_path / 'recovery' / os.path.basename(target) / 'SHA256SUMS').read_text()
    assert 'db/state.db' in sums and 'server/token' in sums and 'etc/config.yaml' in sums
    assert oct(os.stat(target).st_mode & 0o777) == '0o700'
    # A copy without a datastore file stops the script, and k3s stays stopped.
    (tmp_path / 'server/db/state.db').unlink()
    with pytest.raises(SystemExit):
        datastore.preserve(tmp_path / 'recovery2')


def test_the_snapshot_folder_takes_a_name_and_refuses_links(datastore, tmp_path):
    import pwd
    user = pwd.struct_passwd(('op', 'x', os.getuid(), os.getgid(), '', str(tmp_path / 'home'), '/bin/sh'))
    (tmp_path / 'home').mkdir()
    assert datastore.snapshot_folder(user, 'platform-1') == str(tmp_path / 'home/hoover4-snapshots/platform-1')
    for name in ('../outside', '/etc', '.hidden', 'a/b', ''):
        with pytest.raises(SystemExit):
            datastore.snapshot_folder(user, name)
    (tmp_path / 'outside').mkdir()
    (tmp_path / 'home/hoover4-snapshots/escape').symlink_to(tmp_path / 'outside')
    with pytest.raises(SystemExit):
        datastore.snapshot_folder(user, 'escape')


def retirement():
    spec = importlib.util.spec_from_file_location('local_retirement', K3S / 'tools/local-retirement.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_removal_script_needs_an_archive_and_keeps_the_protected_resources(tmp_path):
    import json
    lr = retirement()
    inventory = {'time': 't', 'node': 'dev', 'protected': {**lr.PROTECTED, '/srv/compose-volumes': 'the stopped Compose volumes'},
                 'volume_groups': {'hoover4': {'volumes': []}}}
    (tmp_path / 'inventory.json').write_text(json.dumps(inventory))
    with pytest.raises(SystemExit, match='holds no archive'):
        lr.removal(tmp_path)
    (tmp_path / 'claims').mkdir()
    (tmp_path / 'claims/a.tar').write_bytes(b'claim data')
    lr.write_manifest(tmp_path)
    assert lr.verify(tmp_path)['differences'] == []
    lr.removal(tmp_path)
    script = (tmp_path / 'remove-local-k3s.sh').read_text()
    assert '#   /etc/rancher/k3s/k3s.yaml: the kubeconfig link of another project' in script
    assert '#   /srv/compose-volumes: the stopped Compose volumes' in script
    # The k3s binary, its links and the k3s scripts belong also to another project, so no line removes them.
    body = script.split('set -eu')[1]
    assert 'k3s-uninstall.sh' not in body and '/usr/local/bin/k3s ' not in body
    assert not any(f'/usr/local/bin/{c}' in body for c in ('kubectl', 'crictl', 'ctr'))
    commands = '\n'.join(line for line in body.splitlines() if not line.startswith('#'))
    assert 'k3s.yaml' not in commands and 'hoover4-admin.yaml' not in commands
    assert 'rm -rf /var/lib/rancher/k3s /var/lib/kubelet' in body
    assert "sed -i '\\# /var/lib/kubelet #d' /etc/fstab" in script
    assert 'rm -rf /srv' not in script and 'hoover-operator' not in script.split('set -eu')[1]
    # vgremove stays a comment, because another volume can use the group.
    assert '\nvgremove' not in script and '# Remove the group only when lvs shows no other volume' in script
    (tmp_path / 'claims/a.tar').write_bytes(b'changed')
    assert lr.verify(tmp_path)['differences'] == ['claims/a.tar']




def store_speeds(folder, speeds):
    (folder / 'speed').mkdir(parents=True, exist_ok=True)
    for name, (threads, speed) in speeds.items():
        (folder / 'speed' / f'{name}.json').write_text(json.dumps({'threads': threads, 'cpu_speed': speed}))


BASE = {'agent': 130.0, 'server': 270.0}


def test_the_reserve_covers_the_base_cost_of_k3s_and_the_threads_that_a_slow_node_lacks(tmp_path):
    site = config.parse(site_text('remote.yml'))
    site.path = tmp_path / 'site.yml'
    store_speeds(site.state_folder(), {'server-a': (12, 4078), 'worker-b': (4, 2018)})
    factors = config.speed_factors(site)
    assert factors['server-a'] == 1.0 and factors['worker-b'] == 0.5
    # A node without the value counts as fast.
    assert factors['edge'] == 1.0
    node = site.nodes['worker-b']
    # 4 threads at half speed are 2 threads of the fastest node. k3s needs 130m of them, which are 260m of the node:
    # the reserve is 4 x (1 - 0.5) + 0.13 = 2.13, rounded up to 100m, and the allocatable CPU is 1.8.
    assert config.kubelet_reserved(node, 0.5, 4, base=BASE) == 'cpu=2200m'
    # The fastest node reserves the base cost, and the server node also its control plane.
    assert config.kubelet_reserved(node, 1.0, 12, base=BASE) == 'cpu=200m'
    assert config.kubelet_reserved(node, 1.0, 12, server=True, base=BASE) == 'cpu=300m'
    # A site value with cpu= replaces the base cost, in threads of the node: 4 - 0.5 x (4 - 0.7) = 2.35.
    node.reserved = 'memory=4Gi,cpu=700m'
    assert config.kubelet_reserved(node, 0.5, 4, base=BASE) == 'memory=4Gi,cpu=2400m'
    assert config.kubelet_reserved(node, 1.0, 4, base=BASE) == 'memory=4Gi,cpu=700m'
    # The memory of a site value stays, and the formula gives the CPU.
    node.reserved = 'memory=4Gi'
    assert config.kubelet_reserved(node, 1.0, 4, base=BASE) == 'memory=4Gi,cpu=200m'
    # Without a site value the measured memory of k3s and the system beside the pods is the memory reserve.
    node.reserved = ''
    memory = {'agent': 2048, 'server': 3072}
    assert config.kubelet_reserved(node, 1.0, 12, base=BASE, memory=memory) == 'memory=2048Mi,cpu=200m'
    assert config.kubelet_reserved(node, 1.0, 12, server=True, base=BASE, memory=memory) == 'memory=3072Mi,cpu=300m'
    node.reserved = 'memory=4Gi'
    assert config.kubelet_reserved(node, 1.0, 4, base=BASE, memory=memory) == 'memory=4Gi,cpu=200m'
    values = host_vars(site_text('remote.yml'), 'worker-b') | {'hoover4_kubelet_reserved': 'cpu=2200m'}
    assert '  - system-reserved=cpu=2200m\n' in render('config.yaml.j2', values)


def test_the_memory_reserve_comes_from_the_memory_table():
    table = json.loads(config.MEMORY_TABLE.read_text())
    assert config.base_memory(table) == {k: int(config._memory_gib(table['node'][k]) * 1024) for k in ('agent', 'server')}
    assert 0 < config.base_memory()['agent'] <= config.base_memory()['server']
    assert config.base_memory({'zone': {}}) == {}


def test_the_base_cost_comes_from_the_cpu_table():
    import json as json_module
    table = json_module.loads(config.CPU_TABLE.read_text())
    assert config.base_cpu(table) == {k: config._cpus(table['runtimeOverhead']['node'][k]) * 1000
                                      for k in ('agent', 'server')}
    assert 0 < config.base_cpu()['agent'] < config.base_cpu()['server']


def test_up_uses_the_stored_speed_and_measures_only_a_node_without_one(tmp_path):
    site = config.parse(site_text('remote.yml'))
    store_speeds(tmp_path, {'server-a': (12, 4078), 'worker-b': (4, 2018)})
    nodes = config.ansible_variables(site, tmp_path)['hoover4_nodes']
    assert nodes['server-a']['speed_stored'] and nodes['worker-b']['speed_stored'] and not nodes['edge']['speed_stored']
    base = config.base_cpu()
    assert nodes['worker-b']['kubelet_reserved'] == config.kubelet_reserved(site.nodes['worker-b'], 0.5, 4, base=base,
                                                                          memory=config.base_memory())
    assert config.ansible_variables(site, tmp_path)['hoover4_speed_dir'] == str(tmp_path / 'speed')
    # The facts play no longer measures the speed, so a new facts file does not change the factors.
    (tmp_path / 'facts').mkdir()
    (tmp_path / 'facts' / 'worker-b.json').write_text(json.dumps({'cpus': 4, 'cpu_speed': 900}))
    assert config.speed_factors(site, tmp_path)['worker-b'] == 0.5
    play = yaml.safe_load((K3S / 'ansible/playbooks/hoover4-hosts.yml').read_text())
    speed = next(p for p in play if 'speed' in p.get('tags', []))
    assert speed['roles'][0]['when'] == 'hoover4_speed_force | default(false) | bool or not hoover4_speed_stored | bool'
    assert 'facts' not in speed['tags']


def test_a_node_without_a_stored_speed_keeps_its_facts_value_and_the_check_names_the_command(tmp_path):
    site = config.parse(site_text('remote.yml'))
    (tmp_path / 'facts').mkdir()
    (tmp_path / 'facts' / 'worker-b.json').write_text(json.dumps({'cpus': 4, 'cpu_speed': 2018}))
    (tmp_path / 'facts' / 'server-a.json').write_text(json.dumps({'cpus': 12, 'cpu_speed': 4078}))
    assert config.adopt_facts_speed(tmp_path) == ['server-a', 'worker-b']
    # A second call keeps the adopted value, also after the facts play wrote a file without cpu_speed.
    (tmp_path / 'facts' / 'worker-b.json').write_text(json.dumps({'cpus': 4}))
    assert config.adopt_facts_speed(tmp_path) == []
    assert config.node_speed(tmp_path, 'worker-b') == {'cpu_speed': 2018, 'source': 'facts'}
    report = config.speed_report(site, tmp_path)
    assert report['worker-b']['factor'] == 0.5
    assert 'earlier facts probe' in report['worker-b']['note']
    assert 'deploy-k3s measure-speed --target worker-b' in report['worker-b']['note']
    assert 'no speed value' in report['edge']['note'] and report['edge']['factor'] == 1.0
    store_speeds(tmp_path, {'worker-b': (4, 2018)})
    assert 'note' not in config.speed_report(site, tmp_path)['worker-b']


def speed_script():
    return load(ROLES / 'hoover4_speed/files/hoover4-speed.py', 'hoover4_speed')


def test_the_speed_measurement_refuses_a_node_that_is_not_at_rest():
    speed = speed_script()
    assert speed.refusal(names=['bash'], units=[], load_now=0.5) == ''
    assert speed.refusal(names=[], units=['k3s-agent'], load_now=0.1).startswith('k3s runs (k3s-agent)')
    assert speed.refusal(names=['k3s-server'], units=[], load_now=0.1).startswith('k3s runs')
    assert 'a container runs (containerd-shim' in speed.refusal(names=['containerd-shim'], units=[], load_now=0.1)
    assert 'conmon' in speed.refusal(names=['conmon'], units=[], load_now=0.1)
    assert speed.refusal(names=[], units=[], load_now=5.5) == 'the 1-minute load is 5.50, above 5. Wait until the node is at rest.'
    assert speed.refusal(names=[], units=[], load_now=5.0) == ''


def test_the_speed_probe_measures_a_positive_cpu_speed():
    speed = speed_script()
    speed.PROBE_SECONDS = 0.05
    assert speed.cpu_speed() > 0
    facts = load(ROLES / 'hoover4_facts/files/hoover4-facts.py', 'hoover4_facts')
    assert not hasattr(facts, 'cpu_speed')


def test_the_containerd_statistics_period_is_ten_seconds():
    values = host_vars(site_text('remote.yml'), 'worker-b')
    text = render('runtimes.toml.j2', values | {'hoover4_kata': True})
    assert "[plugins.'io.containerd.cri.v1.runtime']\n  stats_collect_period = \"10s\"\n" in text


def test_the_scheduler_scores_the_fit_and_the_balance_of_cpu_and_memory():
    text = (ROLES / 'hoover4_k3s/templates/scheduler-config.yaml.j2').read_text()
    profile = yaml.safe_load(text)['profiles'][0]
    weights = {p['name']: p['weight'] for p in profile['plugins']['score']['enabled']}
    assert weights == {'NodeResourcesFit': 10, 'NodeResourcesBalancedAllocation': 10, 'NodeAffinity': 50}
    # The planned node of the site placement (a preferred node affinity) wins over the sum of the resource scores.
    assert weights['NodeAffinity'] * 100 > (weights['NodeResourcesFit'] + weights['NodeResourcesBalancedAllocation']) * 100
    args = {c['name']: c['args'] for c in profile['pluginConfig']}
    assert args['NodeResourcesFit']['scoringStrategy']['resources'] == [{'name': 'cpu', 'weight': 1}, {'name': 'memory', 'weight': 1}]
    assert args['NodeResourcesBalancedAllocation']['resources'] == [{'name': 'cpu', 'weight': 1}, {'name': 'memory', 'weight': 1}]
    assert yaml.safe_load(text)['clientConnection']['kubeconfig'].endswith('/scheduler.kubeconfig')
    # Agents get no scheduler argument.
    assert 'kube-scheduler-arg' not in render('config.yaml.j2', host_vars(site_text('remote.yml'), 'worker-b'))


def test_the_backup_step_gives_the_folders_to_the_pod_user_and_writes_the_marker_only_on_a_mounted_folder():
    sys.path.insert(0, str(K3S / 'platform' / 'backups'))
    import schedule
    tasks = {t['name']: t for t in yaml.safe_load((ROLES / 'hoover4_host/tasks/backup.yml').read_text())}
    folders, marker = tasks['Create the backup folders'], tasks['Write the marker of the backup destination']
    owned = tasks['Give the copies to the user of the operator pod']
    assert marker['ansible.builtin.copy']['dest'].endswith('/' + schedule.MARKER)
    for task in (folders, owned):
        assert task['ansible.builtin.file']['owner'] == task['ansible.builtin.file']['group'] == '{{ hoover4_backup_uid }}'
    assert folders['ansible.builtin.file']['mode'] == '0700' and 'mode' not in owned['ansible.builtin.file']
    assert '{{ hoover4_backup_path }}/staging' in tasks['Read the backup folders']['loop']
    # A mount that the fstab names and that is missing gets no folder and no marker, so the jobs pause.
    ready = 'hoover4_backup_mounted.rc == 0 or hoover4_backup_fstab.rc != 0'
    assert folders['when'] == marker['when'] == owned['when'] == ready


def test_the_kubelet_stops_the_pods_at_a_host_shutdown_and_a_changed_file_restarts_k3s():
    kubelet = yaml.safe_load((ROLES / 'hoover4_k3s/templates/kubelet-hoover4.conf.j2').read_text())
    assert kubelet['shutdownGracePeriod'] == '150s' and kubelet['shutdownGracePeriodCriticalPods'] == '30s'
    assert kubelet['memorySwap'] == {'swapBehavior': 'NoSwap'}
    install = {t['name']: t for t in yaml.safe_load((ROLES / 'hoover4_k3s/tasks/install.yml').read_text())}
    assert 'hoover4_kubelet_dropin.changed' in install['Decide the install']['ansible.builtin.set_fact']['hoover4_k3s_install']
    assert install['Wait for the shutdown lock of the kubelet']['until'] == "'kubelet' in hoover4_kubelet_inhibit.stdout"
