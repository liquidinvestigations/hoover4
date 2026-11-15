"""The driver suite: the plans, records, revisions, interruptions, host steps, render and check of deploy-k3s.

Fake ssh, sudo, bash, kubectl and ansible-playbook commands on PATH stand in for the hosts and the cluster. No test contacts a host.
"""
import json
import shlex
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import K3S, FIXTURES, site_text, write_site

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

    def make(fixture='single-node.yml'):
        # The zone state of the fixture goes into the state folder of the site file and into the private folder of
        # the context, which the driver reads.
        site_path = write_site(tmp_path, fixture)
        site_path = site_path.rename(tmp_path / 'site.yml')
        zones = site_path.parent / Path(fixture).stem / 'zone-state.json'
        if zones.exists():
            (tmp_path / 'site').mkdir(exist_ok=True)
            (tmp_path / 'site' / 'zone-state.json').write_text(zones.read_text())
            (private / 'zone-state.json').write_text(zones.read_text())
        site = config.read(site_path)
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
                          ('operator', 'stores'), ('stores', 'zone:zone-a'),
                          ('zone:zone-a', 'calls'), ('zone:zone-a', 'mcp-relay')):
        assert steps.index(before) < steps.index(after)
    assert steps[-1] == 'calls'


def test_remote_plan_puts_the_control_plane_first_and_gpu_nodes_last(env):
    ctx = env.make('remote.yml')
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


def test_the_up_steps_wait_only_for_their_prerequisites():
    names = ['hosts:prepare', 'hosts:k3s', 'hosts:verify', 'tools', 'cluster', 'registry', 'images', 'ingress', 'frontend',
             'monitoring', 'operator', 'hoover-data', 'stores', 'prepull', 'zone:zone-a', 'zone:zone-b', 'calls']
    needs = deploy.prerequisites(names)
    assert needs['registry'] == names[:5]
    for name in ('images', 'ingress', 'frontend', 'monitoring', 'hoover-data'):
        assert set(needs[name]) == set(names[:6]), name
    assert set(needs['operator']) == set(names[:6]) | {'images', 'monitoring'}
    assert set(needs['stores']) == set(needs['prepull']) == set(names[:6]) | {'images'}
    platform = {'images', 'ingress', 'frontend', 'monitoring', 'operator', 'hoover-data', 'stores'}
    assert set(needs['zone:zone-a']) == set(needs['zone:zone-b']) == set(names[:6]) | platform
    assert set(needs['calls']) == set(names[:6]) | (platform - {'images'}) | {'zone:zone-a', 'zone:zone-b'}
    # A step that the table does not name waits for every earlier step, except a step on another node.
    assert deploy.prerequisites(['a', 'b', 'c'])['c'] == ['a', 'b']
    assert deploy.prerequisites(['start:k3s:a', 'start:k3s:b', 'start:stores'])['start:k3s:b'] == []


def test_independent_steps_run_at_the_same_time_and_zones_up_to_the_site_limit(env):
    import threading
    ctx = env.make()
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    names = ['registry', 'ingress', 'frontend', 'zone:zone-a', 'zone:zone-b', 'zone:zone-c', 'calls']
    lock, active, peak, order = threading.Lock(), set(), {}, []

    def make(name):
        def run(ctx):
            with lock:
                active.add(name)
                order.append(name)
                peak['all'] = max(peak.get('all', 0), len(active))
                peak['zones'] = max(peak.get('zones', 0), sum(a.startswith('zone:') for a in active))
            time.sleep(0.3)
            with lock:
                active.discard(name)
            return {}
        return run
    record = ctx.records.new('up', ['dev'], rev, names, complete=False)
    assert deploy.execute(ctx, record, {n: make(n) for n in names}) == 0
    assert config.parallel_zones(ctx.site) == 2
    assert peak['zones'] == 2 and peak['all'] >= 2
    assert order[0] == 'registry' and order[-1] == 'calls'
    assert {s['state'] for s in ctx.records.load(record['id'])['steps']} == {'done'}


