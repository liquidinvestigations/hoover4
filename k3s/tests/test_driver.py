"""The driver suite: the plans, records, revisions, interruptions, host steps, render and check of deploy-k3s.

Fake ssh, sudo, bash, kubectl and ansible-playbook commands on PATH stand in for the hosts and the cluster. No test contacts a host.
"""
import json
import shlex
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
    command = args[-1]
    if 'cat /etc/os-release' in command:
        release = {'ubuntu': 'ID=ubuntu\nID_LIKE=debian\n', 'rhel': 'ID="rhel"\n'}[mode.split('-')[0]]
        machine = 'aarch64' if '-arm' in mode else 'x86_64'
        rights = '' if '-nosudo' in mode else 'sudo-ok\n'
        print(release + '==\n' + machine + '\n==\n' + rights + 'home=/home/operator')
        sys.exit(0)
    if '--report' in command:
        print(open(os.environ['FAKE_REPORT']).read() if os.environ.get('FAKE_REPORT') else '{}')
        sys.exit(0)
    if command.startswith('systemctl is-active'):
        print(os.environ.get('FAKE_ACTIVE', 'active'))
        sys.exit(0)
    sys.stdin.read()
    sys.exit(0)
if name == 'sudo':
    sys.exit(0)
if name == 'ansible-playbook':
    if os.environ.get('FAKE_ANSIBLE') == 'fail':
        print('fatal: [edge]: UNREACHABLE! => {}')
        print('edge                       : ok=0    changed=0    unreachable=1    failed=0')
        sys.exit(4)
    print('PLAY RECAP')
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
        if '-o' in args:
            print(os.environ.get('FAKE_ETCD', 'true'))
            sys.exit(0)
        print(args[2] + ' Ready control-plane 1d v1.36.5')
        sys.exit(0)
    if args[:2] == ['get', 'namespace']:
        print(os.environ.get('FAKE_CLUSTER', ''))
        sys.exit(0)
    if args[:2] == ['get', 'deployments,statefulsets']:
        print(json.dumps({'items': [{'kind': k, 'metadata': {'name': n}, 'spec': {'replicas': r}}
                                    for (k, n), r in ((tuple(key.split('/')), v) for key, v in state.get(ns, {}).items())]}))
        sys.exit(0)
    if args[:2] == ['get', 'cronjobs']:
        print(json.dumps({'items': [{'metadata': {'name': n}, 'spec': {'suspend': v}}
                                    for n, v in state.get('cronjobs', {}).get(ns, {}).items()]}))
        sys.exit(0)
    if args[:2] == ['patch', 'cronjob']:
        state.setdefault('cronjobs', {}).setdefault(ns, {})[args[2]] = json.loads(args[-1])['spec']['suspend']
        json.dump(state, open(state_path, 'w'))
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
    for name in ('ssh', 'sudo', 'kubectl', 'bash', 'podman', 'ansible-playbook'):
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
    assert steps[:3] == ['hosts:prepare', 'hosts:k3s', 'hosts:verify']
    for before, after in (('hosts:verify', 'cluster'), ('tools', 'registry'), ('registry', 'images'),
                          ('images', 'zone:zone-a'), ('ingress', 'frontend'), ('monitoring', 'operator'),
                          ('zone:zone-a', 'calls'), ('zone:zone-a', 'mcp-relay')):
        assert steps.index(before) < steps.index(after)
    assert steps[-1] == 'calls'


def test_remote_plan_puts_the_control_plane_first_and_gpu_nodes_last(env):
    ctx = env.make('remote.ini')
    steps = list(deploy.plan(ctx, 'up', ['gpu-1', 'edge', 'server-a']))
    # One Ansible run for each host step covers every target node.
    assert [s for s in steps if s.startswith('hosts:')] == ['hosts:prepare', 'hosts:k3s', 'hosts:verify']
    assert 'cluster' in steps
    assert list(deploy.plan(ctx, 'down', ['gpu-1', 'edge', 'server-a']))[-3:] == [
        'stop:k3s:gpu-1', 'stop:k3s:edge', 'stop:k3s:server-a']
    # The GPU images are built after the other images and before the GPU pool.
    assert steps.index('images') < steps.index('gpu-images') < steps.index('gpu-pool')
    # Without the control plane the driver runs no cluster step.
    assert all(s.startswith('hosts:') for s in deploy.plan(ctx, 'up', ['edge']))


