"""The settings pages of the operator portal: read, save, Apply, retry and abandon, through settings.py and apply.py.

The portal container of the operator pod runs the k3s folder of the operator image (PORTAL_REPO) with the site file of
the ConfigMap portal-site. Its state folder holds the ConfigMaps of the cluster copy of the state (../../clusterstate.py). The
secrets are in the secret store (../../secretstore.py), which the portal does not read. With HOOVER4_CLUSTER_STATE=1, each request first reads the cluster copy, and a
request that changes the operator state writes it back. The runner container runs the Apply operations that this
module starts.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get('PORTAL_REPO', '/repo'))
sys.path.insert(0, str(REPO / 'k3s'))
sys.path.insert(0, str(REPO / 'k3s/platform/operator'))
sys.path.insert(0, str(REPO / 'k3s/platform/backups'))
import config  # noqa: E402
import apply  # noqa: E402
import clusterstate  # noqa: E402
import oplock  # noqa: E402
import schedule  # noqa: E402

S = apply.operator_settings
GROUP_TITLES = {'budget': 'Hoover resources', 'switch': 'Switches', 'tuning': 'Tunings', 'volume': 'Volume sizes',
                'size': 'Memory limits', 'backup': 'Backups'}
# Each scope of the overview names its settings in keys (apply.scope_keys()). The scope pools holds the settings of the
# processing pools of the site, and an installation of the store layout site does not list them.


class Refused(Exception):
    """A request that the portal refuses. The message goes back to the operator."""

    def __init__(self, message, status=400, problems=None):
        super().__init__(message)
        self.status, self.problems = status, problems or {}


def site():
    return config.read(os.environ.get('HOOVER4_SITE'))


def synced(function):
    """Read the cluster copy of the operator state before the request and write the changes after it."""
    import functools

    @functools.wraps(function)
    def run(*args):
        if os.environ.get(clusterstate.ENV) != '1':
            return function(*args)
        folder = site().state_folder()
        try:
            clusterstate.pull(folder, ('configmap',))
            result = function(*args)
        finally:
            clusterstate.push(folder, ('configmap',))
        return result
    return run


def state(s):
    return S.State(s.operator_state())


def suggestions(s, nodes):
    """Hardware suggestions for each Hoover installation and the processing pools, from the allocatable CPU and memory
    of the largest worker node of the site. A zone has no home node, so the scheduler can put a worker pod on that node.
    An installation of the store layout site has no pool setting, so the scope pools gets the Tika and Tesseract
    suggestions."""
    out = {}
    workers = [nodes[n.name] for n in s.nodes.values() if n.has('worker') and n.name in nodes]
    if not workers:
        return out
    largest = max(workers, key=lambda n: (n['memory_mib'], n['cpus']))
    cpus, memory_mib = largest['cpus'], largest['memory_mib']
    processors = {'budget.tika_cpus': str(max(1, cpus // 8)), 'budget.tesseract_cpus': str(max(1, cpus // 8))}
    pooled = apply.pooled(s)
    for hoover in config.hoovers(s).values():
        out[f'hoover:{hoover.name}'] = {
            'budget.worker_cpus': str(max(2, cpus // 3)),
            'budget.worker_memory_mib': str(max(3072, min(32768, memory_mib // 4 // 512 * 512))),
            **({} if hoover.name in pooled else processors),
            'budget.worker_pods': str(max(1, len([n for n in s.nodes.values() if n.has('worker')]))),
        }
    if pooled:
        out[S.POOLS] = processors
    return out


def describe(setting):
    return {'key': setting.key, 'scope': setting.scope, 'kind': setting.kind, 'default': setting.default,
            'minimum': setting.minimum, 'maximum': setting.maximum, 'choices': list(setting.choices),
            'services': list(setting.services), 'apply': setting.apply, 'group': setting.group,
            'empty': setting.empty}


def operation_view(st, op):
    if op is None:
        return None
    log = st.folder / 'logs' / f'{op.id}.log'
    lines = log.read_text(errors='replace').splitlines()[-15:] if log.exists() else []
    return {'id': op.id, 'status': op.status, 'error': op.error, 'steps': op.steps, 'changed': op.changed,
            'revision': op.desired_revision, 'source': op.source_revision[:12], 'attempts': op.attempts,
            'created': op.created, 'updated': op.updated, 'log': [line[:300] for line in lines]}


@synced
def backup_alarms():
    """The alarm rows of the backups, from operator/backups/state.json of the operator state (../backups/backups.py)."""
    s = site()
    path = s.operator_state() / 'backups' / 'state.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    return schedule.alarm_rows(data, bool(s.backup))


@synced
def overview(nodes):
    s = site()
    st = state(s)
    for scope, values in suggestions(s, nodes).items():
        if st.suggestions(scope) != values:
            st.suggest(scope, values)
    revision = st.revision()
    applied = st.applied()
    scopes = []
    for scope in apply.scopes(s):
        overrides = st.overrides(revision).get(scope, {})
        keys = apply.scope_keys(s, scope)
        scopes.append({'id': scope, 'keys': keys, 'services': {k: apply.key_services(scope, k) for k in keys},
                       'effective': st.effective(scope, revision),
                       'applied': st.effective(scope, st.applied_revision(scope, applied)),
                       'applied_revision': st.applied_revision(scope, applied), 'overrides': overrides,
                       'suggestions': st.suggestions(scope)})
    pending = [{'scope': scope, 'key': key, 'from': old, 'to': new}
               for scope, diff in apply.changes(st, s, revision).items() for key, (old, new) in diff.items()]
    history = sorted((st.folder / 'operations').glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    backup = dict(s.backup) if s.backup else None
    return {'revision': revision, 'applied': applied, 'scopes': scopes,
            'registry': [describe(x) for x in S.REGISTRY.values()], 'groups': GROUP_TITLES,
            'pending': pending, 'services': apply.services(st, s, revision), 'steps': apply.plan(st, s, revision),
            'active': operation_view(st, st.active()),
            # A queued Apply waits while another site operation, for example a deployment, holds the site lock.
            'site_operation': oplock.site_lock(s.operator_state()).busy(),
            'operations': [operation_view(st, st.operation(p.stem)) for p in history],
            'backup_destination': backup, 'nodes': nodes}


@synced
def save(actor, body):
    s = site()
    st = state(s)
    changes = body.get('changes')
    if not isinstance(changes, dict) or not isinstance(body.get('base'), int):
        raise Refused('The request needs base and changes.')
    allowed = set(apply.scopes(s))
    problems = {}
    for scope, values in changes.items():
        if scope not in allowed or not isinstance(values, dict):
            raise Refused(f'{scope} is not a scope of this site.')
        keys = set(apply.scope_keys(s, scope))
        for key, value in values.items():
            setting = S.REGISTRY.get(key)
            # A saved pool setting of an installation of the store layout site can only be removed (None).
            if setting is None or (key not in keys and not (value is None and setting.scope == scope.split(':')[0])):
                problems[f'{scope}/{key}'] = (f'{key} is a setting of the processing pools. Change it in the processing pools of the site.'
                                              if key in S.POOLED and scope.startswith('hoover:') else f'{key} is not a setting of this scope.')
                continue
            if value is not None:
                try:
                    setting.check(str(value))
                except S.SettingsError as error:
                    problems[f'{scope}/{key}'] = str(error)
    if problems:
        raise Refused('Correct the marked values. Nothing was saved.', problems=problems)
    try:
        revision = st.save(body['base'], {k: {kk: (None if vv is None else str(vv)) for kk, vv in v.items()}
                                          for k, v in changes.items()}, actor=actor)
    except S.StaleRevision as error:
        raise Refused(str(error), status=409)
    except S.SettingsError as error:
        raise Refused(str(error))
    return {'revision': revision}


@synced
def start(actor, body):
    s = site()
    st = state(s)
    if body.get('revision') != st.revision():
        raise Refused(f'The saved settings changed to revision {st.revision()}. Review the changes, then apply again.', status=409)
    if st.revision() == st.applied()['revision']:
        raise Refused('The saved settings are already applied.')
    steps, scope_steps = apply.plan_scopes(st, s)
    try:
        op = st.start_apply(apply.deployment_revision(s), steps, scope_steps)
    except S.OperationActive as error:
        raise Refused(str(error), status=409)
    return {'operation': op.id, 'steps': [x['name'] for x in op.steps]}


@synced
def retry(actor, body):
    try:
        return {'operation': state(site()).retry(str(body.get('id', '')), actor=actor).id}
    except S.SettingsError as error:
        raise Refused(str(error))


@synced
def abandon(actor, body):
    try:
        state(site()).abandon(str(body.get('id', '')), actor=actor)
    except S.SettingsError as error:
        raise Refused(str(error))
    return {'operation': body.get('id')}


ACTIONS = {'save': save, 'apply': start, 'retry': retry, 'abandon': abandon}