def test_a_failed_step_lets_the_running_steps_finish_and_starts_no_later_step(env):
    ctx = env.make()
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    names = ['registry', 'ingress', 'frontend', 'zone:zone-a']

    def ingress(ctx):
        raise deploy.StepFailed('ingress broke')

    def frontend(ctx):
        time.sleep(0.3)
        return {}
    steps = {'registry': lambda ctx: {}, 'ingress': ingress, 'frontend': frontend, 'zone:zone-a': lambda ctx: {}}
    record = ctx.records.new('up', ['dev'], rev, names, complete=True)
    assert deploy.execute(ctx, record, steps) == 2
    states = {s['name']: s['state'] for s in ctx.records.load(record['id'])['steps']}
    assert states == {'registry': 'done', 'ingress': 'failed', 'frontend': 'done', 'zone:zone-a': 'pending'}
    assert ctx.records.load(record['id'])['error'] == 'ingress: ingress broke'


def test_measure_speed_runs_only_the_forced_speed_play(env):
    ctx = env.make('remote.yml')
    deploy.measure_speed(ctx, ['worker-b'])
    playbooks = [c for c in env.commands() if c[0] == 'ansible-playbook']
    assert len(playbooks) == 1 and playbooks[0][-2:] == ['--tags', 'speed']
    assert playbooks[0][playbooks[0].index('--limit') + 1] == 'worker-b'
    extras = [json.loads(playbooks[0][i + 1]) for i, a in enumerate(playbooks[0]) if a == '-e']
    assert extras[-1] == {'hoover4_speed_force': True}
    assert (env.private / 'speed').is_dir()


def test_the_independent_steps_act_on_different_nodes():
    assert not deploy.independent('hosts:k3s', 'hosts:prepare')
    assert not deploy.independent('cluster', 'hosts:verify')
    assert deploy.independent('stop:k3s:a', 'stop:k3s:b')
    assert not deploy.independent('stop:k3s:a', 'stop:stores')


def test_render_and_check_change_no_host_and_write_only_the_inventory_and_facts(env, monkeypatch):
    ctx = env.make('remote.yml')
    before = sorted(p for p in env.tmp.rglob('*') if 'commands.log' not in str(p))
    out = deploy.render(ctx, ['server-a', 'worker-b'], deploy.resolve_revision(env.repo, 'HEAD'))
    assert out['up'][0] == 'hosts:prepare' and out['down'][-1] == 'stop:k3s:server-a'
    assert out['site'] == 'example-org' and out['ansible_variables']['hoover4_nodes']['server-a']['server'] is True
    (env.private / 'facts').mkdir()
    (env.private / 'facts' / 'worker-b.json').write_text('{"os_family": "RedHat"}')
    problems, state = deploy.check(ctx, ['server-a', 'worker-b'])
    after = sorted(p for p in env.tmp.rglob('*') if 'commands.log' not in str(p))
    assert {p.relative_to(env.private).parts[0] for p in set(after) - set(before)} == {'facts'}
    playbooks = [c for c in env.commands() if c[0] == 'ansible-playbook']
    assert len(playbooks) == 1 and playbooks[0][-2:] == ['--tags', 'facts']
    # The site file is the inventory, and the derived values are extra variables.
    assert playbooks[0][1:3] == ['-i', str(ctx.site_path)]
    assert json.loads(playbooks[0][playbooks[0].index('-e') + 1])['hoover4_nodes']['worker-b']['ssh_host'] == 'worker-b'
    assert not [c for c in env.commands() if c[0] in ('sudo', 'ssh')]
    assert state['worker-b']['os_family'] == 'RedHat'
    assert {k: v for k, v in state['server-a'].items() if k != 'speed'} == {'reachable': False, 'ready': False}
    # The check names the stored speed of each node, and how to measure a node without one.
    assert 'deploy-k3s measure-speed --target server-a' in state['server-a']['speed']['note']
    assert any('the operator tools are missing' in p for p in problems)
    assert any(f'the admin kubeconfig {ctx.kubeconfig} is missing' in p for p in problems)
    # zone-b of the fixture is a zone of the earlier store layout, and the site has three store nodes.
    assert any(p.startswith('the zone zone-b keeps its ClickHouse and Garage in its zone namespace') for p in problems)
    assert not any('zone-a keeps' in p for p in problems)
    # zone-a of the fixture uses the Temporal of the site, so no problem names its Temporal.
    assert not any('Temporal on the PostgreSQL' in p for p in problems)
    assert not any('zone-a runs its own Manticore' in p for p in problems)
    assert 'store_warnings' not in state


