"""The host steps: the Ansible inventory of the site file, the k3s configuration of servers and agents, the WireGuard
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

from conftest import K3S, site_text
import config

ROLES = K3S / 'ansible' / 'roles'
REMOTE_GPU = site_text('remote.ini').replace('architecture = arm64\n', 'architecture = arm64\nvpn_interface = wg-site\n')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def host_vars(text, node, state='/state'):
    inventory = config.ansible_inventory(config.parse(text), state)['all']
    return {**inventory['vars'], **inventory['children']['hoover4']['hosts'][node], 'inventory_hostname': node,
            'hoover4_kata': inventory['children']['hoover4']['hosts'][node]['hoover4_architecture'] == 'amd64'
            and not inventory['children']['hoover4']['hosts'][node]['hoover4_gpu']}


def render(template, values):
    # Ansible renders templates with trim_blocks, and the filter bool of Ansible keeps a bool.
    environment = jinja2.Environment(trim_blocks=True, undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    environment.filters['bool'] = bool
    return environment.from_string((ROLES / 'hoover4_k3s/templates' / template).read_text()).render(**values)


def test_every_server_initializes_etcd_and_no_agent_does():
    server = render('config.yaml.j2', host_vars(site_text('remote.ini'), 'server-a'))
    agent = render('config.yaml.j2', host_vars(site_text('remote.ini'), 'worker-b'))
    assert 'cluster-init: true\n' in server and 'agent-token-file: /etc/rancher/k3s/agent-token\n' in server
    assert 'cluster-init' not in agent and agent.startswith('server: https://10.0.0.2:6443\ntoken-file: /etc/rancher/k3s/agent-token\n')
    assert 'node-ip: 10.0.0.3\nflannel-iface: wg0\n' in agent


def test_the_configuration_of_a_lan_server_keeps_the_bytes_of_the_earlier_installer():
    # The earlier root script wrote this file on a LAN server. The same bytes keep k3s running without a restart.
    text = site_text('remote.ini')
    values = host_vars(text, 'server-a') | {'hoover4_node_address': '192.0.2.25', 'hoover4_flannel_iface': 'enp3s0',
                                            'inventory_hostname': 'lan-3', 'hoover4_reserved': ''}
    assert render('config.yaml.j2', values) == """# The server keeps its datastore in embedded etcd, also on a site with one node. etcd gives the snapshots of
# the platform backup. One server is not highly available.
cluster-init: true
advertise-address: 192.0.2.25
tls-san:
  - 192.0.2.25
flannel-backend: vxlan
token-file: /etc/rancher/k3s/token
agent-token-file: /etc/rancher/k3s/agent-token
write-kubeconfig-mode: "0600"
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
    values = host_vars(REMOTE_GPU, 'gpu-1')
    assert values['hoover4_flannel_iface'] == 'wg-site' and 'hoover4_wireguard' not in values
    text = render('config.yaml.j2', values)
    assert 'node-taint:\n  - hoover.dev/gpu=true:NoSchedule\n' in text
    runtimes = render('runtimes.toml.j2', values)
    assert 'runtimes.runsc-nvproxy]' in runtimes and 'runtimes.kata]' not in runtimes
    assert 'runtimes.kata]' in render('runtimes.toml.j2', host_vars(REMOTE_GPU, 'server-a'))


def test_the_inventory_connects_with_the_ssh_address_and_keeps_the_state_paths(tmp_path):
    inventory = config.ansible_inventory(config.parse(site_text('remote.ini')), tmp_path)['all']
    assert inventory['vars']['hoover4_kubeconfig'] == str(tmp_path / 'kubeconfig')
    assert inventory['vars']['hoover4_tokens_dir'] == str(tmp_path / 'staging/tokens')
    hosts = inventory['children']['hoover4']['hosts']
    assert inventory['children']['hoover4_server']['hosts'] == {'server-a': {}}
    assert 'server-a' not in inventory['children']['hoover4_agents']['hosts']
    assert hosts['server-a']['hoover4_convert_sqlite'] is True and hosts['worker-b']['hoover4_convert_sqlite'] is False
    assert inventory['hosts']['localhost']['ansible_connection'] == 'local'
    local = config.ansible_inventory(config.parse(site_text('single-node.ini')), tmp_path)['all']['children']['hoover4']
    assert local['hosts']['dev']['ansible_host'] == 'localhost' and local['hosts']['dev']['hoover4_single_local'] is True


# calls sits on another LAN. It peers only with the public node edge, and the other nodes reach it through edge.
ROUTED = site_text('remote.ini').replace('public_address = 203.0.113.11\n',
                                         'public_address = 203.0.113.11\nwireguard_public_key = calls-public-key\n'
                                         'wireguard_peers = edge\nwireguard_via = edge\n')
# gpu-1 keeps its VPN interface and names edge as its direct peer. The person adds the reverse peer on gpu-1.
PEERED_GPU = REMOTE_GPU.replace('gpu_api_key_file = /root/vllm-key\n',
                                'gpu_api_key_file = /root/vllm-key\nwireguard_public_key = gpu-1-public-key\n'
                                'wireguard_peers = edge\n')


