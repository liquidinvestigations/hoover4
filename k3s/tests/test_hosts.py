"""The host scripts: the k3s configuration of servers and agents, etcd, the VPN interface, the tokens and the GPU runtime.

The tests load the root scripts as modules and replace their file writes and paths. No test runs a root command.
"""
import importlib.util
import os

import pytest

from conftest import K3S, site_text
import config


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_').removesuffix('.py'), K3S / 'hosts' / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REMOTE_GPU = site_text('remote.ini').replace('architecture = arm64\n', 'architecture = arm64\nvpn_interface = prototype-vpn\n')


@pytest.fixture
def k3s(tmp_path, monkeypatch):
    """root-install-k3s.py with a staged folder and its server data below tmp_path. write_file records the files."""
    module = load('root-install-k3s.py')
    staged = tmp_path / 'staged'
    staged.mkdir()
    (staged / 'server-token').write_text('s' * 64 + '\n')
    (staged / 'agent-token').write_text('a' * 64 + '\n')
    monkeypatch.setattr(module, 'STAGED', str(staged))
    monkeypatch.setattr(module, 'SERVER_DIR', str(tmp_path / 'server'))
    monkeypatch.setattr(module, 'DB_DIR', str(tmp_path / 'server/db'))
    monkeypatch.setattr(module, 'K3S_DIR', str(tmp_path / 'etc'))
    written = {}
    monkeypatch.setattr(module, 'write_file', lambda path, text, mode=0o644, secret=False: written.__setitem__(path, text))
    module.written = written
    module.tmp = tmp_path

    def use(text, node):
        module.use_site(config.legacy_hosts(config.parse(text)), node)
        written.clear()
        module.k3s_config()
        return written[f'{tmp_path}/etc/config.yaml']
    module.use = use
    return module


def test_every_server_initializes_etcd_and_no_agent_does(k3s):
    single = k3s.use(site_text('single-node.ini'), 'dev')
    assert 'cluster-init: true' in single.splitlines()
    assert 'flannel-iface: hoover4' in single and 'flannel-backend: host-gw' in single
    server = k3s.use(site_text('remote.ini'), 'server-a')
    assert 'cluster-init: true' in server.splitlines() and 'flannel-iface: wg0' in server
    assert 'datastore-endpoint' not in server
    agent = k3s.use(site_text('remote.ini'), 'worker-b')
    assert 'cluster-init' not in agent
    assert 'server: https://10.0.0.2:6443' in agent and f'token-file: {k3s.tmp}/etc/agent-token' in agent


def test_a_gpu_node_keeps_its_own_vpn_interface(k3s):
    gpu = k3s.use(REMOTE_GPU, 'gpu-1')
    assert 'flannel-iface: prototype-vpn' in gpu
    assert 'node-ip: 10.0.0.5' in gpu and 'hoover.dev/gpu=true:NoSchedule' in gpu
    assert k3s.interface(config.legacy_hosts(config.parse(REMOTE_GPU))['hosts']['gpu-1']) == 'prototype-vpn'
    hosts = load('root-install.py')
    hosts.use_interface('prototype-vpn')
    assert hosts.WG_CONF == '/etc/wireguard/prototype-vpn.conf'


@pytest.fixture
def wireguard(tmp_path, monkeypatch):
    """root-install.py as server-a of REMOTE_GPU, where gpu-1 has no public key, with a fake wg and wg-quick."""
    module = load('root-install.py')
    hosts = config.legacy_hosts(config.parse(REMOTE_GPU))['hosts']
    monkeypatch.setattr(module, 'HOSTS', hosts)
    monkeypatch.setattr(module, 'THIS', 'server-a')
    monkeypatch.setattr(module, 'DRY', False)
    conf = tmp_path / 'wg0.conf'
    conf.write_text('[Interface]\nPrivateKey = private\nListenPort = %d\n' % hosts['server-a']['port'])
    monkeypatch.setattr(module, 'WG_CONF', str(conf))
    monkeypatch.setattr(module.tempfile, 'mkdtemp', lambda **kw: str(tmp_path / 'check'), raising=True)
    (tmp_path / 'check').mkdir()
    module.events = []
    module.strip_code = 0

    def read(cmd):
        if cmd[:3] == ['wg', 'show', 'wg0'] and cmd[3] == 'public-key':
            return 0, hosts['server-a']['key'] + '\n'
        if cmd[0] == 'wg-quick':
            module.events.append(('strip', open(cmd[2]).read()))
            return module.strip_code, 'stripped\n' if module.strip_code == 0 else 'Line unrecognized'
        return 0, ''
    monkeypatch.setattr(module, 'read', read)
    monkeypatch.setattr(module, 'change', lambda cmd, **kw: module.events.append(('change', cmd)) or '')
    monkeypatch.setattr(module, 'write_file', lambda path, text, **kw: module.events.append(('write', path, text)))
    monkeypatch.setattr(module, 'verify_peers', lambda: None)
    return module