def test_check_names_a_site_zone_of_the_earlier_temporal(env):
    ctx = env.make('remote.yml')
    state = json.loads((env.private / 'zone-state.json').read_text())
    del state['zones']['zone-a']['temporal']
    (env.private / 'zone-state.json').write_text(json.dumps(state))
    problems, _ = deploy.check(ctx, ['server-a'])
    assert any(p.startswith('the zone zone-a runs its own Temporal on the PostgreSQL of the zone') for p in problems)


def test_check_names_a_site_zone_of_the_earlier_manticore(env):
    ctx = env.make('remote.yml')
    state = json.loads((env.private / 'zone-state.json').read_text())
    del state['zones']['zone-a']['manticore']
    (env.private / 'zone-state.json').write_text(json.dumps(state))
    problems, _ = deploy.check(ctx, ['server-a'])
    assert any(p.startswith('the zone zone-a runs its own Manticore daemons in the zone namespace') for p in problems)


def test_check_refuses_shared_stores_with_copies(env, monkeypatch):
    ctx = env.make('remote.yml')
    ctx.kubeconfig.write_text('fake')
    recorded = {'data': {'plan': json.dumps({'failover': False, 'replicas': 3, 'garage_replication_factor': 3})}}
    monkeypatch.setattr(deploy.Context, 'kubectl', lambda self, *a, check=True: json.dumps(recorded) if 'shared-stores' in a else '')
    monkeypatch.setattr(deploy, 'node_ready', lambda ctx, name: True)
    problems, _ = deploy.check(ctx, ['server-a'])
    assert any(p.startswith('the shared stores of hoover-stores keep 3 copies of their data') for p in problems)


def test_a_failed_play_names_the_node_and_keeps_a_resumable_record(env, monkeypatch):
    monkeypatch.setenv('FAKE_ANSIBLE', 'fail')
    ctx = env.make('remote.yml')
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    steps = deploy.select(deploy.plan(ctx, 'up', ['edge']), ['hosts'])
    record = ctx.records.new('up', ['edge'], rev, list(steps))
    assert deploy.execute(ctx, record, steps) == 2
    record = ctx.records.load(record['id'])
    assert record['status'] == 'failed' and record['error'].startswith('hosts:prepare: the play hoover4-hosts.yml failed on edge')
    assert [s['state'] for s in record['steps']] == ['failed', 'pending', 'pending']