def test_a_site_without_gpu_nodes_has_no_gpu_steps(env):
    ctx = env.make()
    steps = list(deploy.plan(ctx, 'up', ['dev']))
    assert 'gpu-images' not in steps and 'gpu-pool' not in steps


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


def test_the_independent_steps_act_on_different_nodes():
    assert not deploy.independent('hosts:k3s', 'hosts:prepare')
    assert not deploy.independent('cluster', 'hosts:verify')
    assert deploy.independent('stop:k3s:a', 'stop:k3s:b')
    assert not deploy.independent('stop:k3s:a', 'stop:stores')


def test_render_and_check_change_no_host_and_write_only_the_inventory_and_facts(env, monkeypatch):
    ctx = env.make('remote.ini')
    before = sorted(p for p in env.tmp.rglob('*') if 'commands.log' not in str(p))
    out = deploy.render(ctx, ['server-a', 'worker-b'], deploy.resolve_revision(env.repo, 'HEAD'))
    assert out['up'][0] == 'hosts:prepare' and out['down'][-1] == 'stop:k3s:server-a'
    assert out['inventory']['all']['children']['hoover4_server']['hosts'] == {'server-a': {}}
    (env.private / 'facts').mkdir()
    (env.private / 'facts' / 'worker-b.json').write_text('{"os_family": "RedHat"}')
    problems, state = deploy.check(ctx, ['server-a', 'worker-b'])
    after = sorted(p for p in env.tmp.rglob('*') if 'commands.log' not in str(p))
    assert {p.relative_to(env.private).parts[0] for p in set(after) - set(before)} == {'ansible', 'facts'}
    playbooks = [c for c in env.commands() if c[0] == 'ansible-playbook']
    assert len(playbooks) == 1 and playbooks[0][-2:] == ['--tags', 'facts']
    assert not [c for c in env.commands() if c[0] in ('sudo', 'ssh')]
    assert state['worker-b']['os_family'] == 'RedHat' and state['server-a'] == {'reachable': False, 'ready': False}
    assert any('the operator tools are missing' in p for p in problems)
    assert any(f'the admin kubeconfig {ctx.kubeconfig} is missing' in p for p in problems)


def test_a_failed_play_names_the_node_and_keeps_a_resumable_record(env, monkeypatch):
    monkeypatch.setenv('FAKE_ANSIBLE', 'fail')
    ctx = env.make('remote.ini')
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    steps = deploy.select(deploy.plan(ctx, 'up', ['edge']), ['hosts'])
    record = ctx.records.new('up', ['edge'], rev, list(steps))
    assert deploy.execute(ctx, record, steps) == 2
    record = ctx.records.load(record['id'])
    assert record['status'] == 'failed' and record['error'].startswith('hosts:prepare: the play hoover4-hosts.yml failed on edge')
    assert [s['state'] for s in record['steps']] == ['failed', 'pending', 'pending']


def test_verify_names_a_missing_kubeconfig_and_the_differences_of_each_node(env, monkeypatch):
    ctx = env.make('remote.ini')
    ctx.record = {'targets': ['server-a', 'edge']}
    with pytest.raises(deploy.StepFailed, match=f'the admin kubeconfig {ctx.kubeconfig} is missing'):
        deploy.step_verify(ctx)
    ctx.kubeconfig.write_text('fake')
    ready = {'server-a': True, 'edge': False}
    monkeypatch.setattr(deploy, 'node_ready', lambda ctx, name: ready[name])
    monkeypatch.setattr(deploy, 'node_label', lambda ctx, name, label: 'true')
    monkeypatch.setattr(deploy, 'node_args', lambda ctx, name: ['--flannel-iface', 'wg0', '--cluster-init', 'true'])
    monkeypatch.setattr(deploy.Context, 'kubectl', lambda self, *a, check=True: deploy.K3S_VERSION)
    with pytest.raises(deploy.StepFailed, match='node edge: the node is not Ready'):
        deploy.step_verify(ctx, attempts=2, pause=0)
    ready['edge'] = True
    monkeypatch.setattr(deploy, 'node_args', lambda ctx, name: ['--flannel-iface', 'eth0'])
    with pytest.raises(deploy.StepFailed) as error:
        deploy.step_verify(ctx, attempts=1, pause=0)
    assert "node server-a: flannel-iface is 'eth0', not 'wg0', k3s runs without cluster-init" in str(error.value)
    monkeypatch.setattr(deploy, 'node_args', lambda ctx, name: ['--flannel-iface', 'wg0', '--cluster-init', 'true'])
    assert deploy.step_verify(ctx, attempts=1, pause=0) == {'nodes': ['server-a', 'edge']}