def test_a_peer_without_a_public_key_gets_no_peer_block(wireguard):
    blocks = wireguard.peer_blocks(open(wireguard.WG_CONF).read())
    text = '\n'.join(blocks)
    assert 'worker-b-public-key' in text and 'edge-public-key' in text
    assert 'gpu-1' not in text and all(line.strip() != 'PublicKey =' for line in blocks)


def test_the_new_interface_file_is_checked_before_it_is_written(wireguard):
    wireguard.step_wireguard()
    kinds = [e[0] for e in wireguard.events]
    assert kinds == ['strip', 'change', 'write']
    assert 'worker-b-public-key' in wireguard.events[0][1] and wireguard.events[1][1][:2] == ['wg', 'syncconf']


def test_a_refused_interface_file_changes_nothing(wireguard):
    wireguard.strip_code = 1
    with pytest.raises(SystemExit):
        wireguard.step_wireguard()
    assert [e[0] for e in wireguard.events] == ['strip']


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
        '[node.gpu-1] keeps its VPN interface prototype-vpn. Add a peer for edge on that interface by hand: the public '
        'key of edge, its endpoint, and AllowedIPs 10.0.0.1/32.']
    # Without wireguard_peers no node adds a direct peer for gpu-1, because no reverse peer exists there.
    plain = config.parse(REMOTE_GPU)
    assert all('gpu-1' not in h['peers'] for h in config.legacy_hosts(plain)['hosts'].values())
    assert config.manual_peers(plain) == []


def test_the_direct_peer_for_a_node_behind_nat_has_no_endpoint(wireguard, monkeypatch):
    hosts = config.legacy_hosts(config.parse(PEERED_GPU))['hosts']
    monkeypatch.setattr(wireguard, 'HOSTS', hosts)
    monkeypatch.setattr(wireguard, 'THIS', 'edge')
    blocks = wireguard.peer_blocks('[Interface]\n')
    block = blocks[blocks.index('PublicKey = gpu-1-public-key') - 1:]
    block = block[:block.index('') if '' in block else len(block)]
    assert 'AllowedIPs = 10.0.0.5/32' in block and not any(line.startswith('Endpoint') for line in block)


def test_the_wireguard_step_adds_routed_addresses_and_removes_none(wireguard, monkeypatch):
    hosts = config.legacy_hosts(config.parse(ROUTED))['hosts']
    monkeypatch.setattr(wireguard, 'HOSTS', hosts)
    # server-a has a hub peer for the whole range and a peer for edge from an earlier run.
    text = ('[Interface]\nPrivateKey = private\nListenPort = %d\n\n[Peer]\nPublicKey = hub-key\nAllowedIPs = 10.0.0.0/24\n\n'
            '[Peer]\nPublicKey = edge-public-key\nAllowedIPs = 10.0.0.1/32\n' % hosts['server-a']['port'])
    open(wireguard.WG_CONF, 'w').write(text)
    wireguard.step_wireguard()
    written = [e for e in wireguard.events if e[0] == 'write'][0][2]
    assert 'AllowedIPs = 10.0.0.0/24\n' in written
    assert 'AllowedIPs = 10.0.0.1/32, 10.0.0.4/32\n' in written
    assert 'calls-public-key' not in written and 'PublicKey = worker-b-public-key' in written
    # On calls the new peer for edge carries the addresses that edge forwards.
    monkeypatch.setattr(wireguard, 'THIS', 'calls')
    blocks = '\n'.join(wireguard.peer_blocks('[Interface]\n'))
    assert blocks.count('[Peer]') == 1
    assert 'AllowedIPs = 10.0.0.1/32, 10.0.0.2/32, 10.0.0.3/32' in blocks


def test_the_vpn_interface_must_be_a_valid_name():
    with pytest.raises(config.SiteError, match='is not a network interface name'):
        config.parse(site_text('remote.ini').replace('architecture = arm64\n', 'architecture = arm64\nvpn_interface = a b\n'))
    site = config.parse(REMOTE_GPU)
    assert config.parse(config.dump(site)) == site


def test_an_existing_server_keeps_its_token(k3s):
    k3s.use(site_text('remote.ini'), 'server-a')
    assert k3s.token_problems() == []
    server = k3s.tmp / 'server'
    server.mkdir()
    (server / 'token').write_text('K10abc::server:' + 's' * 64 + '\n')
    # A full token and its secret are the same token. The agent token of a server without one is the server token.
    problems = k3s.token_problems()
    assert problems == ['the staged agent-token differs from the agent token of this server']
    (server / 'agent-token').write_text('K10abc::node:' + 'a' * 64 + '\n')
    assert k3s.token_problems() == []
    (server / 'token').write_text('K10abc::server:other\n')
    assert k3s.token_problems() == ['the staged server-token differs from the token of this server']


def test_an_existing_agent_keeps_its_token(k3s, monkeypatch):
    k3s.use(site_text('remote.ini'), 'worker-b')
    (k3s.tmp / 'etc').mkdir()
    (k3s.tmp / 'etc/agent-token').write_text('b' * 64 + '\n')
    assert k3s.token_problems() == ['the staged agent-token differs from the token in agent-token']


