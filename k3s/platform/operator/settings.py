#!/usr/bin/env python3
"""The operator settings of a cluster installation: the registry, the saved revisions and the apply operations.

The portal and the deployment command use this module, so they read, check, save and apply settings the same way.

Registry
  REGISTRY names every setting: its key, scope, type, default, range or choices, the services that it changes, and
  how a change reaches them. It holds every tuning and switch of the Hoover ini (deploy.py DEFAULTS), the Hoover
  settings of the cluster (budget, worker sandbox, slot tuner, administrator groups, volume sizes), and the existing
  cluster and openDesk controls (zone applications, zone memory limits, CPU policy). EXCLUDED names each ini key that
  is not a setting, and why. The default of an ini setting is its value in hoover4.ini.release.
  Scopes: hoover (one value for each Hoover installation of the site file), zone (one value for each zone),
  cluster (one value). A scope id is `hoover:<name>`, `zone:<zone>` or `cluster`.
  Apply modes: restart (the services restart with the new value), reconcile (the set of objects changes),
  expand (a volume grows, never shrinks), fixed (the value cannot change after the first apply).

State, in one folder on the control-plane host (config.Site.operator_state())
  revisions/<n>.json   the explicit operator values (overrides) of revision n. A written revision never changes.
  desired.json         the newest revision number, and the one-time seed records
  suggestions.json     hardware suggestions. A suggestion is shown, and changes nothing until an operator saves it.
  applied.json         the applied revision, the source revision of the deployment, and the previous applied record
  operations/<id>.json one apply operation: its pinned revisions, its steps, its status and its last error
  active.json          the operation that owns the installation, until it succeeds or an operator abandons it
Each file is written to a temporary file, synced and renamed, so a reader sees the old or the new file only.
A save names the revision that the operator edited. A save over a newer revision is refused (StaleRevision).
A save never starts an operation. Apply pins the newest revision and the source revision once. A retry or a runner
restart continues the same operation with the same revisions, at its first unfinished step. A later saved revision
waits for a new Apply. A failed operation keeps applied.json unchanged and records which services already changed.

Usage: settings.py list                         prints the registry as JSON
       settings.py show <state-folder> <scope>  prints the effective values of a scope
"""
import configparser
import contextlib
import fcntl
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parents[1]
REPO = K3S.parent
SCHEMA = 1


class SettingsError(ValueError):
    """A value or a request breaks the registry or the state rules."""


class StaleRevision(SettingsError):
    """The save names an older revision than the newest one."""


class OperationActive(SettingsError):
    """Another operation owns the installation."""


class RunnerBusy(SettingsError):
    """Another runner runs the operation now."""


@dataclass(frozen=True)
class Setting:
    key: str
    scope: str
    kind: str
    default: str
    services: tuple
    apply: str
    group: str
    ini: tuple = None
    env: str = None
    minimum: float = None
    maximum: float = None
    choices: tuple = ()
    empty: bool = False

    def check(self, value):
        """The value as stored text, or SettingsError."""
        if not isinstance(value, str):
            value = 'true' if value is True else 'false' if value is False else str(value)
        value = value.strip()
        if value == '' and self.empty:
            return ''
        label = f'{self.key} = {value!r}'
        if self.kind == 'bool':
            if value.lower() not in ('true', 'false'):
                raise SettingsError(f'{label} must be true or false.')
            return value.lower()
        if self.kind == 'choice':
            if value not in self.choices:
                raise SettingsError(f'{label} must be one of {", ".join(self.choices)}.')
            return value
        if self.kind in ('int', 'float', 'cpu'):
            pattern = r'[0-9]+' if self.kind == 'int' else r'[0-9]+(\.[0-9]+)?'
            if not re.fullmatch(pattern, value):
                raise SettingsError(f'{label} must be a {"whole" if self.kind == "int" else ""} number.'.replace('  ', ' '))
            number = float(value)
            if self.minimum is not None and number < self.minimum:
                raise SettingsError(f'{label} must be at least {self.minimum:g}.')
            if self.maximum is not None and number > self.maximum:
                raise SettingsError(f'{label} must be at most {self.maximum:g}.')
            return value
        if self.kind == 'size':
            if not re.fullmatch(r'[0-9]+(\.[0-9]+)?[kKmMgGtT]?[bB]?|[0-9]+([KMGT]i)', value):
                raise SettingsError(f'{label} must be a size such as 4G or 512M.')
            if size_bytes(value) <= 0:
                raise SettingsError(f'{label} must be greater than zero.')
            return value
        if self.kind == 'duration':
            if not re.fullmatch(r'[0-9]+[smhd]', value):
                raise SettingsError(f'{label} must be a duration such as 168h.')
            return value
        if self.kind == 'text':
            if '\n' in value or (value == '' and not self.empty):
                raise SettingsError(f'{label} must be one line of text.')
            return value
        raise AssertionError(self.kind)