def test_a_dirty_checkout_stays_unchanged_and_the_record_names_its_files(env):
    (env.repo / 'file.txt').write_text('local change\n')
    ctx = env.make()
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    record = ctx.records.new('up', ['dev'], rev, ['a'], checkout_changes=deploy.dirty_files(env.repo))
    assert deploy.execute(ctx, record, fake_steps(['a'], [])) == 0
    assert (env.repo / 'file.txt').read_text() == 'local change\n'
    assert ctx.records.load(record['id'])['checkout_changes'] == [' M file.txt']
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
        'cronjobs': {'zone-a': {'opendesk-nextcloud-aio-cron': False, 'paused-by-operator': True}},
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
    kube = json.loads((env.tmp / 'kube.json').read_text())
    assert kube['cronjobs']['zone-a'] == {'opendesk-nextcloud-aio-cron': True, 'paused-by-operator': True}
    play = [c for c in env.commands() if c[0] == 'ansible-playbook'][-1]
    assert play[play.index('--limit') + 1] == 'dev' and play[-1] == '{"hoover4_action": "stop"}'
    assert play[play.index('--limit') + 2].endswith('playbooks/hoover4-service.yml')
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
    kube = json.loads((env.tmp / 'kube.json').read_text())
    assert kube['cronjobs']['zone-a'] == {'opendesk-nextcloud-aio-cron': False, 'paused-by-operator': True}
    assert ctx.records.applied() is None
    assert 'temporal' in log


def test_the_command_refuses_a_missing_or_unknown_target(env):
    ctx = env.make()
    cmd = [sys.executable, str(K3S / 'deploy-k3s'), 'up', '--site', str(ctx.site_path)]
    # The variable runs the command as it runs inside the operator image.
    image = dict(os.environ, HOOVER4_OPERATOR_IMAGE='1')
    out = subprocess.run(cmd, capture_output=True, text=True, env=image)
    assert out.returncode != 0 and 'needs --target with nodes of the site: dev, or all' in out.stderr
    out = subprocess.run(cmd + ['--target', 'nope'], capture_output=True, text=True, env=image)
    assert 'nope is not a node of the site' in out.stderr


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


# Pinned inputs, the site lock and the applied settings ----------------------------------------------------------------

import oplock  # noqa: E402
from conftest import operator_settings  # noqa: E402


def test_a_resume_refuses_a_changed_site_file_or_cluster(env, monkeypatch):
    ctx = env.make()
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    calls = []
    record = ctx.records.new('up', ['dev'], rev, ['a', 'b'], inputs=deploy.pinned_inputs(ctx))
    assert record['inputs']['settings_revision'] == 0 and 'tree' not in record['inputs']
    assert deploy.execute(ctx, record, fake_steps(['a', 'b'], calls, interrupt=['b'])) == 130
    ctx.site_path.write_text(ctx.site_path.read_text() + '\n# edited\n')
    assert deploy.execute(ctx, ctx.records.load(record['id']), fake_steps(['a', 'b'], calls)) == 2
    record = ctx.records.load(record['id'])
    assert 'the site file' in record['error'] and 'changed after the start of the record' in record['error']
    assert [c[0] for c in calls] == ['a', 'b']
    # The cluster identity is recorded when the cluster answers, and another cluster is refused.
    ctx = env.make()
    (env.private / 'kubeconfig').write_text('fake')
    monkeypatch.setenv('FAKE_CLUSTER', 'uid-1')
    record = ctx.records.new('up', ['dev'], rev, ['a'], inputs=deploy.pinned_inputs(ctx))
    assert record['inputs']['cluster_identity'] == 'uid-1'
    monkeypatch.setenv('FAKE_CLUSTER', 'uid-2')
    assert deploy.execute(ctx, record, fake_steps(['a'], [])) == 2
    assert 'another cluster' in ctx.records.load(record['id'])['error']