def test_verify_names_a_missing_kubeconfig_and_the_differences_of_each_node(env, monkeypatch):
    ctx = env.make('remote.yml')
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
    gib = 2 ** 30
    single = {'dev': {'volume_groups': {'hoover4': {'size_bytes': 1000 * gib, 'k3s_volumes_bytes': 190 * gib}}}}
    single, labels = topolvm_values.values(config.legacy_hosts(config.parse(site_text('single-node.yml')), single))
    # The k3s data volumes in the group do not count: 5 % of 810 GiB is 40.5 GiB, rounded up.
    assert single['lvmd']['deviceClasses'] == [{'name': 'nvme', 'volume-group': 'hoover4', 'default': True, 'spare-gb': 41}]
    defaults = [c['name'] for c in single['storageClasses'] if c['storageClass']['isDefaultClass']]
    assert defaults == ['nvme-ext4']
    facts = {'server-a': {'volume_groups': {'tier-hdd': {'size_bytes': 400 * gib}}},
             'worker-b': {'volume_groups': {'tier-hdd': {'size_bytes': 200 * gib}, 'tier-ssd': {'size_bytes': 100 * gib}}},
             'edge': {'volume_groups': {'tier-nvme': {'size_bytes': 50 * gib}}}}
    remote, labels = topolvm_values.values(config.legacy_hosts(config.parse(site_text('remote.yml')), facts))
    assert [c['name'] for c in remote['storageClasses'] if c['storageClass']['isDefaultClass']] == ['hdd-ext4']
    assert {c['name'] for c in remote['storageClasses']} == {f'{t}-{k}' for t in ('hdd', 'ssd', 'nvme') for k in ('ext4', 'block')}
    # Each node has its own lvmd configuration, and each tier its own volume group.
    assert labels == {'edge': 'edge', 'server-a': 'server-a', 'worker-b': 'worker-b'}
    configs = {c['nodeSelector']['storage.hoover/lvmd']: c['deviceClasses']
               for c in [remote['lvmd']] + remote['lvmd']['additionalConfigs']}
    assert configs['worker-b'] == [{'name': 'hdd', 'volume-group': 'tier-hdd', 'default': True, 'spare-gb': 10},
                                   {'name': 'ssd', 'volume-group': 'tier-ssd', 'default': False, 'spare-gb': 5}]
    assert configs['edge'] == [{'name': 'nvme', 'volume-group': 'tier-nvme', 'default': True, 'spare-gb': 3}]
    # A node without the facts of a volume group stops the render with its name.
    del facts['edge']
    with pytest.raises(SystemExit, match='edge has no facts of the volume group tier-nvme'):
        topolvm_values.values(config.legacy_hosts(config.parse(site_text('remote.yml')), facts))


def test_the_legacy_settings_of_a_single_node_site_use_the_local_address():
    values = config.legacy_settings(config.parse(site_text('single-node.yml')))
    assert values['registry_endpoint'] == f'{config.LOCAL_ADDRESS}:5000'
    assert values['frontend_bind'] == [config.LOCAL_ADDRESS] and values['frontend_local'] is True
    assert 'frontend_ssh' not in values
    remote = config.legacy_settings(config.parse(site_text('remote.yml')))
    assert remote['frontend_ssh'] == 'edge' and remote['registry_endpoint'] == '10.0.0.2:5000'
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
    state.save(0, {'hoover:zone-a': {'main_services.common_workers': '5'}})
    rev = deploy.resolve_revision(env.repo, 'HEAD')
    record = ctx.records.new('up', ['dev'], rev, ['a'], complete=True, inputs=deploy.pinned_inputs(ctx))
    # A save after the start of the run stays pending.
    state.save(1, {'hoover:zone-a': {'main_services.common_workers': '6'}})
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
    steps = {'zone:zone-a': deploy.step_zone('zone-a')}
    record = ctx.records.new('up', ['dev'], rev, list(steps), complete=False, inputs=deploy.pinned_inputs(ctx))
    assert deploy.execute(ctx, record, steps) == 0
    assert waited == ['zone-a', 'hoover-zone-a']
    assert checked == ['hoover-zone-a']
    assert state.applied_revision('zone:zone-a') == 1 and state.applied_revision('hoover:zone-a') == 1
    # The cluster scope needs every zone and the GPU pool, so a scoped run leaves it pending.
    assert state.applied_revision('cluster') == 0 and state.applied()['revision'] == 0
    # The zone is registered before zone.py applies it. The frontend serves every zone host, so no frontend step runs.
    # A zone has no home node, so neither call names one.
    assert 'zone.register' in ran[0][0][2] and ran[0][0][4:] == ['zone-a']
    assert ran[-1][0][2:] == ['apply', 'zone-a']
    assert not any('frontend' in arg for command, _ in ran for arg in command)
    # zone.py and its nested renders get the pinned settings revision.
    assert ran[-1][0][1].endswith('zones/zone.py') and ran[-1][1]['HOOVER4_SETTINGS_REVISION'] == '1'