def size_bytes(text):
    m = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)([kKmMgGtT]?)(i?)[bB]?', text.strip())
    if not m:
        return 0
    return int(float(m.group(1)) * 1024 ** ' KMGT'.index((m.group(2) or ' ').upper()))


# ----------------------------------------------------------------------------------------------------------------------
# The registry
# ----------------------------------------------------------------------------------------------------------------------

def deploy_module():
    spec = importlib.util.spec_from_file_location('hoover_deploy_settings', REPO / 'deploy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The ini keys that are not operator settings. Each reason says where the value comes from instead.
EXCLUDED = {
    ('storage', 'volumes_path'): 'The cluster gives each volume its own claim.',
    ('storage', 'garage_capacity'): 'The renderer derives it from the size of the Garage data volume.',
    ('ai_services', 'enabled'): 'The [gpu_pool] section of the site file turns the GPU services on.',
    ('ai_services', 'host'): 'The GPU forwarder of the Hoover namespace is the GPU host.',
    ('ai_services', 'bind_ip'): 'The GPU installation publishes its own ports.',
    ('ai_services', 'vllm_api_key_file'): 'The key is a secret file of [gpu_pool] in the site file.',
    ('main_services', 'website_release_mode'): 'The cluster runs the release image.',
    ('main_services', 'development_auth_backdoor_enabled'): 'Keycloak and oauth2-proxy sign in every user.',
    ('main_services', 'proxy_username'): 'Only the development identity proxy reads it.',
    ('main_services', 'proxy_groups'): 'Only the development identity proxy reads it.',
    ('main_services', 'website_bind_ip'): 'Kubernetes Services and the ingress replace published ports.',
    ('main_services', 'infra_bind_ip'): 'Kubernetes Services and the ingress replace published ports.',
    ('main_services', 'mcp_shared_secret_file'): 'The secret setup step writes the Secret hoover-runtime.',
    ('main_services', 'browser_fetch_token_file'): 'The secret setup step writes the Secret hoover-runtime.',
    ('main_services', 'factcheck_api_key_file'): 'The secret setup step writes the Secret hoover-runtime.',
    ('main_services', 'chat_control_dir'): 'The chat_control_dir of the site file names the host folder.',
    ('main_services', 'ops_backup_dir'): 'The backup volume of the installation holds the backups.',
    ('main_services', 'admin_base_url'): 'The renderer derives it from the public name of the installation.',
    ('main_services', 'container_log_max_size'): 'The kubelet rotates the container logs.',
    ('main_services', 'container_log_max_files'): 'The kubelet rotates the container logs.',
}

BOOL_KEYS = {'automatic', 'clamav_update_signatures', 'llm_streaming'}
CHOICES = {('main_services', 'pdf_ocr_provider'): ('tesseract', 'easyocr', 'both', 'none')}
# The switches that change the set of services. A change reconciles the objects of the installation.
RECONCILE = {('main_services', k) for k in ('internet_tools_enabled', 'web_tor_enabled', 'tesseract_cpu_enabled',
                                             'clamav_enabled', 'ocr_pdf_enabled')} | {('ai_services', 'llm_enabled')}
WORKER = 'hoover4-worker'
WEBSITE = 'hoover4-website'
AGENTS = ('hoover4-internal-search-agent', 'hoover4-full-research-agent')
FINGERPRINT = ('hoover4-mcp-collections', 'hoover4-ocr-pdf', 'hoover4-regex-entity-scanner', 'hoover4-tesseract-cpu')
# The services of each ini key, by the first matching rule: (section or None, key pattern, services).
SERVICE_RULES = [
    ('operations', r'.*', ('hoover4-ops',)),
    ('uploads', r'.*', (WEBSITE, WORKER)),
    ('processing_updates', r'.*', (WEBSITE, WORKER)),
    ('ai_services', r'ai_server_.*_concurrency', ('gpu-pool',)),
    # Every [ai_services] key is part of the configuration fingerprint, which several services report.
    ('ai_services', r'llm_enabled', (WORKER, WEBSITE, *AGENTS, *FINGERPRINT)),
    ('ai_services', r'.*', (WORKER, WEBSITE, *FINGERPRINT)),
    (None, r'temporal_history_shards', ('temporal',)),
    (None, r'cassandra_.*', ('temporal-cassandra',)),
    (None, r'temporal_ui_.*', ('temporal-ui',)),
    (None, r'temporal_.*', ('temporal',)),
    (None, r'clickhouse_ui_mem_limit', ('ch-ui',)),
    (None, r'clickhouse_monitoring_mem_limit', ('clickhouse-monitoring',)),
    (None, r'clickhouse_.*', ('clickhouse',)),
    (None, r'manticore_vectors_mem_limit', ('manticore-vectors', WORKER)),
    (None, r'manticore_mem_limit', ('manticore',)),
    (None, r'manticore_expansion_limit', (WEBSITE, 'hoover4-mcp-collections')),
    (None, r'tika_.*', ('hoover4-tika', WORKER)),
    (None, r'tesseract_.*', ('hoover4-tesseract-cpu', WORKER, WEBSITE)),
    (None, r'(ocr_pdf_.*|pdf_preview_concurrency)', ('hoover4-ocr-pdf', WORKER, WEBSITE)),
    (None, r'pdf_ocr_provider', (WORKER, WEBSITE)),
    (None, r'clamav_.*', ('hoover4-clamav', WORKER)),
    (None, r'regex_scanner_.*', ('hoover4-regex-entity-scanner', WORKER, WEBSITE)),
    (None, r'(browser_.*|mcp_browser_mem_limit)', ('hoover4-mcp-browser', 'hoover4-mcp-metasearch')),
    (None, r'web_search_.*', ('hoover4-mcp-metasearch',)),
    (None, r'web_tor_.*', ('hoover4-web-tor', 'hoover4-mcp-metasearch', 'hoover4-mcp-browser')),
    (None, r'internet_tools_enabled', ('hoover4-mcp-whois', 'hoover4-mcp-metasearch', 'hoover4-mcp-browser',
                                       'hoover4-web-tor', *AGENTS, WORKER, WEBSITE, 'hoover4-ops')),
    (None, r'full_research_agent_workers', ('hoover4-full-research-agent',)),
    (None, r'(agent_.*|llm_.*|title_request_timeout_seconds|board_reason_request_seconds)', (WORKER, *AGENTS)),
    (None, r'(max_held_polls_per_user|rate_chat_poll_per_minute|error_rate_alert_percent|search_.*)',
     (WEBSITE, 'hoover4-mcp-collections')),
    (None, r'(ops_.*)', ('hoover4-ops',)),
    (None, r'worker_graceful_shutdown_seconds', (WORKER, 'hoover4-ops')),
    (None, r'gpu_.*', (WORKER, 'hoover4-mcp-collections')),
    (None, r'.*', (WORKER,)),
]


def _kind(section, key, default):
    if (section, key) in CHOICES:
        return 'choice'
    if key.endswith('_enabled') or key in BOOL_KEYS:
        return 'bool'
    if key == 'temporal_retention':
        return 'duration'
    if key == 'agent_packs_chat':
        return 'text'
    if key.endswith(('_mem_limit', '_heap', '_heap_new', '_direct_memory')) or key == 'tika_parse_heap':
        return 'size'
    if key.endswith('_cpus'):
        return 'cpu'
    if key.endswith(('_ratio', '_fraction')):
        return 'float'
    return 'int'


def _services(section, key):
    for rule_section, pattern, services in SERVICE_RULES:
        if (rule_section is None or rule_section == section) and re.fullmatch(pattern, key):
            return services
    raise AssertionError(key)


def _release_values():
    parser = configparser.ConfigParser(interpolation=None, default_section='\n')
    parser.read(REPO / 'hoover4.ini.release')
    return parser


def _ini_settings(deploy):
    release = _release_values()
    out = []
    for section, keys in deploy.DEFAULTS.items():
        for key, code_default in keys.items():
            if (section, key) in EXCLUDED or key.endswith('_port'):
                continue
            default = release.get(section, key, fallback=code_default).strip()
            kind = _kind(section, key, default)
            apply = 'fixed' if key == 'temporal_history_shards' else 'reconcile' if (section, key) in RECONCILE else 'restart'
            group = ('switch' if kind == 'bool' or kind == 'choice' else
                     'size' if kind in ('size', 'cpu') or key.endswith('_mem_limit') else 'tuning')
            minimum = 1 if kind in ('int', 'cpu') and not key.endswith(('_bytes', '_cap', 'arenas', '_mb', '_qps')) else 0
            if kind == 'float':
                minimum = 0
            out.append(Setting(
                key=f'{section}.{key}', scope='hoover', kind=kind, default=default, services=_services(section, key),
                apply=apply, group=group, ini=(section, key), minimum=minimum if kind in ('int', 'cpu', 'float') else None,
                choices=CHOICES.get((section, key), ()), empty=code_default == '' or default == ''))
    return out


# The Hoover settings of the cluster, which no ini key holds. The renderer reads them (../../hoover/manifests.py).
WORKER_PODS = ('hoover-workers',)
CLUSTER_HOOVER = [
    Setting('budget.worker_pods', 'hoover', 'int', '1', WORKER_PODS, 'restart', 'budget', minimum=1, maximum=64),
    Setting('budget.worker_memory_mib', 'hoover', 'int', '6144', WORKER_PODS, 'restart', 'budget', minimum=3072),
    Setting('budget.worker_cpus', 'hoover', 'int', '4', WORKER_PODS, 'restart', 'budget', minimum=1, maximum=256),
    Setting('budget.tika_cpus', 'hoover', 'int', '2', ('hoover4-tika', 'hoover-workers'), 'restart', 'budget', minimum=1),
    Setting('budget.tesseract_cpus', 'hoover', 'int', '2', ('hoover4-tesseract-cpu', 'hoover-workers'), 'restart', 'budget', minimum=1),
    Setting('budget.ocr_pdf_slots', 'hoover', 'int', '1', ('hoover4-ocr-pdf', 'hoover-workers'), 'restart', 'budget', minimum=1),
    Setting('budget.browser_contexts', 'hoover', 'int', '4', ('hoover4-mcp-browser',), 'restart', 'budget', minimum=1),
    Setting('budget.clamav_memory_mib', 'hoover', 'int', '3072', ('hoover4-clamav',), 'restart', 'budget', minimum=1024),
    Setting('workers.parser_sandbox', 'hoover', 'choice', 'off', WORKER_PODS + ('hoover-singletons',), 'restart', 'switch',
            env='HOOVER4_PARSER_SANDBOX', choices=('off', 'bwrap')),
    Setting('workers.slot_tuner', 'hoover', 'choice', 'fixed', WORKER_PODS, 'restart', 'switch',
            env='HOOVER4_SLOT_TUNER', choices=('fixed', 'resource')),
    Setting('workers.tuner_target_memory', 'hoover', 'float', '0.8', WORKER_PODS, 'restart', 'tuning',
            env='HOOVER4_TUNER_TARGET_MEMORY', minimum=0.1, maximum=0.95),
    Setting('workers.tuner_target_cpu', 'hoover', 'float', '0.9', WORKER_PODS, 'restart', 'tuning',
            env='HOOVER4_TUNER_TARGET_CPU', minimum=0.1, maximum=1.0),
    Setting('website.admin_groups', 'hoover', 'text', 'Domain Admins', ('hoover-website',), 'restart', 'switch',
            env='HOOVER4_ADMIN_GROUPS'),
]
# The volume claims of a Hoover installation and their first sizes. The local store layout uses every claim. The zone
# store layout uses the upload, backup and worker claims.
VOLUMES = {
    'clickhouse-data': '20Gi', 'manticore-data': '10Gi', 'manticore-vectors-data': '10Gi', 'garage-meta': '1Gi',
    'garage-data': '20Gi', 'temporal-cassandra': '20Gi', 'temporal-elasticsearch': '10Gi', 'ops-backups': '50Gi',
    'upload-tmp': '20Gi', 'worker-temp-files': '20Gi', 'clickhouse-monitoring': '1Gi',
}
CLUSTER_HOOVER += [Setting(f'volume.{name}', 'hoover', 'size', size, (name,), 'expand', 'volume')
                   for name, size in VOLUMES.items()]
# The openDesk applications of a zone (../../zones/zones.py) and Hoover.
APPLICATIONS = ('nextcloud', 'collabora', 'cryptpad', 'element', 'jitsi', 'openproject', 'xwiki', 'notes', 'hoover')
ZONE_SETTINGS = [Setting('zone.enabled', 'zone', 'bool', 'true', ('zone',), 'reconcile', 'switch')]
ZONE_SETTINGS += [Setting(f'app.{name}', 'zone', 'bool', 'true', (name,), 'reconcile', 'switch') for name in APPLICATIONS]


def _zone_memory():
    data = json.loads((K3S / 'zones/memory-limits.json').read_text())
    out = []
    for workload, containers in data['zone'].items():
        for container, limit in containers.items():
            out.append(Setting(f'memory.{workload}.{container}', 'zone', 'size', limit, (workload,), 'restart', 'size'))
    for name, limit in data['hoover'].items():
        out.append(Setting(f'memory.hoover.{name}', 'hoover', 'size', limit, (name,), 'restart', 'size'))
    return out


def _cpu_policy():
    data = json.loads((K3S / 'zones/cpu-policy.json').read_text())
    return [
        Setting('cpu.oversubscription', 'cluster', 'int', str(data['oversubscription']), ('all',), 'restart', 'tuning', minimum=1),
        Setting('cpu.allocation', 'cluster', 'text', data['allocation'], ('all',), 'restart', 'tuning'),
        Setting('cpu.limit', 'cluster', 'text', data['limit'], ('all',), 'restart', 'tuning'),
        Setting('cpu.slow_start_limit', 'cluster', 'text', data['slowStart']['limit'], ('all',), 'restart', 'tuning'),
    ]


def build_registry():
    items = _ini_settings(deploy_module()) + CLUSTER_HOOVER + ZONE_SETTINGS + _zone_memory() + _cpu_policy()
    registry = {}
    for item in items:
        if item.key in registry:
            raise AssertionError(f'two settings have the key {item.key}')
        registry[item.key] = item
    return registry


REGISTRY = build_registry()


def scope_of(scope_id):
    kind = scope_id.split(':', 1)[0]
    if kind not in ('hoover', 'zone', 'cluster') or (kind != 'cluster') != (':' in scope_id):
        raise SettingsError(f'{scope_id} is not a scope. Use hoover:<name>, zone:<zone> or cluster.')
    return kind


def check_values(scope_id, values, registry=REGISTRY):
    """The checked text of each value. A key outside the registry or the scope is an error."""
    kind = scope_of(scope_id)
    out, problems = {}, []
    for key, value in values.items():
        setting = registry.get(key)
        if setting is None:
            problems.append(f'{key} is not a setting.')
        elif setting.scope != kind:
            problems.append(f'{key} belongs to the {setting.scope} scope, not {scope_id}.')
        elif value is None:
            out[key] = None
        else:
            try:
                out[key] = setting.check(value)
            except SettingsError as error:
                problems.append(str(error))
    if problems:
        raise SettingsError('\n'.join(problems))
    return out


def effective(scope_id, overrides, registry=REGISTRY):
    """The value of every setting of a scope: the override, else the budget suggestion, else the default."""
    kind = scope_of(scope_id)
    values = {k: s.default for k, s in registry.items() if s.scope == kind}
    if kind == 'hoover':
        sys.path.insert(0, str(K3S / 'hoover'))
        import zone_ini
        budget = {k: int(overrides.get(f'budget.{k}', values[f'budget.{k}'])) for k in zone_ini.BUDGET}
        for (section, key), value in zone_ini.derive(budget).items():
            if f'{section}.{key}' in values:
                values[f'{section}.{key}'] = value
    values.update(overrides)
    return values


def ini_values(values, registry=REGISTRY):
    """The {(section, key): text} of the ini settings of a set of effective values."""
    return {registry[k].ini: v for k, v in values.items() if registry[k].ini}


# ----------------------------------------------------------------------------------------------------------------------
# State
# ----------------------------------------------------------------------------------------------------------------------

def write_json(path, data):
    """Write a JSON file so that a reader sees either the old or the new file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp')
    with open(tmp, 'w') as handle:
        handle.write(json.dumps(data, indent=1, sort_keys=True) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    folder = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


@dataclass
class Operation:
    id: str
    desired_revision: int
    source_revision: str
    steps: list
    status: str = 'running'
    error: str = ''
    changed: list = field(default_factory=list)
    created: str = ''
    updated: str = ''
    attempts: int = 1

    def next_step(self):
        for step in self.steps:
            if step['status'] != 'done':
                return step
        return None


class State:
    """The operator state of one installation, in one folder on the control-plane host."""

    def __init__(self, folder, registry=REGISTRY):
        self.folder = Path(folder)
        self.registry = registry
        self.folder.mkdir(parents=True, exist_ok=True)

    # Locks. The state lock covers each change of a file. The runner lock is held while a runner runs an operation.
    @contextlib.contextmanager
    def _lock(self, name='state.lock', blocking=True):
        with open(self.folder / name, 'a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                raise RunnerBusy('another runner runs the operation now') from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _desired(self):
        return read_json(self.folder / 'desired.json', {'schema': SCHEMA, 'revision': 0, 'seeded': {}})

    def revision(self):
        return self._desired()['revision']

    def overrides(self, revision=None):
        """{scope id: {key: value}} of a revision. Revision 0 has no override."""
        revision = self.revision() if revision is None else revision
        if revision == 0:
            return {}
        data = read_json(self.folder / 'revisions' / f'{revision}.json')
        if data is None:
            raise SettingsError(f'revision {revision} is missing from {self.folder}')
        return data['overrides']

    def effective(self, scope_id, revision=None):
        return effective(scope_id, self.overrides(revision).get(scope_id, {}), self.registry)

    def applied(self):
        return read_json(self.folder / 'applied.json', {'revision': 0, 'source_revision': '', 'operation': '', 'previous': None})

    def save(self, base_revision, changes, actor='', note=''):
        """Save {scope id: {key: value or None}} over base_revision as a new revision. None removes an override.

        Returns the new revision. Starts no operation and changes no service.
        """
        checked = {scope: check_values(scope, values, self.registry) for scope, values in changes.items()}
        with self._lock():
            desired = self._desired()
            if desired['revision'] != base_revision:
                raise StaleRevision(f'the settings changed to revision {desired["revision"]} after revision {base_revision}. '
                                    'Load them again and repeat the change.')
            overrides = json.loads(json.dumps(self.overrides(desired['revision'])))
            applied = self.applied()
            for scope, values in checked.items():
                current = overrides.setdefault(scope, {})
                for key, value in values.items():
                    if value is None:
                        current.pop(key, None)
                    else:
                        current[key] = value
                if not current:
                    overrides.pop(scope)
            applied = self.applied()['revision']
            if applied:
                before_all = self.overrides(applied)
                for scope, values in checked.items():
                    before = effective(scope, before_all.get(scope, {}), self.registry)
                    after = effective(scope, overrides.get(scope, {}), self.registry)
                    for key in values:
                        setting = self.registry[key]
                        if setting.apply == 'fixed' and after[key] != before[key]:
                            raise SettingsError(f'{key} is fixed after the first apply. It stays {before[key]}.')
                        if setting.apply == 'expand' and size_bytes(after[key]) < size_bytes(before[key]):
                            raise SettingsError(f'{key} = {after[key]} is smaller than the applied size {before[key]}. '
                                                'A volume only grows.')
            revision = desired['revision'] + 1
            write_json(self.folder / 'revisions' / f'{revision}.json',
                       {'revision': revision, 'base': base_revision, 'overrides': overrides, 'saved': now(),
                        'actor': actor, 'note': note})
            desired['revision'] = revision
            write_json(self.folder / 'desired.json', desired)
            return revision

    def suggest(self, scope_id, values):
        """Record hardware suggestions. They change no saved value and no revision."""
        checked = check_values(scope_id, values, self.registry)
        with self._lock():
            data = read_json(self.folder / 'suggestions.json', {})
            data[scope_id] = {'values': checked, 'recorded': now()}
            write_json(self.folder / 'suggestions.json', data)

    def suggestions(self, scope_id):
        return (read_json(self.folder / 'suggestions.json', {}).get(scope_id) or {}).get('values', {})

    def seed(self, scope_id, source, actor='seed'):
        """Save the explicit ini values of a source Compose install once, as overrides of a Hoover scope.

        source is a config.SourceInstall. A key with an override keeps it. A value equal to the default is left out.
        A second call for the same scope saves nothing. Returns the new revision, or None.
        """
        if scope_of(scope_id) != 'hoover':
            raise SettingsError('only a Hoover scope takes the values of a Compose ini')
        while True:
            desired = self._desired()
            if scope_id in desired['seeded']:
                return None
            base = desired['revision']
            current = self.overrides(base).get(scope_id, {})
            defaults = effective(scope_id, {}, self.registry)
            changes, refused = {}, []
            for label in source.explicit:
                section, key = label.split('.', 1)
                setting = self.registry.get(f'{section}.{key}')
                if setting is None or not setting.ini or setting.key in current:
                    continue
                value = source.values[section][key]
                try:
                    value = setting.check(value)
                except SettingsError as error:
                    refused.append(str(error))
                    continue
                if value != defaults[setting.key]:
                    changes[setting.key] = value
            if refused:
                raise SettingsError('the source ini has values that the settings refuse:\n' + '\n'.join(refused))
            try:
                with self._lock():
                    if scope_id in self._desired()['seeded']:
                        return None
                revision = self.save(base, {scope_id: changes} if changes else {}, actor=actor,
                                     note=f'values of {source.path}')
            except StaleRevision:
                continue
            with self._lock():
                desired = self._desired()
                desired['seeded'][scope_id] = {'source': source.path, 'revision': revision, 'keys': sorted(changes)}
                write_json(self.folder / 'desired.json', desired)
            return revision

    # Operations
    def active(self):
        data = read_json(self.folder / 'active.json')
        return self.operation(data['id']) if data else None

    def operation(self, operation_id):
        data = read_json(self.folder / 'operations' / f'{operation_id}.json')
        if data is None:
            raise SettingsError(f'operation {operation_id} does not exist')
        return Operation(**data)

    def _write_operation(self, op):
        op.updated = now()
        write_json(self.folder / 'operations' / f'{op.id}.json', asdict(op))

    def start_apply(self, source_revision, steps):
        """Create the apply operation of the newest revision. It pins that revision and the source revision."""
        with self._lock():
            active = self.active()
            if active:
                raise OperationActive(f'operation {active.id} ({active.status}) owns the installation. '
                                      'Retry it or abandon it first.')
            op = Operation(id=f'op-{int(time.time())}-{uuid.uuid4().hex[:6]}', desired_revision=self.revision(),
                           source_revision=source_revision, created=now(),
                           steps=[{'name': name, 'status': 'pending', 'started': '', 'finished': ''} for name in steps])
            self._write_operation(op)
            write_json(self.folder / 'active.json', {'id': op.id})
            return op

    def abandon(self, operation_id, actor=''):
        """End a failed operation without applying it. applied.json stays unchanged."""
        with self._lock():
            op = self.operation(operation_id)
            if op.status != 'failed':
                raise SettingsError(f'operation {op.id} is {op.status}. Only a failed operation can be abandoned.')
            op.status = 'abandoned'
            op.error += f' Abandoned by {actor or "the operator"}.'
            self._write_operation(op)
            (self.folder / 'active.json').unlink()

    def run(self, executors):
        """Run the active operation from its first unfinished step to its end.

        executors maps a step name to a function(operation, overrides) that returns the list of services that it
        changed. Each step is recorded before it starts and after it ends. A failed step records its error and leaves
        the operation active, so a later run continues at that step with the same pinned revisions.
        """
        with self._lock('runner.lock', blocking=False):
            op = self.active()
            if op is None:
                return None
            overrides = self.overrides(op.desired_revision)
            with self._lock():
                if op.status == 'failed':
                    op.attempts += 1
                op.status, op.error = 'running', ''
                self._write_operation(op)
            while True:
                step = op.next_step()
                if step is None:
                    break
                with self._lock():
                    step['status'], step['started'] = 'running', now()
                    self._write_operation(op)
                try:
                    changed = executors[step['name']](op, overrides) or []
                except Exception as error:  # noqa: BLE001  The error goes into the operation record.
                    with self._lock():
                        step['status'], op.status = 'failed', 'failed'
                        op.error = f'{step["name"]}: {type(error).__name__}: {error}'
                        self._write_operation(op)
                    return op
                with self._lock():
                    step['status'], step['finished'] = 'done', now()
                    op.changed = sorted(set(op.changed) | set(changed))
                    self._write_operation(op)
            with self._lock():
                previous = self.applied()
                previous.pop('previous', None)
                write_json(self.folder / 'applied.json', {
                    'revision': op.desired_revision, 'source_revision': op.source_revision, 'operation': op.id,
                    'applied': now(), 'previous': previous if previous.get('revision') else None})
                op.status = 'succeeded'
                self._write_operation(op)
                (self.folder / 'active.json').unlink()
            return op


def main(argv):
    if argv == ['list']:
        print(json.dumps({k: asdict(s) for k, s in REGISTRY.items()}, indent=1))
    elif len(argv) == 3 and argv[0] == 'show':
        print(json.dumps(State(argv[1]).effective(argv[2]), indent=1, sort_keys=True))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