def test_one_site_lock_for_the_driver_apply_migration_and_backups(env, tmp_path):
    ctx = env.make()
    ctx.records.lock('up', 'up-1')
    for kind in ('apply', 'migration', 'backup', 'zone-operation'):
        with pytest.raises(oplock.Busy, match='the site operation up up-1'):
            oplock.SiteLock(ctx.state).acquire(kind, f'{kind}-1')
    assert oplock.SiteLock(ctx.state).busy()['id'] == 'up-1'
    ctx.records.unlock()
    assert oplock.SiteLock(ctx.state).busy() is None
    assert oplock.SiteLock(ctx.state).holder()['state'] == 'released'


def test_a_killed_holder_releases_the_lock_and_the_next_holder_records_it(env):
    ctx = env.make()
    script = ('import sys, time; sys.path.insert(0, sys.argv[1]); import oplock; '
              'lock = oplock.SiteLock(sys.argv[2]); lock.acquire("migration", "migration-1"); print("held", flush=True); '
              'time.sleep(60)')
    child = subprocess.Popen([sys.executable, '-c', script, str(K3S), str(ctx.state)], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == 'held'
    with pytest.raises(oplock.Busy):
        oplock.SiteLock(ctx.state).acquire('up', 'up-2')
    child.kill()
    child.wait()
    lock = oplock.SiteLock(ctx.state)
    owner = lock.acquire('up', 'up-2')
    assert owner['recovered']['id'] == 'migration-1'
    # A child process of the holder runs inside its operation without a second lock.
    out = subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); import oplock; '
                          'print(oplock.SiteLock(sys.argv[2]).acquire("zone", "x")["id"])', str(K3S), str(ctx.state)],
                         capture_output=True, text=True, env=dict(os.environ))
    assert out.stdout.strip() == 'up-2'
    lock.release()


def test_a_finished_complete_up_records_its_settings_revision_for_every_scope(env):
    ctx = env.make()
    S = operator_settings()
    state = S.State(ctx.state)
    state.save(0, {'hoover:main': {'main_services.common_workers': '5'}})
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    record = ctx.records.new('up', ['dev'], rev, ['a'], complete=True, inputs=deploy.pinned_inputs(ctx))
    # A save after the start of the run stays pending.
    state.save(1, {'hoover:main': {'main_services.common_workers': '6'}})
    assert deploy.execute(ctx, record, fake_steps(['a'], [])) == 0
    assert state.applied()['revision'] == 1 and state.applied()['operation'] == f'deploy:{record["id"]}'
    assert state.revision() == 2


def test_a_zone_step_records_its_scopes_after_the_workloads_are_ready(env, monkeypatch):
    ctx = env.make()
    S = operator_settings()
    state = S.State(ctx.state)
    state.save(0, {'zone:zone-a': {'app.xwiki': 'false'}, 'cluster': {'cpu.oversubscription': '3'}})
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    waited = []
    monkeypatch.setattr(deploy, 'wait_rollouts', lambda ctx, ns: waited.append(ns))
    checked = []
    monkeypatch.setattr(deploy, 'check_sign_in', lambda ctx, hoover: checked.append(hoover.namespace))
    ran = []
    monkeypatch.setattr(ctx, 'run', lambda argv, **kw: ran.append(([str(a) for a in argv], ctx.env())) or (0, ''))
    steps = {'zone:zone-a': deploy.step_zone('zone-a', 'dev')}
    record = ctx.records.new('up', ['dev'], rev, list(steps), complete=False, inputs=deploy.pinned_inputs(ctx))
    assert deploy.execute(ctx, record, steps) == 0
    assert waited == ['zone-a', 'hoover-zone-a']
    assert checked == ['hoover-zone-a']
    assert state.applied_revision('zone:zone-a') == 1 and state.applied_revision('hoover:main') == 1
    # The cluster scope needs every zone and the GPU pool, so a scoped run leaves it pending.
    assert state.applied_revision('cluster') == 0 and state.applied()['revision'] == 0
    # The zone is registered and the frontend serves its names before zone.py applies it.
    assert 'zone.register' in ran[0][0][2] and ran[0][0][4:] == ['zone-a', 'dev']
    assert any('frontend' in arg for arg in ran[1][0])
    # zone.py and its nested renders get the pinned settings revision.
    assert ran[-1][0][1].endswith('zones/zone.py') and ran[-1][1]['HOOVER4_SETTINGS_REVISION'] == '1'


