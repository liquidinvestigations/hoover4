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
    assert 'ln -sfn "$link" /etc/rancher/k3s/k3s.yaml' in script
    assert "sed -i '\\# /var/lib/kubelet #d' /etc/fstab" in script
    assert 'rm -rf /srv' not in script and 'hoover-operator' not in script.split('set -eu')[1]
    # vgremove stays a comment, because another volume can use the group.
    assert '\nvgremove' not in script and '# Remove the group only when lvs shows no other volume' in script
    (tmp_path / 'claims/a.tar').write_bytes(b'changed')
    assert lr.verify(tmp_path)['differences'] == ['claims/a.tar']