@pytest.mark.parametrize('phase, logs, passes', [
    ('Succeeded', 'the token endpoint accepted the client of the proxy', True),
    ('Failed', 'the proxy cannot reach the sign-in service: [Errno 111] Connection refused', False),
    ('Pending', '', False),
])
def test_a_broken_token_exchange_fails_the_zone_step(env, monkeypatch, phase, logs, passes):
    ctx = env.make('remote.yml')
    hoover = ctx.hoovers()['zone-a']
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
    assert issuer == f'https://zone-a-id.{ctx.site.domain}/realms/opendesk'
    assert redirect == f'https://zone-a-hoover.{ctx.site.domain}/oauth2/callback'
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
    ctx = env.make('remote.yml')
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
    # The architecture of a node comes from its facts.
    with pytest.raises(deploy.StepFailed, match='deploy-k3s check --target gpu-1'):
        deploy.gpu_architecture(ctx)
    (ctx.private / 'facts').mkdir(parents=True, exist_ok=True)
    (ctx.private / 'facts' / 'gpu-1.json').write_text(json.dumps({'architecture': 'aarch64'}))
    assert deploy.gpu_architecture(ctx) == 'arm64'


def test_a_local_shell_runs_in_the_home_folder_like_a_remote_one():
    # The bundle paths are relative to the home folder. A driver run from another folder still finds the bundle.
    import types
    import nodeshell
    local = nodeshell.Shell(types.SimpleNamespace(name='a', local=True, ssh_host=''))
    remote = nodeshell.Shell(types.SimpleNamespace(name='b', local=False, ssh_host=''))
    alias = nodeshell.Shell(types.SimpleNamespace(name='c', local=False, ssh_host='C'))
    assert local.command('ls k3s-install') == ['sh', '-c', 'cd && ls k3s-install']
    assert remote.command('ls k3s-install')[-3:] == ['b', '--', 'ls k3s-install']
    assert alias.command('ls k3s-install')[-3:] == ['C', '--', 'ls k3s-install']


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
    site = config.parse(site_text('remote.yml'))
    facts = {name: {'avx2': name != 'worker-b', 'gpus': [{'name': 'GB10', 'memory_mib': 1000}] if name == 'gpu-1' else [],
                    'volume_groups': {g: {'size_bytes': 2 ** 40} for g in node.storage.values()}}
             for name, node in site.nodes.items()}
    hosts = config.legacy_hosts(site, facts)
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
    lines = {line.split()[2]: line for line in calls.read_text().splitlines()
             if line.startswith('label node') and 'storage.hoover/lvmd' not in line}
    # The labels of the facts. A node without the fact loses the label.
    assert 'cpu.hoover/avx2=true' in lines['server-a'] and 'cpu.hoover/avx2-' in lines['worker-b']
    assert 'storage.tier/hdd=true' in lines['worker-b'] and 'storage.tier/ssd=true' in lines['worker-b']
    assert 'gpu.hoover/count-' in lines['edge']
    # A node without facts stops the setup, because its labels are unknown.
    hosts['hosts']['edge']['facts'] = False
    (tmp_path / 'hosts.json').write_text(json.dumps(hosts))
    r = subprocess.run(['bash', str(K3S / 'cluster/setup.sh')], env=env, capture_output=True, text=True)
    assert r.returncode and 'no facts for edge' in r.stderr