@pytest.mark.parametrize('phase, logs, passes', [
    ('Succeeded', 'the token endpoint accepted the client of the proxy', True),
    ('Failed', 'the proxy cannot reach the sign-in service: [Errno 111] Connection refused', False),
    ('Pending', '', False),
])
def test_a_broken_token_exchange_fails_the_zone_step(env, monkeypatch, phase, logs, passes):
    ctx = env.make('remote.ini')
    hoover = next(h for h in ctx.site.hoovers.values() if h.zone == 'zone-a')
    calls = []

    def kubectl(*args, check=True):
        calls.append(args)
        if 'jsonpath={.status.phase}' in args:
            return phase
        return logs if 'logs' in args else 'FailedScheduling: no node' if 'events' in args else ''
    monkeypatch.setattr(ctx, 'kubectl', kubectl)
    applied = []
    monkeypatch.setattr(ctx, 'run', lambda argv, **kw: applied.append(json.loads(kw['input'])) or (0, ''))
    monkeypatch.setattr(deploy.time, 'sleep', lambda s: None)
    if passes:
        deploy.check_sign_in(ctx, hoover)
    else:
        with pytest.raises(deploy.StepFailed, match=f'sign-in check of {hoover.namespace} ended in phase {phase}'
                           + (': the proxy cannot reach' if logs else ': FailedScheduling')):
            deploy.check_sign_in(ctx, hoover, timeout=0.01 if phase == 'Pending' else 300)
    pod = applied[0]
    # The pod gets the label that the egress-oidc policy of the proxy selects, and the client secret of the proxy.
    assert pod['metadata']['labels']['hoover.dev/oidc'] == 'client'
    assert pod['metadata']['labels']['app.kubernetes.io/name'] != 'oauth2-proxy'
    assert pod['spec']['volumes'][0]['secret']['secretName'] == 'oauth2-proxy'
    issuer, redirect = pod['spec']['containers'][0]['command'][3:]
    assert issuer == f'https://id.zone-a.{ctx.site.suffix}/realms/opendesk'
    assert redirect == f'https://hoover.zone-a.{ctx.site.suffix}/oauth2/callback'
    assert calls[-1][:4] == ('-n', hoover.namespace, 'delete', 'pod')


def test_the_sign_in_check_accepts_only_invalid_grant(tmp_path):
    # The script runs against a local token endpoint. Only "invalid_grant" proves that Keycloak accepted the client.
    import http.server
    import threading
    answers = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({'token_endpoint': f'http://127.0.0.1:{self.server.server_port}/token'}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            code, body = answers['now']
            self.send_response(code)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())
    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    secrets = tmp_path / 'secrets'
    secrets.mkdir()
    (secrets / 'client-secret').write_text('s')
    script = deploy.SIGN_IN_CHECK.replace('/secrets/', f'{secrets}/')
    issuer = f'http://127.0.0.1:{server.server_port}/realms/opendesk'
    try:
        for code, body, ok in [(400, {'error': 'invalid_grant'}, True), (401, {'error': 'invalid_client'}, False),
                               (400, {'error': 'invalid_request'}, False), (200, {'access_token': 'x'}, False)]:
            answers['now'] = (code, body)
            r = subprocess.run([sys.executable, '-c', script, issuer, 'https://hoover.example/oauth2/callback'],
                               capture_output=True, text=True)
            assert (r.returncode == 0) == ok, (code, body, r.stderr)
        server.shutdown()
        r = subprocess.run([sys.executable, '-c', script, issuer, 'x'], capture_output=True, text=True, timeout=60)
        assert r.returncode and 'cannot reach the sign-in service' in r.stderr
    finally:
        server.server_close()


