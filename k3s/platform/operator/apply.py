#!/usr/bin/env python3
"""The steps of an operator Apply and the commands that run them. The portal and runner.py use this module.

plan() compares the saved revision with the applied revision of each scope and names one step for each part that
changes:
  hoover:<installation>   ../../hoover/manifests.py apply with the pinned settings revision, then a rollout wait and a
                          check that each claim has its size
  apps:<zone>             ../../zones/apps.py, which turns openDesk applications off and on, then a rollout wait
  zone:<zone>             ../../zones/zone.py apply, for the memory limits of a zone and the CPU policy, then a rollout
                          wait of the zone and its Hoover namespace
  gpu-pool                ../gpu/gpu_pool.py apply for the cluster setting gpu.runtime, then a rollout wait and an
                          authenticated call to each GPU service (gpu_pool.py verify)
  schedule                the backup policies. The backup scheduler reads the applied revision, and no service changes.
A revision without a change gets the step record, so Apply still records it as applied.
plan_scopes() also names the steps of each changed scope. The operation records a scope as applied when all of its
steps finished, so a failed later step leaves only its own scopes pending.
Each command gets the deployment revision in HOOVER4_REVISION and the settings revision in HOOVER4_SETTINGS_REVISION.
Usage: apply.py plan     prints the steps of the saved revision
       apply.py run      runs the active operation once, as runner.py does
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parents[1]
sys.path.insert(0, str(K3S))
import config  # noqa: E402


def _operator_settings():
    """settings.py of this folder under the name operator_settings. The name settings belongs to ../../settings.py."""
    import importlib.util
    if 'operator_settings' not in sys.modules:
        spec = importlib.util.spec_from_file_location('operator_settings', HERE / 'settings.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules['operator_settings'] = module
        spec.loader.exec_module(module)
    return sys.modules['operator_settings']


operator_settings = _operator_settings()


class ApplyFailed(RuntimeError):
    """A step failed. The message names the cause and the action."""


def site():
    return config.read(os.environ.get('HOOVER4_SITE') or config.DEFAULT_SITE)


def scopes(s):
    out = ['cluster'] + [f'zone:{z}' for z in sorted({h.zone for h in s.hoovers.values()})]
    return out + [f'hoover:{h}' for h in sorted(s.hoovers)]


def changes(state, s, revision=None):
    """{scope: {key: (applied value, saved value)}} between the applied revision of each scope and a saved revision."""
    revision = state.revision() if revision is None else revision
    applied = state.applied()
    out = {}
    for scope in scopes(s):
        before = state.effective(scope, state.applied_revision(scope, applied))
        after = state.effective(scope, revision)
        diff = {k: (before[k], after[k]) for k in after if before[k] != after[k]}
        if diff:
            out[scope] = diff
    return out


def key_steps(s, scope, key):
    """The steps that bring one changed key of a scope to the services."""
    kind, _, name = scope.partition(':')
    zone_of = {h.zone: h.name for h in s.hoovers.values()}
    if key.startswith('backup.'):
        return ['schedule']
    if kind == 'hoover':
        return [f'hoover:{name}']
    if kind == 'zone' and key in ('app.hoover', 'zone.enabled') and name in zone_of:
        return [f'hoover:{zone_of[name]}'] + ([f'zone:{name}'] if key == 'zone.enabled' else [])
    if kind == 'zone' and key.startswith('app.'):
        return [f'apps:{name}']
    if kind == 'zone':
        return [f'zone:{name}']
    if key.startswith('gpu.'):
        # The GPU pool of the site runs the GPU services. A pool at an address runs outside the site, so the value
        # changes no service of this site.
        return ['gpu-pool'] if s.gpu_pool.get('nodes') else ['record']
    # The CPU policy of the cluster reaches the services through the render of each zone.
    return [f'zone:{zone}' for zone in sorted(zone_of)] or ['record']


def plan_scopes(state, s, revision=None):
    """(steps in order, {scope: [steps]}) of the changes of a saved revision."""
    steps, by_scope = [], {}
    for scope, diff in changes(state, s, revision).items():
        for key in diff:
            for step in key_steps(s, scope, key):
                if step not in steps:
                    steps.append(step)
                by_scope.setdefault(scope, [])
                if step not in by_scope[scope]:
                    by_scope[scope].append(step)
    # The GPU pool runs before the zones, so the zones find the GPU services with the new runtime.
    order = {'gpu-pool': 0}
    steps.sort(key=lambda step: order.get(step, 1))
    return (steps or ['record']), by_scope


def plan(state, s, revision=None):
    return plan_scopes(state, s, revision)[0]


def services(state, s, revision=None):
    """The services that the saved changes affect, for the portal."""
    out = set()
    for diff in changes(state, s, revision).values():
        for key in diff:
            out.update(operator_settings.REGISTRY[key].services)
    return sorted(out)


def deployment_revision(s):
    """The source revision of the applied deployment, else the commit of the checkout."""
    applied = s.operator_state() / 'deploy' / 'applied.json'
    if applied.exists():
        return json.loads(applied.read_text())['revision']
    return subprocess.run(['git', '-C', str(K3S.parent), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                          check=True).stdout.strip()


def run_command(argv, op, log):
    env = dict(os.environ, HOOVER4_REVISION=op.source_revision, HOOVER4_SETTINGS_REVISION=str(op.desired_revision))
    with open(log, 'a') as f:
        f.write(f'$ {" ".join(str(a) for a in argv)}\n')
        f.flush()
        result = subprocess.run([str(a) for a in argv], env=env, stdout=f, stderr=subprocess.STDOUT)
    if result.returncode:
        # A kubectl error can print a whole object on one line. The page shows the start of each line, and the log keeps all.
        tail = [line if len(line) <= 300 else line[:300] + '...' for line in Path(log).read_text().strip().splitlines()[-3:]]
        raise ApplyFailed(f'{Path(str(argv[1])).name} exited with code {result.returncode}: ' + ' | '.join(tail)
                          + f' The full output is in {log}.')


def kubectl(*args):
    kubeconfig = os.environ.get('KUBECONFIG') or str(K3S / 'private' / 'kubeconfig')
    return subprocess.run(['kubectl', '--kubeconfig', kubeconfig, *args], capture_output=True, text=True)


def wait_rollouts(namespace, timeout=900):
    """Wait until every Deployment and StatefulSet of a namespace with replicas runs its current revision."""
    deadline = time.monotonic() + timeout
    r = kubectl('-n', namespace, 'get', 'deployments,statefulsets', '-o', 'json')
    if r.returncode:
        raise ApplyFailed(f'the workloads of {namespace} are unreadable: {r.stderr.strip()[-300:]}')
    for item in json.loads(r.stdout)['items']:
        if item['spec'].get('replicas', 1) == 0:
            continue
        left = max(10, int(deadline - time.monotonic()))
        r = kubectl('-n', namespace, 'rollout', 'status', f"{item['kind'].lower()}/{item['metadata']['name']}", f'--timeout={left}s')
        if r.returncode:
            raise ApplyFailed(f"{item['kind']} {item['metadata']['name']} did not become ready: {r.stderr.strip()[-300:]}")
    return deadline


def wait_hoover(namespace, timeout=900):
    """Wait for every workload of the namespace and for the size of every claim."""
    deadline = wait_rollouts(namespace, timeout)
    while True:
        claims = json.loads(kubectl('-n', namespace, 'get', 'pvc', '-o', 'json').stdout)['items']
        short = [c for c in claims if c['status'].get('phase') == 'Bound' and
                 operator_settings.size_bytes(c['status'].get('capacity', {}).get('storage', '0')) <
                 operator_settings.size_bytes(c['spec']['resources']['requests']['storage'])]
        if not short:
            return
        claim = short[0]['metadata']['name']
        events = kubectl('-n', namespace, 'get', 'events', '--field-selector', f'involvedObject.name={claim},type=Warning',
                         '-o', 'jsonpath={range .items[*]}{.reason}{" "}{.message}{"\\n"}{end}').stdout.strip().splitlines()
        # A resize that the storage driver refuses does not succeed later, so the step ends at the first refusal.
        refused = [e for e in events if e.startswith(('VolumeResizeFailed', 'ExternalExpanding failed'))]
        if refused or time.monotonic() > deadline:
            events = refused or events
            raise ApplyFailed(f"the volume {claim} did not grow to {short[0]['spec']['resources']['requests']['storage']}. "
                              f"{events[-1].rstrip('.') + '.' if events else 'No event names the cause.'} Check the free space of the volume "
                              f"group with vgs, then retry, or abandon the operation and save a smaller size.")
        time.sleep(5)


def executors(s, log, wait=wait_hoover, wait_namespaces=None):
    wait_namespaces = wait_namespaces or (lambda names: [wait_rollouts(n) for n in names])
    by_name = {h.name: h for h in s.hoovers.values()}

    class Steps(dict):
        def __missing__(self, step):
            kind, _, name = step.partition(':')
            if kind == 'hoover':
                def run(op, overrides, name=name):
                    run_command([sys.executable, K3S / 'hoover/manifests.py', name, 'apply', '--revision', op.source_revision,
                                 '--settings-revision', str(op.desired_revision)], op, log)
                    wait(by_name[name].namespace)
                    return [f'hoover:{name}']
                return run
            if kind == 'apps':
                def run(op, overrides, name=name):
                    run_command([sys.executable, K3S / 'zones/apps.py', name], op, log)
                    wait_namespaces([name])
                    return [f'apps:{name}']
                return run
            if kind == 'zone':
                def run(op, overrides, name=name):
                    run_command([sys.executable, K3S / 'zones/zone.py', 'apply', name], op, log)
                    wait_namespaces([name] + [h.namespace for h in s.hoovers.values() if h.zone == name])
                    return [f'zone:{name}']
                return run
            if kind == 'gpu-pool':
                def run(op, overrides):
                    run_command([sys.executable, K3S / 'platform/gpu/gpu_pool.py', 'apply'], op, log)
                    run_command([sys.executable, K3S / 'platform/gpu/gpu_pool.py', 'verify'], op, log)
                    return ['gpu-pool']
                return run
            if kind in ('schedule', 'record'):
                return lambda op, overrides: ['backups'] if kind == 'schedule' else []
            raise KeyError(step)
    return Steps()


def main(argv):
    s = site()
    state = operator_settings.State(s.operator_state())
    if argv == ['plan']:
        print(json.dumps({'revision': state.revision(), 'applied': state.applied()['revision'],
                          'steps': plan(state, s), 'services': services(state, s)}, indent=1))
    elif argv == ['run']:
        log = s.operator_state() / 'logs' / 'apply.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        op = state.active()
        if op and op.status in ('running', 'queued'):
            import oplock
            with oplock.SiteLock(s.operator_state()) as lock:
                lock.acquire('apply', op.id)
                op = state.run(executors(s, log))
            print(json.dumps({'operation': op.id, 'status': op.status, 'error': op.error}))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