def test_coturn_reaches_the_public_media_address_only_on_the_livekit_ports():
    # A relay-only client needs coturn to reach LiveKit at the public address. A host chain keeps every other port of
    # it closed to the coturn user. The pod admission policy refuses a privileged pod, so the rule is not in the pod.
    sys.path.insert(0, str(K3S / 'platform/calls'))
    import turn_peers
    assert turn_peers.peer_lines('10.42.3.0/24', '203.0.113.10')[-1] == 'allowed-peer-ip=203.0.113.10'
    firewall = (K3S / 'ansible/roles/hoover4_public_firewall/files/coturn-peers.sh').read_text()
    assert f'COTURN_UID={turn_peers.COTURN_UID}' in firewall
    # The chain is in its own table, independent of the public interface and of the input filter.
    assert 'table inet hoover_coturn_peers {' in firewall and 'coturn_peers' not in (
        K3S / 'ansible/roles/hoover4_public_firewall/files/public-firewall.sh').read_text()
    chain = firewall[firewall.index('chain coturn_peers {'):].split('}')[0].splitlines()
    rules = [line.split(' comment ')[0].strip() for line in chain[1:] if line.strip()]
    assert rules == ['type filter hook output priority raw; policy accept;', 'meta skuid != $COTURN_UID accept',
                     '$FAMILY daddr != $PUBLIC_IP accept', f'udp dport {turn_peers.LIVEKIT_UDP} accept',
                     f'tcp dport {turn_peers.LIVEKIT_TCP} accept', 'counter drop']
    text = (K3S / 'platform/calls/install-calls.py').read_text()
    assert "'runAsUser':turn_peers.COTURN_UID" in text and 'turn_peers.peer_lines(PODS,public)' in text
    # The public peer comes only from the probe of the host rule (turn_peers.chain_problem).
    assert 'coturn(public_peer())' in text and 'turn_peers.chain_problem(NODE,PUBLIC' in text
    assert "'hostPort':turn_peers.LIVEKIT_UDP" in text and "'udp_port':turn_peers.LIVEKIT_UDP" in text
    assert 'hostPID' not in text and "'privileged'" not in text
    # A refused coturn or LiveKit pod fails the step, because the old pod is gone before the new one starts.
    assert "for name in ('coturn','livekit') if ZONES else ('coturn',):" in text and "'rollout','status'" in text


FAKE_CALLS_KUBECTL = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['CALLS_LOG'], 'a') as log:
    log.write(' '.join(args) + '\n')
if args[:2] == ['get', 'nodes']:
    print(json.dumps({'items': [{'metadata': {'name': 'calls'}, 'spec': {'podCIDR': '10.42.4.0/24'}}]}))
elif 'configmap' in args and 'coturn-peer-check' in args and args[-2:] == ['-o', 'json']:
    record = os.environ.get('CALLS_RECORD')
    if not record:
        sys.exit('Error from server (NotFound)')
    print(json.dumps({'data': json.loads(record)}))
elif args[:1] == ['apply']:
    sys.exit('apply is not expected')