def test_an_image_of_the_wrong_architecture_fails_the_image_step(env, monkeypatch):
    ctx = env.make('remote.ini')
    ctx.revision = '0' * 40

    def registry_get(endpoint, path, accept=None):
        if '/manifests/' in path:
            return 'sha256:aa', {'config': {'digest': 'sha256:cfg'}}
        return '', {'architecture': 'amd64'}
    monkeypatch.setattr(deploy, 'registry_get', registry_get)
    out = deploy.image_references(ctx, ['hoover/hoover-vllm:000000000000'], architecture='amd64')
    assert out == {'registry.hoover.internal/hoover/hoover-vllm:000000000000':
                   {'digest': 'sha256:aa', 'architectures': ['amd64']}}
    with pytest.raises(deploy.StepFailed, match='not arm64'):
        deploy.image_references(ctx, ['hoover/hoover-vllm:000000000000'], architecture='arm64')
    assert deploy.gpu_architecture(ctx) == 'arm64'


def test_a_local_shell_runs_in_the_home_folder_like_a_remote_one():
    # The bundle paths are relative to the home folder. A driver run from another folder still finds the bundle.
    import types
    import nodeshell
    local = nodeshell.Shell(types.SimpleNamespace(name='a', local=True, ssh_address=''))
    remote = nodeshell.Shell(types.SimpleNamespace(name='b', local=False, ssh_address='op@b'))
    assert local.command('ls k3s-install') == ['sh', '-c', 'cd && ls k3s-install']
    assert remote.command('ls k3s-install')[-1] == 'ls k3s-install'


def test_an_on_delete_statefulset_waits_for_its_ready_replicas(monkeypatch):
    # kubectl rollout status refuses an OnDelete StatefulSet, for example the Kata stores of a zone.
    import types
    items = [{'kind': 'StatefulSet', 'metadata': {'name': 'clickhouse-kata'},
              'spec': {'replicas': 1, 'updateStrategy': {'type': 'OnDelete'}}},
             {'kind': 'Deployment', 'metadata': {'name': 'website'}, 'spec': {'replicas': 1}}]
    calls = []
    ctx = types.SimpleNamespace(kubeconfig='kc',
                                kubectl=lambda *a, check=False: json.dumps({'items': items if 'deployments,statefulsets' in a else []}),
                                run=lambda argv, capture=False, check=True: calls.append(argv) or (0, ''))
    deploy.wait_rollouts(ctx, 'zone-a')
    assert calls[0][5:7] == ['wait', 'statefulset/clickhouse-kata'] and '--for=jsonpath={.status.readyReplicas}=1' in calls[0]
    assert calls[1][5:8] == ['rollout', 'status', 'deployment/website']


def test_the_cluster_setup_labels_only_the_joined_nodes(tmp_path):
    # A GPU node of the site file joins in its own root step. Until then the cluster step labels the other nodes.
    import json
    import os
    import subprocess
    site = config.parse(site_text('remote.ini'))
    hosts = config.legacy_hosts(site)
    for name in hosts['hosts']:
        hosts['hosts'][name]['tiers'] = ['ssd']
    (tmp_path / 'hosts.json').write_text(json.dumps(hosts))
    joined = [n for n in hosts['hosts'] if n != 'gpu-1']
    calls = tmp_path / 'calls.log'
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'kubectl').write_text(
        '#!/bin/sh\necho "$*" >> %s\ncase "$*" in *"get nodes -o jsonpath"*) echo "%s";; *"label node gpu-1"*) exit 1;; esac\n'
        % (calls, ' '.join(joined)))
    (bin_dir / 'helm').write_text('#!/bin/sh\nexit 0\n')
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', SITE=str(tmp_path / 'hosts.json'),
               HELM=str(bin_dir / 'helm'), KUBECONFIG=str(tmp_path / 'kubeconfig'))
    r = subprocess.run(['bash', str(K3S / 'cluster/setup.sh')], env=env, capture_output=True, text=True)
    labelled = [line.split()[2] for line in calls.read_text().splitlines() if line.startswith('label node')]
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]
    assert 'node gpu-1 has not joined the cluster' in r.stdout
    assert 'gpu-1' not in labelled and set(joined) <= set(labelled)


