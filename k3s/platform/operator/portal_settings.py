"""The settings pages of the operator portal: read, save, Apply, retry and abandon, through settings.py and apply.py.

The portal pod runs on the control-plane node. It mounts the k3s folder of the checkout read-only (PORTAL_REPO), the
operator state folder read-write and the site file read-only. It does not mount the other private files.
runner.py on the host runs the Apply operations that this module starts.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get('PORTAL_REPO', '/repo'))
sys.path.insert(0, str(REPO / 'k3s'))
sys.path.insert(0, str(REPO / 'k3s/platform/operator'))
import config  # noqa: E402
import apply  # noqa: E402
import oplock  # noqa: E402

S = apply.operator_settings
GROUP_TITLES = {'budget': 'Hoover resources', 'switch': 'Switches', 'tuning': 'Tunings', 'volume': 'Volume sizes',
                'size': 'Memory limits', 'backup': 'Backups'}


class Refused(Exception):
    """A request that the portal refuses. The message goes back to the operator."""

    def __init__(self, message, status=400, problems=None):
        super().__init__(message)
        self.status, self.problems = status, problems or {}


def site():
    return config.read(os.environ.get('HOOVER4_SITE') or config.DEFAULT_SITE)


def state(s):
    return S.State(s.operator_state())


def suggestions(s, nodes):
    """Hardware suggestions for each Hoover installation, from the allocatable CPU and memory of its home node."""
    out = {}
    for hoover in s.hoovers.values():
        node = nodes.get(hoover.home_node)
        if not node:
            continue
        cpus, memory_mib = node['cpus'], node['memory_mib']
        out[f'hoover:{hoover.name}'] = {
            'budget.worker_cpus': str(max(2, cpus // 3)),
            'budget.worker_memory_mib': str(max(3072, min(32768, memory_mib // 4 // 512 * 512))),
            'budget.tika_cpus': str(max(1, cpus // 8)),
            'budget.tesseract_cpus': str(max(1, cpus // 8)),
            'budget.worker_pods': str(max(1, len([n for n in s.nodes.values() if n.has('worker')]))),
        }
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
        scopes.append({'id': scope, 'effective': st.effective(scope, revision),
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
            'site_operation': oplock.SiteLock(s.operator_state()).busy(),
            'operations': [operation_view(st, st.operation(p.stem)) for p in history],
            'backup_destination': backup, 'nodes': nodes}


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
        for key, value in values.items():
            setting = S.REGISTRY.get(key)
            if setting is None or setting.scope != scope.split(':')[0]:
                problems[f'{scope}/{key}'] = f'{key} is not a setting of this scope.'
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


def retry(actor, body):
    try:
        return {'operation': state(site()).retry(str(body.get('id', '')), actor=actor).id}
    except S.SettingsError as error:
        raise Refused(str(error))


def abandon(actor, body):
    try:
        state(site()).abandon(str(body.get('id', '')), actor=actor)
    except S.SettingsError as error:
        raise Refused(str(error))
    return {'operation': body.get('id')}


ACTIONS = {'save': save, 'apply': start, 'retry': retry, 'abandon': abandon}