def test_the_datastore_of_the_server_folder(k3s):
    db = k3s.tmp / 'server/db'
    assert k3s.datastore() == 'none'
    db.mkdir(parents=True)
    (db / 'state.db').write_text('')
    assert k3s.datastore() == 'sqlite'
    (db / 'etcd/member').mkdir(parents=True)
    assert k3s.datastore() == 'etcd'


def test_the_patched_gpu_runtime_is_optional(k3s):
    k3s.use(REMOTE_GPU, 'gpu-1')
    # No staged runsc-nvproxy: the handler uses the runsc of the gVisor release, and the script does not stop.
    assert 'binary_name = "/opt/gvisor/runsc"' in k3s.runsc_nvproxy_toml()
    patched = k3s.tmp / 'staged/runsc-nvproxy'
    patched.mkdir()
    (patched / 'runsc').write_text('binary')
    assert 'binary_name = "/opt/gvisor-nvproxy/runsc"' in k3s.runsc_nvproxy_toml()


def test_the_sqlite_copy_verifies_before_the_conversion(k3s, monkeypatch):
    k3s.use(site_text('remote.ini'), 'server-a')
    db = k3s.tmp / 'server/db'
    db.mkdir(parents=True)
    (db / 'state.db').write_bytes(os.urandom(4096))
    (k3s.tmp / 'server/token').write_text('K10abc::server:' + 's' * 64 + '\n')
    (k3s.tmp / 'etc').mkdir()
    (k3s.tmp / 'etc/config.yaml').write_text('node-name: server-a\n')
    commands = []
    monkeypatch.setattr(k3s, 'run', lambda cmd, env=None, check=True: commands.append(cmd) or '')
    target = k3s.preserve_sqlite(k3s.tmp / 'recovery')
    assert commands == [['systemctl', 'stop', 'k3s']]
    sums = open(os.path.join(target, 'SHA256SUMS')).read()
    assert 'db/state.db' in sums and 'server/token' in sums and 'etc/config.yaml' in sums
    assert oct(os.stat(target).st_mode & 0o777) == '0o700'


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


def test_an_install_after_the_sqlite_copy_starts_the_stopped_server(k3s, monkeypatch):
    # install-k3s.sh skips the start when its unit file is unchanged, so the script restarts the unit itself.
    k3s.use(site_text('remote.ini'), 'server-a')
    commands = []
    monkeypatch.setattr(k3s, 'run', lambda cmd, env=None, check=True: commands.append(cmd) or '')
    monkeypatch.setattr(k3s, 'staged', lambda name: str(k3s.tmp / 'staged' / name))
    monkeypatch.setattr(k3s.subprocess, 'run', lambda *a, **kw: type('R', (), {'returncode': 3})())
    assert k3s.install_k3s() == 'k3s'
    assert commands[-1] == ['systemctl', 'restart', 'k3s']


@pytest.mark.parametrize('script', ['root-install-k3s.py', 'root-install.py', 'root-install-local.py'])
def test_the_root_scripts_accept_names_and_refuse_paths_and_links_out_of_their_folder(script, tmp_path):
    module = load(script)
    assert module.name_arg('5885ba402618') == '5885ba402618'
    for value in ('/etc', '../x', 'a/b', '..', '.', '.hidden', '', 'a b', 'x;rm'):
        with pytest.raises(SystemExit):
            module.name_arg(value)
    home = tmp_path / 'home'
    (home / 'k3s-install' / 'rev').mkdir(parents=True)
    assert module.below(str(home), 'k3s-install/rev') == str(home / 'k3s-install' / 'rev')
    for relative in ('/etc/passwd', '../outside', 'k3s-install/../../outside', 'k3s-install//rev', ''):
        with pytest.raises(SystemExit):
            module.below(str(home), relative)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (home / 'k3s-install' / 'escape').symlink_to(outside)
    (home / 'k3s-install' / 'inner').symlink_to(home / 'k3s-install' / 'rev')
    for relative in ('k3s-install/escape', 'k3s-install/escape/hosts.json', 'k3s-install/inner'):
        with pytest.raises(SystemExit):
            module.below(str(home), relative)


def test_the_k3s_script_finds_the_bundle_and_snapshots_by_name(tmp_path, monkeypatch, capsys):
    module = load('root-install-k3s.py')
    user = type('User', (), {'pw_dir': str(tmp_path), 'pw_name': 'operator'})()
    (tmp_path / 'k3s-install' / 'snapshots').mkdir(parents=True)
    assert module.install_folder(user, 'abc') == str(tmp_path / 'k3s-install' / 'abc')
    assert module.install_folder(user, 'snapshots', 'platform-1') == str(tmp_path / 'k3s-install/snapshots/platform-1')
    with pytest.raises(SystemExit):
        module.install_folder(user, 'snapshots', '../../etc')
    monkeypatch.setenv('SUDO_USER', 'alice')
    monkeypatch.setattr(module.os, 'geteuid', lambda: 0)
    with pytest.raises(SystemExit):
        module.operator_user('bob')
    assert 'differs from the user alice' in capsys.readouterr().out