def test_coturn_reaches_the_public_media_address_only_on_the_livekit_ports():
    # A relay-only client needs coturn to reach LiveKit at the public address. A host chain keeps every other port of
    # it closed to the coturn user. The pod admission policy refuses a privileged pod, so the rule is not in the pod.
    sys.path.insert(0, str(K3S / 'platform/calls'))
    import turn_peers
    assert turn_peers.peer_lines('10.42.0.0-10.42.3.255', '') == [
        'denied-peer-ip=0.0.0.0-255.255.255.255', 'allowed-peer-ip=10.42.0.0-10.42.3.255']
    assert turn_peers.peer_lines('10.42.0.0-10.42.3.255', '203.0.113.10')[-1] == 'allowed-peer-ip=203.0.113.10'
    firewall = (K3S / 'ansible/roles/hoover4_public_firewall/files/public-firewall.sh').read_text()
    assert f'COTURN_UID={turn_peers.COTURN_UID}' in firewall
    chain = firewall[firewall.index('chain coturn_peers {'):].split('}')[0].splitlines()
    rules = [line.split(' comment ')[0].strip() for line in chain[1:] if line.strip()]
    assert rules == ['type filter hook output priority raw; policy accept;', 'meta skuid != $COTURN_UID accept',
                     'ip daddr != $PUBLIC_IP accept', f'udp dport {turn_peers.LIVEKIT_UDP} accept',
                     f'tcp dport {turn_peers.LIVEKIT_TCP} accept', 'counter drop']
    text = (K3S / 'platform/calls/install-calls.py').read_text()
    assert "'runAsUser':turn_peers.COTURN_UID" in text and 'turn_peers.peer_lines(PODS,PUBLIC)' in text
    assert "'hostPort':turn_peers.LIVEKIT_UDP" in text and "'udp_port':turn_peers.LIVEKIT_UDP" in text
    assert 'hostPID' not in text and "'privileged'" not in text
    # A refused coturn or LiveKit pod fails the step, because the old pod is gone before the new one starts.
    assert "for name in ('coturn','livekit'):" in text and "'rollout','status'" in text


def test_ssh_that_sshd_refused_before_the_command_starts_again(monkeypatch):
    # A public node under login attempts from the internet drops new connections at MaxStartups.
    import types
    import nodeshell
    monkeypatch.setattr(nodeshell, 'SSH_PAUSE', 0)
    shell = nodeshell.Shell(types.SimpleNamespace(name='edge', local=False, ssh_address='op@edge'))
    answers = [(255, 'kex_exchange_identification: Connection closed by remote host'),
               (255, 'Connection reset by 203.0.113.10 port 22'), (0, 'done')]
    calls = []
    monkeypatch.setattr(nodeshell, 'run', lambda argv, **kw: calls.append(argv) or answers[len(calls) - 1])
    assert shell.run('true') == (0, 'done') and len(calls) == 3
    # A failure after the start, or another ssh error, is not run again.
    calls.clear()
    answers[:] = [(255, 'Permission denied (publickey).'), (0, 'done')]
    assert shell.run('true')[0] == 255 and len(calls) == 1
    calls.clear()
    answers[:] = [(1, 'Connection closed by remote host'), (0, 'done')]
    assert shell.run('true')[0] == 1 and len(calls) == 1


def test_a_node_that_keeps_its_vpn_gets_no_wireguard_play(tmp_path):
    text = site_text('remote.ini')
    groups = config.ansible_inventory(config.parse(text), tmp_path)['all']['children']
    assert 'server-a' in groups['hoover4_wireguard']['hosts'] and 'gpu-1' not in groups['hoover4_wireguard']['hosts']
    assert 'hoover4_wireguard' not in groups['hoover4']['hosts']['gpu-1']
    foreign = config.parse(text.replace('[node.calls]\n', '[node.calls]\nvpn_interface = wg-site\n'))
    assert 'calls' not in config.ansible_inventory(foreign, tmp_path)['all']['children']['hoover4_wireguard']['hosts']