def test_a_node_with_wireguard_peers_gets_direct_peers_only_with_them():
    hosts = config.legacy_hosts(config.parse(ROUTED))['hosts']
    assert hosts['calls']['peers'] == ['edge']
    assert 'calls' in hosts['edge']['peers'] and 'calls' not in hosts['server-a']['peers']
    # The nodes without the key keep the full mesh among themselves. gpu-1 keeps its own VPN and names no peers.
    assert set(hosts['server-a']['peers']) == {'worker-b', 'edge'}
    # Each side routes the other through edge, and edge only forwards.
    assert hosts['server-a']['routes'] == {'edge': ['10.0.0.4/32']}
    assert hosts['calls']['routes'] == {'edge': ['10.0.0.2/32', '10.0.0.3/32']}
    assert hosts['edge']['routes'] == {}
    site = config.parse(ROUTED)
    assert config.parse(config.dump(site)) == site
    assert config.legacy_hosts(config.parse(site_text('remote.ini')))['hosts']['server-a']['routes'] == {}


def test_a_route_needs_direct_peers_with_the_forwarding_node():
    with pytest.raises(config.SiteError, match='have no direct peer'):
        config.parse(ROUTED.replace('wireguard_peers = edge\n', 'wireguard_peers = server-a\n'))
    with pytest.raises(config.SiteError, match='not another node of the site'):
        config.parse(ROUTED.replace('wireguard_peers = edge\n', 'wireguard_peers = edge, nowhere\n'))
    with pytest.raises(config.SiteError, match='has no direct peer for edge'):
        config.parse(ROUTED.replace('[node.worker-b]\n', '[node.worker-b]\nwireguard_peers = server-a\n'))


def test_a_node_that_keeps_its_vpn_gets_no_route_and_a_hand_made_reverse_peer():
    # The installer adds no interface on gpu-1, so it cannot add the routes there.
    with pytest.raises(config.SiteError, match='configures no WireGuard interface on this node'):
        config.parse(PEERED_GPU.replace('wireguard_peers = edge\n', 'wireguard_peers = edge\nwireguard_via = edge\n'))
    site = config.parse(PEERED_GPU)
    hosts = config.legacy_hosts(site)['hosts']
    # Only edge adds a direct peer for gpu-1. The other nodes keep the route of the existing VPN.
    assert 'gpu-1' in hosts['edge']['peers'] and 'gpu-1' not in hosts['server-a']['peers']
    assert config.manual_peers(site) == [
        '[node.gpu-1] keeps its VPN interface wg-site. Add a peer for edge on that interface by hand: the public '
        'key of edge, its endpoint, and AllowedIPs 10.0.0.1/32.']
    # Without wireguard_peers no node adds a direct peer for gpu-1, because no reverse peer exists there.
    plain = config.parse(REMOTE_GPU)
    assert all('gpu-1' not in h['peers'] for h in config.legacy_hosts(plain)['hosts'].values())
    assert config.manual_peers(plain) == []


def test_the_direct_peer_for_a_node_behind_nat_has_no_endpoint(tmp_path):
    values = host_vars(PEERED_GPU, 'edge')
    peer = next(p for p in values['hoover4_wireguard']['peers'] if p['name'] == 'gpu-1')
    assert peer == {'name': 'gpu-1', 'key': 'gpu-1-public-key', 'endpoint': '', 'allowed_ips': ['10.0.0.5/32']}
    block = wireguard_module().peer_blocks('[Interface]\n', [peer])
    assert 'AllowedIPs = 10.0.0.5/32' in block and not any(line.startswith('Endpoint') for line in block)


def wireguard_module():
    return load(ROLES / 'hoover4_wireguard/library/hoover4_wireguard_peers.py', 'hoover4_wireguard_peers')


def test_the_wireguard_peers_add_routed_addresses_and_remove_none():
    wg = wireguard_module()
    values = host_vars(ROUTED, 'server-a')['hoover4_wireguard']
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
    peers = host_vars(ROUTED, 'calls')['hoover4_wireguard']['peers']
    blocks = '\n'.join(wg.peer_blocks('[Interface]\n', peers))
    assert blocks.count('[Peer]') == 1 and 'AllowedIPs = 10.0.0.1/32, 10.0.0.2/32, 10.0.0.3/32' in blocks


def test_the_vpn_interface_must_be_a_valid_name():
    with pytest.raises(config.SiteError, match='is not a network interface name'):
        config.parse(site_text('remote.ini').replace('architecture = arm64\n', 'architecture = arm64\nvpn_interface = a b\n'))
    site = config.parse(REMOTE_GPU)
    assert config.parse(config.dump(site)) == site


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
                 'volume_group': {'name': 'hoover4', 'physical_volumes': ['/dev/nvme2n1p2']}}
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


