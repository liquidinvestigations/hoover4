"""The driver suite: the plans, records, revisions, interruptions, host adapters, render and check of deploy-k3s.

Fake ssh, sudo, bash and kubectl commands on PATH stand in for the hosts and the cluster. No test contacts a host.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import K3S, FIXTURES, site_text

sys.path.insert(0, str(K3S / 'driver'))
import config  # noqa: E402
import deploy  # noqa: E402
import records  # noqa: E402

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
name = os.path.basename(sys.argv[0])
log = os.environ['FAKE_LOG']
with open(log, 'a') as f:
    f.write(json.dumps([name] + sys.argv[1:]) + '\n')
args = sys.argv[1:]
if name == 'ssh':
    mode = os.environ.get('FAKE_SSH', 'down')
    if mode == 'down':
        print('ssh: connect to host 192.0.2.11 port 22: Connection timed out', file=sys.stderr)
        sys.exit(255)
    release = {'ubuntu': 'ID=ubuntu\nID_LIKE=debian\n', 'rhel': 'ID="rhel"\n'}[mode.split('-')[0]]
    machine = 'aarch64' if mode.endswith('arm') else 'x86_64'
    print(release + '==\n' + machine + '\n==\nsudo-ok')
    sys.exit(0)
if name == 'sudo':
    sys.exit(0)
if name == 'kubectl':
    state_path = os.environ.get('FAKE_KUBE')
    state = json.load(open(state_path)) if state_path and os.path.exists(state_path) else {}
    if '--kubeconfig' in args:
        i = args.index('--kubeconfig'); del args[i:i + 2]
    ns = None
    if '-n' in args:
        i = args.index('-n'); ns = args[i + 1]; del args[i:i + 2]
    kinds = {'deployment': 'Deployment', 'statefulset': 'StatefulSet'}
    if args[:2] == ['get', 'node']:
        if not os.environ.get('FAKE_READY'):
            sys.exit(1)
        print(args[2] + ' Ready control-plane 1d v1.36.5')
        sys.exit(0)
    if args[:2] == ['get', 'deployments,statefulsets']:
        print(json.dumps({'items': [{'kind': k, 'metadata': {'name': n}, 'spec': {'replicas': r}}
                                    for (k, n), r in ((tuple(key.split('/')), v) for key, v in state.get(ns, {}).items())]}))
        sys.exit(0)
    if args[0] == 'scale':
        state.setdefault(ns, {})[f'{kinds[args[1]]}/{args[2]}'] = int(args[3].split('=')[1])
        json.dump(state, open(state_path, 'w'))
        sys.exit(0)
    if args[0] == 'get' and len(args) >= 3:
        print(state.get(ns, {}).get(f'{kinds[args[1]]}/{args[2]}', 0))
        sys.exit(0)
    sys.exit(0)
sys.exit(0)
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A site, a private folder, a git repository and fake commands."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name in ('ssh', 'sudo', 'kubectl', 'bash', 'podman'):
        path = bin_dir / name
        path.write_text(FAKE)
        path.chmod(0o755)
    log = tmp_path / 'commands.log'
    log.touch()
    monkeypatch.setenv('PATH', f'{bin_dir}:{os.environ["PATH"]}')
    monkeypatch.setenv('FAKE_LOG', str(log))
    monkeypatch.setenv('FAKE_KUBE', str(tmp_path / 'kube.json'))
    monkeypatch.delenv('FAKE_READY', raising=False)
    repo = tmp_path / 'repo'
    repo.mkdir()
    git = ['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.org']
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / 'file.txt').write_text('one\n')
    subprocess.run(git + ['add', 'file.txt'], check=True)
    subprocess.run(git + ['commit', '-q', '-m', 'one'], check=True)
    private = tmp_path / 'private'
    private.mkdir()

    def make(fixture='single-node.ini', extra=''):
        state = tmp_path / 'state'
        text = site_text(fixture).replace('[site]\n', f'[site]\nstate_path = {state}\n', 1) + extra
        site_path = tmp_path / 'site.ini'
        site_path.write_text(text)
        site = config.parse(text)
        ctx = deploy.Context(site_path, site, private=private, repo=repo)
        ctx.kubeconfig = private / 'kubeconfig'
        return ctx

    class Env:
        pass
    e = Env()
    e.tmp, e.make, e.repo, e.git, e.private, e.log = tmp_path, make, repo, git, private, log
    e.commands = lambda: [json.loads(line) for line in log.read_text().splitlines()]
    return e


def fake_steps(names, calls, fail=(), interrupt=()):
    def make(name):
        def run(ctx):
            calls.append((name, ctx.revision, os.environ.get('HOOVER4_REVISION') or ctx.env().get('HOOVER4_REVISION')))
            if name in interrupt:
                interrupt.remove(name)
                raise KeyboardInterrupt
            if name in fail:
                raise deploy.StepFailed(f'{name} broke')
            return {}
        return run
    return {n: make(n) for n in names}


def test_up_plan_puts_hosts_registry_images_and_zones_in_order(env):
    ctx = env.make()
    steps = list(deploy.plan(ctx, 'up', ['dev']))
    assert steps[:7] == ['host:dev:prerequisites', 'host:dev:software', 'host:dev:settings', 'host:dev:storage',
                         'host:dev:stage', 'host:dev:k3s', 'host:dev:dns']
    for before, after in (('host:dev:k3s', 'cluster'), ('tools', 'registry'), ('registry', 'images'),
                          ('images', 'zone:zone-a'), ('ingress', 'frontend'), ('monitoring', 'operator'),
                          ('zone:zone-a', 'calls')):
        assert steps.index(before) < steps.index(after)
    assert steps[-1] == 'calls'


def test_remote_plan_puts_the_control_plane_first_and_gpu_nodes_last(env):
    ctx = env.make('remote.ini')
    steps = list(deploy.plan(ctx, 'up', ['gpu-1', 'edge', 'server-a']))
    hosts = [s.split(':')[1] for s in steps if s.startswith('host:')]
    assert hosts == ['server-a', 'server-a', 'edge', 'edge', 'gpu-1', 'gpu-1']
    assert 'cluster' in steps
    # Without the control plane the driver runs no cluster step.
    assert all(s.startswith('host:') for s in deploy.plan(ctx, 'up', ['edge']))


def test_revision_is_resolved_once_and_a_resume_keeps_it(env):
    ctx = env.make()
    first = deploy.resolve_revision(env.repo, 'HEAD')
    names = ['a', 'b', 'c']
    calls = []
    record = ctx.records.new('up', ['dev'], first, names, complete=True)
    assert deploy.execute(ctx, record, fake_steps(names, calls, interrupt=['b'])) == 130
    (env.repo / 'file.txt').write_text('two\n')
    subprocess.run(env.git + ['commit', '-q', '-am', 'two'], check=True)
    assert deploy.resolve_revision(env.repo, 'HEAD') != first
    record = ctx.records.load(record['id'])
    assert record['status'] == 'interrupted'
    assert [s['state'] for s in record['steps']] == ['done', 'running', 'pending']
    assert deploy.execute(ctx, record, fake_steps(names, calls)) == 0
    assert [c[0] for c in calls] == ['a', 'b', 'b', 'c']
    assert {c[1] for c in calls} == {first} and {c[2] for c in calls} == {first}
    assert ctx.records.applied()['revision'] == first


def test_a_failed_update_keeps_the_applied_record_and_the_previous_one(env):
    ctx = env.make()
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    calls = []
    one = ctx.records.new('up', ['dev'], rev, ['a', 'b'], complete=True, images={'x': 'sha256:1'})
    one['images'] = {'registry.hoover.internal/hoover/x:1': 'sha256:1'}
    assert deploy.execute(ctx, one, fake_steps(['a', 'b'], calls)) == 0
    two = ctx.records.new('up', ['dev'], rev, ['a', 'b'], complete=True)
    assert deploy.execute(ctx, two, fake_steps(['a', 'b'], calls, fail=['b'])) == 2
    failed = ctx.records.load(two['id'])
    assert failed['status'] == 'failed' and failed['error'] == 'b: b broke'
    assert ctx.records.applied()['id'] == one['id']
    assert ctx.records.applied()['images'] == {'registry.hoover.internal/hoover/x:1': 'sha256:1'}
    assert deploy.execute(ctx, failed, fake_steps(['a', 'b'], calls)) == 0
    assert ctx.records.applied()['id'] == two['id'] and ctx.records.previous()['id'] == one['id']
    # The retry ran only the failed step.
    assert [c[0] for c in calls] == ['a', 'b', 'a', 'b', 'b']


def test_a_partial_up_is_not_an_applied_deployment(env):
    ctx = env.make()
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    record = ctx.records.new('up', ['dev'], rev, ['a'], complete=False)
    assert deploy.execute(ctx, record, fake_steps(['a'], [])) == 0
    assert ctx.records.applied() is None


def test_an_unreachable_remote_node_fails_with_its_name_and_a_resumable_record(env, monkeypatch):
    ctx = env.make('remote.ini')
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    steps = deploy.plan(ctx, 'up', ['worker-b'])
    record = ctx.records.new('up', ['worker-b'], rev, list(steps))
    assert deploy.execute(ctx, record, steps) == 2
    record = ctx.records.load(record['id'])
    assert record['status'] == 'failed'
    assert record['steps'][0]['state'] == 'failed'
    assert 'node worker-b: SSH to 192.0.2.11 failed with exit code 255' in record['error']
    assert 'Connection timed out' in record['error']
    monkeypatch.setenv('FAKE_SSH', 'rhel')
    assert deploy.execute(ctx, record, steps) == 3
    record = ctx.records.load(record['id'])
    assert [s['state'] for s in record['steps']] == ['done', 'waiting']
    assert record['status'] == 'waiting' and ctx.records.applied() is None


def test_remote_scripts_use_the_architecture_and_revision_and_refuse_a_dirty_checkout(env, monkeypatch):
    monkeypatch.setenv('FAKE_SSH', 'ubuntu-arm')
    ctx = env.make('remote.ini')
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    steps = deploy.plan(ctx, 'up', ['gpu-1'])
    record = ctx.records.new('up', ['gpu-1'], rev, list(steps))
    assert deploy.execute(ctx, record, steps) == 3
    folder = env.private / 'deploy/remote/gpu-1'
    install = (folder / 'install.sh').read_text()
    assert f'stage-k3s.sh arm64' in install and f'checkout --quiet {rev}' in install
    assert 'git status --porcelain' in install and 'exit 3' in install
    assert '(debian, arm64)' in install
    assert 'for step in software settings;' in install
    bootstrap = (folder / 'bootstrap.sh').read_text()
    sudoers = [line for line in bootstrap.splitlines() if 'NOPASSWD' in line]
    assert sudoers == ['operator ALL=(root) NOPASSWD: /usr/local/libexec/hoover4/root-install.py *',
                       'operator ALL=(root) NOPASSWD: /usr/local/libexec/hoover4/root-install-k3s.py *']
    project = json.loads((folder / 'project.json').read_text())
    assert project['secret_files'] == {'node.gpu-1.gpu_api_key_file': '/root/vllm-key'}
    assert 'hoovers' not in project
    # Only read-only SSH commands reached the node.
    ssh = [c for c in env.commands() if c[0] == 'ssh']
    assert ssh and all(c[-1].startswith('cat /etc/os-release') for c in ssh)
    # A Ready node finishes the waiting step on resume.
    monkeypatch.setenv('FAKE_READY', '1')
    (env.private / 'kubeconfig').write_text('fake')
    assert deploy.execute(ctx, ctx.records.load(record['id']), steps) == 0


def test_the_local_adapter_stages_the_architecture_of_the_node(env):
    ctx = env.make()
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    steps = deploy.select(deploy.plan(ctx, 'up', ['dev']), ['stage'])
    record = ctx.records.new('up', ['dev'], rev, list(steps))
    assert deploy.execute(ctx, record, steps) == 0
    bash = [c for c in env.commands() if c[0] == 'bash']
    assert bash[0][1].endswith('hosts/stage-k3s.sh') and bash[0][2] == 'amd64'
    assert (env.private / 'staging/amd64/server-token').stat().st_mode & 0o777 == 0o600


def test_render_and_check_change_no_file_and_run_no_root_command(env, monkeypatch):
    monkeypatch.setenv('FAKE_SSH', 'rhel')
    ctx = env.make('remote.ini')
    before = sorted(p for p in env.tmp.rglob('*') if 'commands.log' not in str(p))
    out = deploy.render(ctx, ['server-a', 'worker-b'], deploy.resolve_revision(env.repo, 'HEAD'))
    assert out['up'][0] == 'host:server-a:probe' and out['down'][-1] == 'stop:k3s:server-a'
    problems, state = deploy.check(ctx, ['server-a', 'worker-b'])
    after = sorted(p for p in env.tmp.rglob('*') if 'commands.log' not in str(p))
    assert before == after
    assert not [c for c in env.commands() if c[0] == 'sudo']
    assert state['worker-b']['family'] == 'rhel'
    assert any('the operator tools are missing' in p for p in problems)


def test_a_dirty_checkout_stays_unchanged_and_the_record_names_its_files(env):
    (env.repo / 'file.txt').write_text('local change\n')
    ctx = env.make()
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    record = ctx.records.new('up', ['dev'], rev, ['a'], checkout_changes=deploy.dirty_files(env.repo))
    assert deploy.execute(ctx, record, fake_steps(['a'], [])) == 0
    assert (env.repo / 'file.txt').read_text() == 'local change\n'
    assert ctx.records.load(record['id'])['checkout_changes'] == ['file.txt']
    assert not [c for c in env.commands() if c[0] == 'git']


def test_a_second_driver_waits_for_the_lock(env):
    ctx = env.make()
    other = deploy.Context(ctx.site_path, ctx.site, private=env.private, repo=env.repo)
    ctx.records.lock()
    with pytest.raises(records.Busy):
        other.records.lock()
    ctx.records.unlock()
    other.records.lock()
    other.records.unlock()


def test_down_stops_the_tiers_in_order_and_start_restores_them(env):
    ctx = env.make()
    (env.tmp / 'kube.json').write_text(json.dumps({
        'ingress': {'Deployment/haproxy-ingress': 1},
        'zone-a': {'Deployment/zone-a-gate': 1, 'Deployment/nextcloud': 1, 'StatefulSet/postgresql': 1},
        'hoover-zone-a': {'Deployment/website': 2, 'StatefulSet/hoover-workers': 2, 'Deployment/temporal': 1,
                          'StatefulSet/temporal-cassandra': 1, 'StatefulSet/clickhouse': 1},
    }))
    (env.private / 'kubeconfig').write_text('fake')
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    steps = deploy.plan(ctx, 'down', ['dev'])
    assert list(steps) == ['stop:ingress', 'stop:applications', 'stop:temporal', 'stop:stores', 'stop:k3s:dev']
    record = ctx.records.new('down', ['dev'], rev, list(steps))
    assert deploy.execute(ctx, record, steps) == 0
    scaled = [c[c.index('scale') + 2] for c in env.commands() if c[0] == 'kubectl' and 'scale' in c]
    assert scaled == ['zone-a-gate', 'nextcloud', 'website', 'hoover-workers', 'temporal',
                      'haproxy-ingress', 'postgresql', 'temporal-cassandra', 'clickhouse']
    assert ctx.records.stopped()['hoover-zone-a/deployment/website'] == 2
    sudo = [c for c in env.commands() if c[0] == 'sudo']
    assert ['sudo', '-n', '/usr/bin/systemctl', 'stop', 'k3s.service'] in sudo
    assert sudo[-1][-1] == '/usr/local/bin/k3s-killall.sh'
    log = env.log.read_text()
    env.log.write_text('')
    os.environ['FAKE_READY'] = '1'
    try:
        start = deploy.plan(ctx, 'up', ['dev'], start=True)
        record = ctx.records.new('up', ['dev'], rev, list(start), start=True)
        assert deploy.execute(ctx, record, start) == 0
    finally:
        del os.environ['FAKE_READY']
    scaled = [(c[c.index('scale') + 2], c[-1]) for c in env.commands() if c[0] == 'kubectl' and 'scale' in c]
    assert [s[0] for s in scaled] == ['clickhouse', 'temporal-cassandra', 'haproxy-ingress', 'postgresql', 'temporal',
                                      'website', 'hoover-workers', 'nextcloud', 'zone-a-gate']
    assert ('website', '--replicas=2') in scaled
    assert ctx.records.stopped() == {}
    assert ctx.records.applied() is None
    assert 'temporal' in log


def test_the_local_bootstrap_names_only_the_root_scripts_units_and_kill_script(env, monkeypatch):
    monkeypatch.setenv('USER', 'gabriel')
    ctx = env.make()
    text = deploy.write_local_bootstrap(ctx, ctx.site.nodes['dev']).read_text()
    rules = [line for line in text.splitlines() if 'NOPASSWD' in line]
    assert all(r.startswith('gabriel ALL=(root) NOPASSWD: ') for r in rules)
    commands = {r.split('NOPASSWD: ', 1)[1] for r in rules}
    assert '/usr/local/libexec/hoover4/root-install-local.py *' in commands
    assert '/usr/bin/systemctl stop k3s.service' in commands
    assert not [c for c in commands if c in ('ALL', '/bin/sh', '/usr/bin/bash')]


def test_the_command_refuses_a_missing_or_unknown_target(env):
    ctx = env.make()
    cmd = [sys.executable, str(K3S / 'deploy-k3s'), 'up', '--site', str(ctx.site_path)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode != 0 and 'needs --target with nodes of the site: dev, or all' in out.stderr
    out = subprocess.run(cmd + ['--target', 'nope'], capture_output=True, text=True)
    assert 'nope is not a node of the site' in out.stderr


def test_the_os_family_of_the_adapters():
    assert deploy.os_family('NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\n') == 'arch'
    assert deploy.os_family('ID="rhel"\nID_LIKE="fedora"\n') == 'rhel'
    assert deploy.os_family('ID=ubuntu\nID_LIKE=debian\n') == 'debian'
    assert deploy.os_family('ID=alpine\n') == 'unknown'


def test_the_topolvm_values_follow_the_volume_groups_of_the_site():
    sys.path.insert(0, str(K3S / 'cluster'))
    import topolvm_values
    single, labels = topolvm_values.values(config.legacy_hosts(config.parse(site_text('single-node.ini'))))
    assert single['lvmd']['deviceClasses'] == [{'name': 'nvme', 'volume-group': 'hoover4', 'default': True, 'spare-gb': 10}]
    defaults = [c['name'] for c in single['storageClasses'] if c['storageClass']['isDefaultClass']]
    assert defaults == ['nvme-ext4']
    remote, labels = topolvm_values.values(config.legacy_hosts(config.parse(site_text('remote.ini'))))
    assert [c['name'] for c in remote['storageClasses'] if c['storageClass']['isDefaultClass']] == ['hdd-ext4']
    assert labels == {'edge': 'nvme.tier-nvme', 'server-a': 'hdd.tier-hdd', 'worker-b': 'hdd.tier-hdd'}
    assert len(remote['lvmd']['additionalConfigs']) == 1


def test_the_legacy_settings_of_a_single_node_site_use_the_local_address():
    values = config.legacy_settings(config.parse(site_text('single-node.ini')))
    assert values['registry_endpoint'] == f'{config.LOCAL_ADDRESS}:5000'
    assert values['frontend_bind'] == [config.LOCAL_ADDRESS] and values['frontend_local'] is True
    assert 'frontend_ssh' not in values
    remote = config.legacy_settings(config.parse(site_text('remote.ini')))
    assert remote['frontend_ssh'] == '203.0.113.10' and remote['registry_endpoint'] == '10.0.0.2:5000'
    assert remote['frontend_bind'] == ['10.0.0.1', '203.0.113.10']