"""


@pytest.mark.parametrize('record', [None, {'node': 'calls', 'address': '203.0.113.99'}, {'node': 'edge', 'address': '203.0.113.11'}])
def test_the_calls_step_without_a_matching_probe_record_adds_no_public_peer(tmp_path, record):
    # The zone runner cannot run the probe pod, so it reads the record of the operator step and stops without it.
    site = write_site(tmp_path, 'remote.yml')
    state = site.with_suffix('')
    (state / 'zones').mkdir(parents=True)
    (state / 'zones/secrets.json').write_text(json.dumps({'calls': {'jvb_password': 'x', 'livekit_turn_secret': 'y'}}))
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'kubectl').write_text(FAKE_CALLS_KUBECTL)
    (bin_dir / 'kubectl').chmod(0o755)
    env = dict(os.environ, HOOVER4_SITE=str(site), KUBECONFIG=str(tmp_path / 'kubeconfig'), CALLS_LOG=str(tmp_path / 'log'),
               PATH=f"{bin_dir}:{os.environ['PATH']}", CALLS_RECORD=json.dumps(record) if record else '')
    result = subprocess.run([sys.executable, str(K3S / 'platform/calls/install-calls.py')], env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert 'no verified record of the host rule coturn_peers for 203.0.113.11 on calls' in result.stderr
    assert '--steps operator' in result.stderr
    # The step stops before it changes anything and runs no probe pod.
    log = (tmp_path / 'log').read_text()
    assert 'apply' not in log and 'pod' not in log


def test_the_operator_and_calls_steps_record_the_probe_with_the_admin_kubeconfig(env, monkeypatch):
    ctx = env.make('remote.yml')
    ran = []
    monkeypatch.setattr(ctx, 'run', lambda argv, **kw: ran.append([str(a) for a in argv]) or (0, ''))
    deploy.step_calls(ctx)
    assert ran[0][-2:] == [str(K3S / 'platform/calls/install-calls.py'), '--probe']
    assert ran[1][-1] == str(K3S / 'platform/calls/install-calls.py')
    monkeypatch.setattr(deploy, 'step_operator_image', lambda ctx: 'registry.hoover.internal/hoover/operator:x')
    ran.clear()
    deploy.step_operator(ctx)
    probe = [r for r in ran if r[-1] == '--probe']
    assert probe and ran.index(probe[0]) < next(i for i, r in enumerate(ran) if r[-1].endswith('install-runner.sh'))
    rights = (K3S / 'platform/operator/runner-rights.yaml').read_text()
    calls_role = rights[rights.index('namespace: calls\nrules:'):].split('---')[0]
    # The runner reads the record and has no right on pods in calls.
    assert 'resourceNames: [coturn-peer-check]\n    verbs: [get]' in calls_role and 'pods' not in calls_role


def test_ssh_that_sshd_refused_before_the_command_starts_again(monkeypatch):
    # A public node under login attempts from the internet drops new connections at MaxStartups.
    import types
    import nodeshell
    monkeypatch.setattr(nodeshell, 'SSH_PAUSE', 0)
    shell = nodeshell.Shell(types.SimpleNamespace(name='edge', local=False, ssh_host=''))
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
    text = site_text('remote.yml')
    nodes = config.ansible_variables(config.parse(text), tmp_path)['hoover4_nodes']
    assert nodes['server-a']['wireguard'] and nodes['gpu-1']['wireguard'] == []
    kept = config.parse(text.replace('site: {address: 10.0.0.4, public_key: calls-public-key}',
                                     'site: {address: 10.0.0.4, public_key: calls-public-key, managed: false}'))
    assert config.ansible_variables(kept, tmp_path)['hoover4_nodes']['calls']['wireguard'] == []
    play = (K3S / 'ansible/playbooks/hoover4-hosts.yml').read_text()
    assert 'role: hoover4_wireguard\n      when: hoover4_wireguard | length > 0' in play




def test_the_frontend_step_names_the_local_ca_of_the_internal_mode(tmp_path):
    import types
    text = site_text('remote.yml').replace('tls_dns_credentials_file: /etc/letsencrypt/cloudflare.ini', 'tls_mode: internal')
    ran = []
    ctx = types.SimpleNamespace(site=config.parse(text), private=tmp_path, run=lambda argv, **kw: ran.append(argv) or (0, ''))
    assert deploy.step_frontend(ctx) == {'tls_mode': 'internal', 'local_ca': str(tmp_path / 'frontend' / 'local-ca.crt')}
    assert str(ran[0][1]).endswith('platform/frontend/install-frontend.sh')
    ctx.site = config.parse(site_text('remote.yml'))
    assert deploy.step_frontend(ctx) == {'tls_mode': 'cloudflare'}


def test_the_pull_pod_requests_nothing_so_a_full_node_admits_it():
    import importlib.util
    spec = importlib.util.spec_from_file_location('prepull', Path(__file__).resolve().parents[1] / 'images' / 'prepull.py')
    prepull = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepull)
    pod = prepull.pod('edge', ['registry.example/a:1'])
    spec = pod['spec']
    assert spec['nodeName'] == 'edge'
    assert all(c['resources']['requests'] == {'cpu': '0', 'memory': '0'} for c in spec['initContainers'] + spec['containers'])
