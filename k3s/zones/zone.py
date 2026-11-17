#!/usr/bin/env python3
"""Create, upgrade or delete one zone: openDesk, its stores and its Hoover. This is the one installer command of a zone.

Usage:
  zone.py apply <zone> [--stores site|local] [--full]
                [--dataset name:node:/path ...]
                                          create the zone, or bring it to the source state. The options set the
                                          values of a new zone (zonestate.py), and each option must match for an
                                          existing zone. --home <node> of an earlier version is accepted and has no
                                          effect, because the scheduler places the pods of a zone. --full runs the
                                          openDesk waves also when no input changed (step 5).
  zone.py delete <zone>                  delete the zone namespaces with their volumes, and the zone entry.
The zone state of the state folder holds the zones. The site file names no zone.
Apply reads the current state before each step. Verify unchanged output with ../tools/zone-snapshot.py after an upgrade.
An apply of a disabled zone saves a private render without applying objects or running hooks.
The steps of apply, in order:
  1. The zone state (zonestate.py) gets the zone with the values of its Hoover installation.
     zones.py writes the openDesk values.
  2. The step checks that the registry has the images of the revision. deploy-k3s up builds them (step images).
  3. The cluster gets the zone pod policy (manifests/zone-pods.yaml) and the XWiki extension repository. The zone
     runner cannot change the pod policy, so with its kubeconfig the step only checks that the cluster has the policy
     of the source.
  4. The zone namespaces get their labels, the RoleBinding of the zone runner, the network policy and the Hoover and
     gate client Secrets. A zone of the store layout site gets its openDesk buckets and key in the shared Garage, and
     the Ingress of its object storage host (objectstore.py ensure()). A zone of an earlier version moves its objects
     from SeaweedFS to Garage first (objectstore.py move()), when the kubeconfig may keep the SeaweedFS volume. The
     waves of step 5 then switch the applications, and Helm removes SeaweedFS. The entries of objectstore.py
     SECOND_PASS run once more after a move. After step 5 the applications that hold the key restart once
     (objectstore.py finish()).
  5. helmfile installs openDesk wave by wave (OPENDESK_WAVES), with postrender.py as the Helm post-renderer. The
     entries of one wave (the sub-helmfiles of the release) run at the same time, each in its own helmfile process with
     its own Helm configuration. They share the chart cache <state folder>/opendesk-charts (CHART_CACHE): helmfile
     pulls a chart version once, verifies its signature, and keeps it. An entry without an installed release, or with a release that is not deployed, uses
     helmfile sync, and an entry with only deployed releases uses helmfile apply with a server-side diff. A release
     list that differs from the waves stops the install. A failed entry runs once more on its own after the repair of
     its known cause, and the log names the cause: a new zone has no 2fa-browser flow, which the openDesk Keycloak
     bootstrap Job needs, so zone-login-no-mfa.sh creates it (nubus). Nextcloud restarts when its pod started before
     the management Job stored the complete configuration (nextcloud). A zone whose first install has not completed
     loses the Nextcloud user OpenProject that a failed OpenProject bootstrap left behind (opendesk-openproject-bootstrap).
     The zone state records the completion (bootstrapped), so an existing zone keeps its OpenProject integration.
     While the waves run, a helper sets the login flow as soon as zone-login-no-mfa.sh succeeds, checks Nextcloud, and replaces
     outdated OnDelete pods and outdated pods that block a StatefulSet rollout.
     The waves and step 6 run only when an input changed (opendesk_changes()): the digest of every input that they read
     (opendesk_inputs()) differs from the record of the last complete run, or a Helm release of the zone namespace has
     another revision or a status other than deployed. The record is zones/<zone>/opendesk-applied.json of the state
     folder, in the cluster copy of the zone secrets, so every operator host reads the same record. --full runs the
     waves and step 6 without this check, for example after a change by hand.
  6. zone-login-no-mfa.sh, zone-users.py and zone-patches.py set the login flow, the users and the application state.
     When the waves do not run, only the Collabora discovery check of zone-patches.py runs, because a Nextcloud start
     before Collabora is ready breaks the discovery without an input change. gate.py adds the sign-in service of the
     zone gate.
  7. The Hoover stores, their users and buckets, and the Hoover deployment follow (../hoover/). A zone with
     stores = site (every new zone, with temporal = site and manticore = site) gets a tenant in the shared ClickHouse,
     Garage, Manticore and Temporal of the site, which deploy-k3s up creates (step stores, ../hoover/stores/shared.py
     and temporal.py). Such a zone uses the processing pools of the site (../hoover/pools.py): the zone creates them
     when the site has none and changes no running pool. A zone with stores = local in the zone state gets its Secrets
     from setup.py local-secrets and its objects from manifests.py, with the Compose stores and Temporal in its Hoover
     namespace. A zone with
     stores = zone, or with stores = site and temporal = zone or manticore = zone, is from an earlier version and is
     refused: delete it and create it again.
Delete removes the tenant of a zone with stores = site from the shared stores first: its ClickHouse databases, users
and profile, its Garage buckets and keys, its Manticore tables and users, and its Temporal namespace
(../hoover/stores/shared.py remove), with the openDesk buckets, the openDesk key and the Ingress of the object storage
host. The S3 client in a Garage pod empties the buckets, so a disabled zone is removed the same way. When a part fails or an object stays, the delete stops with the message of shared.py, and the
zone keeps its namespaces and its zone state entry. Repair the store and delete the zone again.
The two namespaces of the zone are then deleted at the same time. The delete of the last zone with stores = site
removes the processing pools. A SeaweedFS volume that a move kept is deleted with the admin kubeconfig. The zone
runner prints its name instead.
  8. write-password-table.py writes the logins into the inventory.
KUBECONFIG names the admin kubeconfig. The default is <state folder>/kubeconfig.
openDesk needs Helm 3 and helmfile in <state folder>/bin/opendesk and the release in <state folder>/downloads.
The command holds the site operation lock (../oplock.py), or runs inside the operation of deploy-k3s or the zone
runner. With the lock of a running cluster it first reads the cluster copy of the zone state and the zone secrets
(../clusterstate.py). With HOOVER4_CLUSTER_STATE=1 (the operator pod, deploy-k3s and this case), apply and delete
write the zone state and the zone secrets into the cluster copy as soon as they change.
"""
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
sys.path.insert(0, str(SOURCE))
import clusterstate  # noqa: E402
import settings  # noqa: E402
import zonestate  # noqa: E402

PRIVATE = settings.PRIVATE
OPENDESK = PRIVATE / 'downloads/opendesk-v1.19.1/src'
TOOLS = PRIVATE / 'bin/opendesk'
STORES = SOURCE / 'hoover' / 'stores'
# The chart cache of the openDesk waves. helmfile keeps each pulled chart version in <cache>/<repository>/<chart>/<version>
# and takes a lock file for each version, so the processes of both zones share the folder. A version that is in the
# cache is not pulled again. Remove the folder to pull every chart again. It is not part of the cluster copy.
CHART_CACHE = PRIVATE / 'opendesk-charts'
# The record of the last complete openDesk run of a zone, in the zone folder of the cluster copy of the zone secrets.
RECORD_NAME = 'opendesk-applied.json'
# The files of the checkout, relative to k3s/, that the openDesk waves and the application state steps read: this
# installer, the post-renderer with the modules and tables that it reads, the pinned tool versions, and the scripts of
# step 6. test_zones.py checks that the list names every local module of the post-renderer.
INPUT_SOURCES = (
    'zones/zone.py', 'zones/postrender.py', 'zones/cpu_policy.py', 'zones/cpu-policy.json', 'zones/cpu_requests.py',
    'zones/cpu-requests.json', 'zones/memory_requests.py', 'zones/memory-requests.json', 'zones/memory-limits.json',
    'zones/zonestate.py', 'zones/synapse', 'zones/openproject', 'hoover/stores/podspec.py', 'settings.py', 'config.py',
    'platform/operator/settings.py', 'cluster/runtimeclasses.yaml', 'driver/artifacts.json',
    'zones/zone-login-no-mfa.sh', 'zones/zone-users.py', 'zones/zone-users.json', 'zones/udm.py',
    'zones/zone-patches.py', 'zones/zone-ai.py', 'zones/nextcloud-ai.py', 'zones/xwiki-ai.sh',
    'zones/xwiki-admin-script.py', 'zones/zone-jobs.py',
)
# The environment variables of a helmfile process that the openDesk helmfiles read (env and requiredEnv).
INPUT_ENV = ('DOMAIN', 'MAIL_DOMAIN', 'MATRIX_DOMAIN', 'MASTER_PASSWORD', 'DEBUG_ENABLED')
INPUT_ENV_PREFIXES = ('OPENDESK_', 'OD_', 'DOVECOT_')
# The helmfile processes of a wave print their output one at a time.
PRINT = threading.Lock()


def step(name, **fields):
    print(json.dumps({'at': time.strftime('%H:%M:%S'), 'step': name, **fields}), flush=True)


def run(*args, env=None, cwd=None, input=None, check=True, quiet=False):
    result = subprocess.run([str(a) for a in args], env=env, cwd=cwd, input=input, text=True,
                            stdout=subprocess.PIPE if quiet else None, stderr=subprocess.PIPE if quiet else None)
    if check and result.returncode:
        if quiet:
            sys.stderr.write((result.stderr or '')[-2000:])
        raise SystemExit(f'{" ".join(str(a) for a in args[:4])} failed with exit code {result.returncode}')
    return result


def kubectl(*args, input=None, check=True):
    return subprocess.run(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), *args], input=input, text=True,
                          capture_output=True, check=check).stdout


def apply_manifest(text, namespace=None):
    """Apply objects when kubectl diff finds a difference, and print the objects that changed.

    kubectl apply reports some objects, for example a MutatingAdmissionPolicy, as configured on each run, also when the
    server keeps the object unchanged. The diff step keeps the output accurate.
    """
    scope = ['-n', namespace] if namespace else []
    diff = subprocess.run(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), 'diff', '-f', '-', *scope], input=text, text=True,
                          capture_output=True)
    if diff.returncode == 0:
        return
    if diff.returncode != 1:
        raise SystemExit(f'kubectl diff failed: {diff.stderr.strip()[-500:]}')
    for line in kubectl('apply', '-f', '-', *scope, input=text).splitlines():
        if not line.endswith(' unchanged'):
            print(line, flush=True)


def register(zone, home=None, values=None):
    """Add a new zone to the zone state, or check that an existing zone has the given values.

    values holds the Hoover values of a new zone (config.ZONE_VALUES and extra_datasets). A new zone gets the store
    layout site unless values names local. A new zone of the layout site gets the Temporal and the Manticore of the
    site (temporal = site, manticore = site). home is the home node argument of an earlier version. It has no effect, and a new entry does not record it.
    """
    import config
    values = {k: v for k, v in (values or {}).items() if v not in (None, '', [], ())}
    try:
        state = zonestate.load()
    except zonestate.ZoneStateError:
        if zonestate.PATH.exists():
            raise
        state = {'schemaVersion': zonestate.SCHEMA, 'zones': {}}
    entry = state['zones'].get(zone)
    if entry is None:
        if values.get('stores') == 'zone':
            raise SystemExit('a new zone cannot use the store layout zone of an earlier version. Use site or local.')
        # bootstrapped turns true after the first complete openDesk install (opendesk()).
        entry = {'enabled': True, 'namespaces': [zone, f'hoover-{zone}'], 'bootstrapped': False, 'stores': 'site', **values}
        if entry['stores'] == 'site':
            entry['temporal'] = 'site'
            entry['manticore'] = 'site'
            # The openDesk objects of the zone are in the shared Garage (objectstore.py).
            entry['objectstore'] = 'garage'
        problems = config.zone_problems(zone, entry, settings.SITE)
        if problems:
            raise SystemExit('; '.join(problems))
        state['zones'][zone] = entry
        zonestate.save(state)
        step('zone-state', zone=zone, change='added')
        return
    for key, value in values.items():
        default = config.ZONE_VALUES.get(key, ('',))[0]
        if entry.get(key, default) != value:
            raise SystemExit(f'{zone} has {key} = {entry.get(key, default)}. A change of an existing zone is not supported.')


def images():
    """Check that the registry has every image of a zone. The step images of deploy-k3s up builds them.

    The Hoover image tags are HOOVER4_IMAGE_TAGS, which deploy-k3s and the operator pod set, else the tags of the
    commit HOOVER4_REVISION or HEAD of the checkout (../hoover/manifests.py image_tags()).
    """
    sys.path.insert(0, str(SOURCE / 'driver'))
    sys.path.insert(0, str(SOURCE / 'hoover'))
    import deploy
    import manifests
    revision = manifests.resolve_revision()
    try:
        deploy.registry_references(settings.SITE, deploy.zone_image_names(manifests.image_tags(revision)))
    except deploy.StepFailed as error:
        raise SystemExit(f'{error}. Run deploy-k3s up --steps images on the operator workstation for the revision '
                         f'{revision[:12]}.') from None


def cluster():
    import zones
    policy = (HERE / 'manifests/zone-pods.yaml').read_text()
    digest = hashlib.sha256(policy.encode()).hexdigest()[:16]
    rights = kubectl('auth', 'can-i', 'patch', 'mutatingadmissionpolicies.admissionregistration.k8s.io/hoover-zone-pods', check=False)
    if rights.strip() == 'yes':
        apply_manifest(policy.replace('SOURCE_HASH', digest))
    elif kubectl('get', 'mutatingadmissionpolicy', 'hoover-zone-pods', '-o',
                 'jsonpath={.metadata.annotations.hoover\\.dev/source-hash}', check=False).strip() != digest:
        raise SystemExit('the zone pod policy of the cluster is not the policy of the source. '
                         'Run platform/operator/install-runner.sh or zone.py with the admin kubeconfig.')
    apply_manifest((HERE / 'manifests/xwiki-extensions.yaml').read_text().replace('IMAGE_TAG', zones.XWIKI_EXTENSIONS_TAG))


def namespaces(zone):
    for name in (zone, f'hoover-{zone}'):
        # The label hoover.dev/zone selects the namespaces of the zone pod policy (manifests/zone-pods.yaml).
        apply_manifest(json.dumps({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': name, 'labels': {
            'hoover.dev/zone': 'true'}}}))
        # The zone runner of the operator portal has its rights in a zone namespace through this binding
        # (../platform/operator/runner-rights.yaml).
        apply_manifest(json.dumps({'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
                                   'metadata': {'name': 'zone-runner', 'namespace': name},
                                   'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': 'zone-admin'},
                                   'subjects': [{'kind': 'ServiceAccount', 'name': 'zone-runner', 'namespace': 'operator-portal'}]}))
    apply_manifest((HERE / 'manifests/zone-network.yaml').read_text().replace('ZONE', zone), zone)
    # The Keycloak bootstrap reads the Hoover and gate client secrets, which zones.py writes.
    apply_manifest((PRIVATE / 'zones' / zone / 'hoover-oidc-secret.json').read_text())


# The sub-helmfiles of openDesk (the entries of helmfile-defaults.yaml.gotmpl of the release) in waves. helmfile runs
# the entries one after another. The entries of one wave here depend only on the earlier waves, so they run at the same
# time, each in its own helmfile process. The applications depend on the services and on Nubus (the identity), and
# not on each other. check_waves() refuses a release whose entry list differs from these waves, so an openDesk upgrade
# with a new entry stops before it installs anything.
OPENDESK_WAVES = (
    ('opendesk-migrations-pre',),
    ('opendesk-services', 'services-external'),
    ('nubus',),
    ('open-xchange', 'nextcloud', 'collabora', 'cryptpad', 'jitsi', 'element', 'neoboard', 'openproject', 'xwiki', 'notes'),
    ('opendesk-openproject-bootstrap',),
    ('opendesk-migrations-post',),
)
ENTRY = re.compile(r'^\s*-\s*path:\s*"helmfile/apps/([^/"]+)/helmfile-defaults\.yaml\.gotmpl"', re.M)
RELEASE = re.compile(r'^  - name: "?([^"\n{}]+)"?\s*$', re.M)
# The wrapper of one entry: the environments of the root helmfile.yaml.gotmpl and the one entry with the values.
WRAPPER = """bases:
  - "{{ requiredEnv "PWD" }}/helmfile/bases/environments.yaml.gotmpl"
---
helmfiles:
  - path: "PATH"
    values:
      - {{ toYaml .Values | nindent 8 }}
"""


def upstream_entries(text):
    """The entry names of helmfile-defaults.yaml.gotmpl, in their order."""
    return ENTRY.findall(text)


def wave_problems(entries, waves=OPENDESK_WAVES):
    """The differences between the entries of the release and the waves, as messages."""
    listed = [e for wave in waves for e in wave]
    problems = [f'the openDesk release has the sub-helmfile {e}, which no wave of zone.py OPENDESK_WAVES names'
                for e in entries if e not in listed]
    problems += [f'zone.py OPENDESK_WAVES names {e}, which the openDesk release does not have' for e in listed if e not in entries]
    problems += [f'zone.py OPENDESK_WAVES names {e} more than once' for e in sorted({e for e in listed if listed.count(e) > 1})]
    wave_of = {e: i for i, wave in enumerate(waves) for e in wave}
    known = [e for e in entries if e in wave_of]
    for before, after in zip(known, known[1:]):
        if wave_of[after] < wave_of[before]:
            problems.append(f'the openDesk release runs {before} before {after}, and zone.py OPENDESK_WAVES runs it later')
    return problems


def check_waves():
    problems = wave_problems(upstream_entries((OPENDESK / 'helmfile-defaults.yaml.gotmpl').read_text()))
    if problems:
        raise SystemExit('; '.join(problems) + '. Update OPENDESK_WAVES for this openDesk release.')


def entry_releases(entry):
    """The release names of one entry, from its helmfile files. Release names that a template builds are left out:
    openDesk builds only the names of legacy releases, which are not installed."""
    names = []
    for path in sorted((OPENDESK / 'helmfile/apps' / entry).glob('helmfile*.gotmpl')):
        text = path.read_text()
        if '\nreleases:' not in text:
            continue
        section = re.split(r'\n[A-Za-z]', text.split('\nreleases:', 1)[1], maxsplit=1)[0]
        names += [n for n in RELEASE.findall(section) if n not in names]
    return names


def helmfile_env(zone, home=None):
    """The environment of a helmfile process. home gives the process its own Helm cache and Helm configuration, so
    processes that run at the same time do not share them. Every process reads the charts from CHART_CACHE."""
    env = dict(os.environ, PWD=str(OPENDESK), PATH=f"{TOOLS}:{os.environ['PATH']}", HELM_PLUGINS=str(TOOLS / 'plugins'),
               HELM_CONFIG_HOME=str(TOOLS / 'config'), HELM_CACHE_HOME=str(TOOLS / 'cache'), HELM_DATA_HOME=str(TOOLS / 'data'),
               HELMFILE_CACHE_HOME=str(CHART_CACHE),
               KUBECONFIG=str(settings.KUBECONFIG), MASTER_PASSWORD=(PRIVATE / 'zones' / zone / 'master-password').read_text().strip(),
               DOMAIN=settings.SUFFIX, MAIL_DOMAIN=settings.zone_domain(zone), MATRIX_DOMAIN=settings.zone_domain(zone))
    if home:
        env.update(HELM_CACHE_HOME=str(home / 'helm-cache'), HELM_CONFIG_HOME=str(home / 'helm-config'),
                   XDG_CACHE_HOME=str(home / 'cache'))
    CHART_CACHE.mkdir(parents=True, exist_ok=True)
    return env


def helmfile_args(zone, command, *extra):
    # helmfile resolves its relative includes from PWD, so PWD must name the source directory.
    args = ['helmfile', command, '-e', 'dev', '-n', zone, '--state-values-file', PRIVATE / 'zones' / zone / 'values.yaml',
            '--post-renderer', HERE / 'postrender.py', '--post-renderer-args', zone, *extra]
    if command == 'apply':
        # The diff renders with cluster access, so a chart that keeps a generated password through lookup, such as
        # SeaweedFS, renders the stored value and shows no difference.
        args += ['--suppress-diff', '--diff-args', '--dry-run=server']
    return args


def helmfile(zone, command, *extra, check=True):
    return run(*helmfile_args(zone, command, *extra), env=helmfile_env(zone), cwd=OPENDESK, check=check,
               quiet=command == 'template')


def helm_releases(zone):
    """{release: status} of the Helm releases of the zone namespace, in every status."""
    out = run('helm', 'list', '-n', zone, '-a', '-o', 'json', env=helmfile_env(zone), quiet=True).stdout
    return {r['name']: r['status'] for r in json.loads(out or '[]')}


def helm_revisions(zone):
    """{release: {revision, status, chart}} of the Helm releases of the zone namespace, in every status."""
    out = run('helm', 'list', '-n', zone, '-a', '-o', 'json', env=helmfile_env(zone), quiet=True).stdout
    return {r['name']: {'revision': str(r['revision']), 'status': r['status'], 'chart': r['chart']}
            for r in json.loads(out or '[]')}


def sha(value):
    """The SHA-256 of bytes, or of the sorted JSON form of a value."""
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()


def tree_digest(root):
    """The SHA-256 of the relative path and the content of every file below root."""
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob('*') if p.is_file() and '__pycache__' not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def operator_effective(zone):
    """The effective operator settings that the post-renderer reads: cluster (cpu_policy.py) and the zone
    (postrender.py operator_values()), at HOOVER4_SETTINGS_REVISION, else the newest saved revision.

    The settings of the apply mode schedule (the backup policies) are left out. Only the backup scheduler reads them,
    so a change of a backup policy changes no openDesk object and no request. The placement step
    (../placement.py opendesk_digest()) reads the same settings."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('operator_settings', SOURCE / 'platform/operator/settings.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = settings.SITE.operator_state() if settings.SITE else None
    overrides = {}
    if folder and (folder / 'desired.json').exists():
        revision = os.environ.get('HOOVER4_SETTINGS_REVISION')
        overrides = module.State(folder).overrides(int(revision) if revision else None)
    out = {}
    for scope in ('cluster', f'zone:{zone}'):
        values = module.effective(scope, overrides.get(scope, {}))
        out[scope] = {k: v for k, v in values.items() if getattr(module.REGISTRY.get(k), 'apply', '') != 'schedule'}
    return out


def opendesk_inputs(zone):
    """{input: SHA-256} of every input of the openDesk waves and of the application state steps of a zone.

    The inputs are the files of INPUT_SOURCES and the openDesk release. The zone folder gives the values, the master
    password, the client secrets and the value files. zones/ gives the shared value files and the zone user passwords.
    ai.json, the zone state entry, the effective operator settings and the site settings follow. The last inputs are the
    environment of helmfile, the Kubernetes version and the storage tiers. The values and the release name the images.
    The value bootstrapped of the zone state entry is left out, because the first run changes it.
    """
    out = {}
    for name in INPUT_SOURCES:
        path = SOURCE / name
        out[f'source/{name}'] = tree_digest(path) if path.is_dir() else sha(path.read_bytes())
    out['opendesk-release'] = tree_digest(OPENDESK)
    folder = PRIVATE / 'zones'
    for path in sorted(folder.glob('*.yaml')) + [settings.ZONE_USER_PASSWORDS, PRIVATE / 'ai.json']:
        if path.is_file():
            out[f'state/{path.relative_to(PRIVATE).as_posix()}'] = sha(path.read_bytes())
    import objectstore
    for path in sorted((folder / zone).iterdir()):
        if path.is_file() and path.name not in (RECORD_NAME, objectstore.RECORD) and not path.name.startswith('.'):
            out[f'state/zones/{zone}/{path.name}'] = sha(path.read_bytes())
    entry = dict(zonestate.load()['zones'][zone])
    entry.pop('bootstrapped', None)
    out['zone-state'] = sha(entry)
    out['operator-settings'] = sha(operator_effective(zone))
    out['site-settings'] = sha(settings.HOST)
    env = helmfile_env(zone)
    out['environment'] = sha({k: env[k] for k in sorted(env) if k in INPUT_ENV or k.startswith(INPUT_ENV_PREFIXES)})
    version = json.loads(kubectl('version', '-o', 'json')).get('serverVersion', {}).get('gitVersion')
    out['cluster'] = sha({'version': version, 'tiers': zonestate.site_tiers(settings.KUBECONFIG)})
    return out


def read_record(zone):
    path = PRIVATE / 'zones' / zone / RECORD_NAME
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def opendesk_changes(zone, inputs, releases):
    """The reasons to run the openDesk waves and the application state steps. An empty list means that nothing changed
    since the last complete run: the same digest of the inputs, the same Helm releases with the same revisions, and
    every release deployed. releases is helm_revisions() of the zone."""
    if first_bootstrap(zone):
        return ['the first install of the zone has not completed']
    record = read_record(zone)
    if not record:
        return ['no record of a complete run']
    reasons = []
    if record.get('digest') != sha(inputs):
        before = record.get('inputs') or {}
        reasons += [f'{name} changed' for name in sorted(set(inputs) | set(before)) if inputs.get(name) != before.get(name)]
        reasons = reasons or ['the input digest changed']
    reasons += [f'release {name} is {r["status"]}' for name, r in sorted(releases.items()) if r['status'] != 'deployed']
    recorded = record.get('releases') or {}
    reasons += [f'release {name} changed by revision or chart' for name in sorted(set(releases) | set(recorded))
                if releases.get(name) != recorded.get(name)]
    return reasons


def write_record(zone, inputs):
    """Record a complete run of the waves and the application state steps with its inputs and Helm releases."""
    path = PRIVATE / 'zones' / zone / RECORD_NAME
    record = {'digest': sha(inputs), 'inputs': inputs, 'releases': helm_revisions(zone),
              'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    path.touch(mode=0o600)
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + '\n')
    clusterstate.checkpoint(PRIVATE)


def entry_command(entry, releases):
    """sync for an entry with no installed release, or with a release that is not deployed, else apply.

    apply renders and diffs each release on the server first. A new release has nothing to diff, and helmfile apply
    skips a failed release without a difference, so both use sync.
    """
    present = [n for n in entry_releases(entry) if n in releases]
    if not present or any(releases[n] != 'deployed' for n in present):
        return 'sync'
    return 'apply'


def run_entry(zone, entry, command):
    """Run one entry in its own helmfile process. Return (exit code, output). The output is printed in one piece."""
    import shutil
    import tempfile
    home = Path(tempfile.mkdtemp(prefix=f'helmfile-{entry}-'))
    try:
        if (TOOLS / 'config').exists():
            shutil.copytree(TOOLS / 'config', home / 'helm-config')
        wrapper = home / 'helmfile.yaml.gotmpl'
        wrapper.write_text(WRAPPER.replace('PATH', str(OPENDESK / 'helmfile/apps' / entry / 'helmfile-defaults.yaml.gotmpl')))
        started = time.monotonic()
        result = subprocess.run([str(a) for a in helmfile_args(zone, command, '-f', wrapper)], env=helmfile_env(zone, home),
                                cwd=OPENDESK, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        with PRINT:
            print(f'--- helmfile {command} {entry} ({int(time.monotonic() - started)} s, exit {result.returncode})', flush=True)
            print(result.stdout, flush=True)
        return result.returncode, result.stdout
    finally:
        shutil.rmtree(home, ignore_errors=True)


def template_entries(zone):
    """The helmfile template output of every openDesk entry of OPENDESK_WAVES, each in its own process, all at the same
    time. The output passes the post-renderer. The deploy-time placement (../placement.py) reads the requests from it.
    Nothing is applied."""
    import shutil
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    check_waves()

    def one(entry):
        home = Path(tempfile.mkdtemp(prefix=f'helmfile-{entry}-'))
        try:
            if (TOOLS / 'config').exists():
                shutil.copytree(TOOLS / 'config', home / 'helm-config')
            wrapper = home / 'helmfile.yaml.gotmpl'
            wrapper.write_text(WRAPPER.replace('PATH', str(OPENDESK / 'helmfile/apps' / entry / 'helmfile-defaults.yaml.gotmpl')))
            result = subprocess.run([str(a) for a in helmfile_args(zone, 'template', '-f', wrapper, '--quiet')],
                                    env=helmfile_env(zone, home), cwd=OPENDESK, text=True, capture_output=True)
            if result.returncode:
                raise SystemExit(f'helmfile template of the openDesk part {entry} of {zone} failed: {result.stderr.strip()[-600:]}')
            return result.stdout
        finally:
            shutil.rmtree(home, ignore_errors=True)
    entries = [e for wave in OPENDESK_WAVES for e in wave]
    with ThreadPoolExecutor(max_workers=len(entries)) as pool:
        return list(pool.map(one, entries))


def failure_cause(output):
    """The last error lines of a helmfile output, for the log of a retry."""
    lines = [line.strip() for line in output.splitlines() if 'Error' in line or 'error' in line or 'timed out' in line]
    return ' | '.join(lines[-3:])[-600:]


def stale_pods(controller, pods):
    """Select old pods that the StatefulSet controller cannot replace automatically."""
    spec, status = controller['spec'], controller.get('status', {})
    if not spec.get('replicas', 1) or status.get('observedGeneration', 0) < controller['metadata']['generation']:
        return []
    revision = status.get('updateRevision')
    if not revision:
        return []
    found = []
    for pod in pods:
        meta = pod['metadata']
        if meta.get('deletionTimestamp') or not any(
                owner.get('uid') == controller['metadata']['uid'] and owner.get('controller')
                for owner in meta.get('ownerReferences', [])):
            continue
        if meta.get('labels', {}).get('controller-revision-hash') == revision:
            continue
        partition = spec.get('updateStrategy', {}).get('rollingUpdate', {}).get('partition', 0)
        if int(meta['name'].rsplit('-', 1)[1]) < partition:
            continue
        ready = any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod.get('status', {}).get('conditions', []))
        if spec.get('updateStrategy', {}).get('type') == 'OnDelete' or not ready:
            found.append(meta['name'])
    return found


def refresh_statefulsets(zone):
    """Replace outdated store pods and blocked StatefulSet pods after a template change."""
    if not zonestate.enabled(zone):
        return
    controllers = json.loads(kubectl('-n', zone, 'get', 'statefulsets', '-o', 'json'))['items']
    pods = json.loads(kubectl('-n', zone, 'get', 'pods', '-o', 'json'))['items']
    for controller in controllers:
        for name in stale_pods(controller, pods):
            kubectl('-n', zone, 'delete', 'pod', name, '--ignore-not-found', '--wait=false')
            step('replace-stale-pod', zone=zone, pod=name)


def login_flow(zone, stop, errors):
    """Run zone-login-no-mfa.sh as soon as the opendesk realm exists, and nextcloud_config(), while helmfile runs.

    The openDesk Keycloak bootstrap Job needs the 2fa-browser flow, which a zone without two-factor login lacks. The Job
    retries, so a flow that exists before its last retry lets the first helmfile pass succeed. The OpenProject bootstrap
    Job calls Nextcloud, so Nextcloud gets its configuration before that Job runs out of retries.
    """
    configured = restarted = False
    try:
        while not stop.wait(20):
            refresh_statefulsets(zone)
            if not configured and subprocess.run(['bash', str(HERE / 'zone-login-no-mfa.sh'), zone], capture_output=True).returncode == 0:
                step('login-flow', zone=zone, result='set during the first helmfile pass')
                configured = True
            if not restarted:
                try:
                    restarted = nextcloud_config(zone, wait=False)
                except subprocess.CalledProcessError as error:
                    # The check runs again in 20 s, and once more after helmfile.
                    step('nextcloud-check', zone=zone, result=f'failed: {(error.stderr or "")[-200:]}')
    except Exception as error:
        errors.append(error)


def nextcloud_domain(zone):
    return settings.zone_host(zone, 'files')


def nextcloud_config(zone, wait=True):
    """Restart Nextcloud when it runs without the configuration of the management Job. Return True after a restart.

    The Nextcloud pod loads config.php from the table fs_config_store of its database when it starts. The management Job
    writes the complete configuration there. A pod that starts before the Job keeps the minimal configuration of the
    install, and answers every request for <zone>-files.<suffix> with a trusted domain error. The OpenProject bootstrap
    then fails, because it calls Nextcloud, and its failed setup leaves the Nextcloud user OpenProject behind. occ cannot
    change the configuration, because it is read-only. A new pod loads the complete configuration.
    """
    domain = nextcloud_domain(zone)
    if not kubectl('-n', zone, 'get', 'deployment', 'opendesk-nextcloud-aio', '--ignore-not-found', '-o', 'name').strip():
        return False
    stored = subprocess.run(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), '-n', zone, 'exec', 'postgresql-0', '-c',
                             'postgresql', '--', 'psql', '-U', 'postgres', '-d', 'nextcloud', '-At', '-c',
                             "SELECT value FROM fs_config_store WHERE name = 'config_php'"],
                            capture_output=True, text=True).stdout
    if domain not in stored:
        return False
    domains = subprocess.run(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), '-n', zone, 'exec',
                              'deployment/opendesk-nextcloud-aio', '--',
                              'php', '/var/www/html/occ', 'config:system:get', 'trusted_domains'],
                             capture_output=True, text=True)
    if domains.returncode or domain in domains.stdout:
        return False
    kubectl('-n', zone, 'rollout', 'restart', 'deployment/opendesk-nextcloud-aio')
    if wait:
        kubectl('-n', zone, 'rollout', 'status', 'deployment/opendesk-nextcloud-aio', '--timeout=600s')
    step('nextcloud-restart', zone=zone, reason='the configuration of the management Job was missing')
    return True


def first_bootstrap(zone):
    """True for a zone whose first openDesk install has not completed: its zone state entry has bootstrapped = false.

    zone.py writes bootstrapped = false for a new zone and true after its first complete install. An entry without the
    key belongs to a zone of an earlier version, which has completed its install.
    """
    return zonestate.load()['zones'].get(zone, {}).get('bootstrapped') is False


def mark_bootstrapped(zone):
    state = zonestate.load()
    entry = state['zones'].get(zone)
    if entry is not None and entry.get('bootstrapped') is False:
        entry['bootstrapped'] = True
        zonestate.save(state)
        clusterstate.checkpoint(PRIVATE)
        step('zone-state', zone=zone, change='bootstrapped')


def openproject_reset(zone):
    """Remove the Nextcloud user and group OpenProject that a failed OpenProject bootstrap left behind.

    The caller runs it only while Helm lists the release opendesk-openproject-bootstrap as failed. It changes only a
    zone whose first install has not completed (first_bootstrap()), so the integration of an existing zone stays.
    The integration setup of the bootstrap creates the user and returns its client credentials. A second setup finds the
    user and returns no credentials, so every retry fails. The order follows the troubleshooting guide of the Nextcloud
    app integration_openproject: disable the app, delete the user and the group, enable the app.
    """
    if not first_bootstrap(zone):
        step('openproject-reset', zone=zone, result='skipped, the zone completed its first install')
        return
    occ = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG), '-n', zone, 'exec', 'deployment/opendesk-nextcloud-aio',
           '--', 'php', '/var/www/html/occ']
    if subprocess.run(occ + ['user:info', 'OpenProject'], capture_output=True).returncode:
        return
    for args in (['app:disable', 'integration_openproject'], ['user:delete', 'OpenProject'],
                 ['group:delete', 'OpenProject'], ['app:enable', 'integration_openproject']):
        subprocess.run(occ + args, capture_output=True)
    step('openproject-reset', zone=zone, reason='a failed bootstrap left the Nextcloud user OpenProject')


def repair(zone, entry, releases):
    """The repair of a known cause before an entry runs again. releases is {release: status} after the failure.

    nubus: the Keycloak bootstrap Job needs the 2fa-browser flow, which zone-login-no-mfa.sh creates once Keycloak
    has the openDesk configuration. nextcloud: Nextcloud restarts when it runs without the configuration of its management Job
    (nextcloud_config()). opendesk-openproject-bootstrap: the same Nextcloud check, and the removal of the Nextcloud user
    OpenProject that a failed bootstrap left behind (openproject_reset()).
    """
    if entry == 'nubus' and kubectl('-n', zone, 'get', 'secret', 'keycloak-admin-password', '--ignore-not-found', '-o', 'name').strip():
        run('bash', HERE / 'zone-login-no-mfa.sh', zone, check=False)
    if entry in ('nextcloud', 'opendesk-openproject-bootstrap'):
        nextcloud_config(zone)
    if entry == 'opendesk-openproject-bootstrap' and releases.get('opendesk-openproject-bootstrap') == 'failed':
        openproject_reset(zone)


def install_entry(zone, entry):
    """Run one entry, and once more after its repair when it fails. The log names the cause of each retry."""
    for attempt in (1, 2):
        command = entry_command(entry, helm_releases(zone))
        step('helmfile', zone=zone, entry=entry, command=command, attempt=attempt)
        code, output = run_entry(zone, entry, command)
        if code == 0:
            return
        releases = helm_releases(zone)
        failed = [n for n in entry_releases(entry) if releases.get(n, 'deployed') != 'deployed']
        if attempt == 2:
            raise SystemExit(f'helmfile {command} of the openDesk part {entry} failed twice: {failure_cause(output)}')
        step('helmfile-retry', zone=zone, entry=entry, releases=failed, cause=failure_cause(output))
        repair(zone, entry, releases)


def opendesk(zone):
    """Install or update openDesk wave by wave (OPENDESK_WAVES). The entries of a wave run at the same time.

    A failed entry runs again on its own after its repair (install_entry()), and a failed wave stops the install.
    The helper thread login_flow() sets the login flow and checks Nextcloud while the waves run.
    """
    check_waves()
    first = first_bootstrap(zone)
    stop = threading.Event()
    errors = []
    refresh_statefulsets(zone)
    helper = threading.Thread(target=login_flow, args=(zone, stop, errors), daemon=True)
    helper.start()
    try:
        for wave in OPENDESK_WAVES:
            started = time.monotonic()
            failures = []

            def one(entry):
                try:
                    install_entry(zone, entry)
                except (SystemExit, Exception) as error:  # noqa: BLE001 - the wave reports the failure of each entry
                    failures.append(f'{entry}: {error}')
            threads = [threading.Thread(target=one, args=(entry,)) for entry in wave]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            if failures:
                raise SystemExit('; '.join(failures))
            step('opendesk-wave', zone=zone, entries=list(wave), seconds=int(time.monotonic() - started))
        nextcloud_config(zone)
    finally:
        stop.set()
        helper.join()
    if errors:
        raise errors[0]
    mark_bootstrapped(zone)
    if first:
        # The portal server reads the portal data once at its start. On a new zone it can start before the portal
        # consumer wrote the data, and then it answers every page with an error until it restarts. A later apply
        # finds the data, so it does not restart the portal server.
        kubectl('-n', zone, 'rollout', 'restart', 'deployment/ums-portal-server')
        kubectl('-n', zone, 'rollout', 'status', 'deployment/ums-portal-server', '--timeout=300s')
        step('portal-server-restart', zone=zone, reason='first install')


def hoover(zone):
    import config
    installation = config.zone_hoover(zone, zonestate.load()['zones'][zone])
    if installation.stores == 'local':
        # The local store layout runs the Compose stores in the Hoover namespace (../hoover/manifests.py).
        run(sys.executable, SOURCE / 'hoover' / 'setup.py', zone, 'local-secrets')
        run(sys.executable, SOURCE / 'hoover' / 'manifests.py', installation.name, 'apply')
        return
    if installation.stores == 'zone':
        raise SystemExit(f'{zone} keeps its ClickHouse and Garage in its zone namespace, from an earlier version. Its data '
                         'does not move to the shared stores of the site. Delete the zone and create it again.')
    if installation.temporal == 'zone':
        raise SystemExit(f'{zone} runs its own Temporal on the PostgreSQL of the zone, from an earlier version. Its workflow '
                         'history does not move to the Temporal of the site. Delete the zone and create it again.')
    if installation.manticore == 'zone':
        raise SystemExit(f'{zone} runs its own Manticore daemons in the zone namespace, from an earlier version. Its search '
                         'tables do not move to the Manticore of the site. Delete the zone and create it again.')
    # ClickHouse, Garage, Manticore and Temporal are shared by the site (../hoover/stores/shared.py). Their claims grow
    # with the zone count.
    run(sys.executable, STORES / 'shared.py', 'ready')
    run(sys.executable, STORES / 'shared.py', 'grow')
    run(sys.executable, STORES / 'creds.py', zone)
    run(sys.executable, SOURCE / 'hoover' / 'setup.py', zone)
    run(sys.executable, SOURCE / 'hoover' / 'manifests.py', zone, 'apply')
    pools()


def pools():
    """Create the processing pools of the site when it has none (../hoover/pools.py ensure), and remove them when no
    zone of the store layout site remains. A running pool stays as it is, so a zone create or delete changes no pool
    pod. In deploy-k3s up the step stores applies the pools (HOOVER4_POOLS_STEP), so the zone step leaves them to it."""
    if os.environ.get('HOOVER4_POOLS_STEP') != '1':
        run(sys.executable, SOURCE / 'hoover' / 'pools.py', 'ensure')


def objects(zone):
    """Create the openDesk buckets and key of a zone of the store layout site in Garage, and apply the Ingress of its
    object storage host. A zone of an earlier version moves its objects from SeaweedFS first (objectstore.py move()),
    gets objectstore = garage and new values. Return True after a move.

    The zone runner cannot keep the SeaweedFS volume of a move (Retain). With its kubeconfig the zone stays on
    SeaweedFS, and the next deploy-k3s up moves it."""
    import objectstore
    entry = zonestate.load()['zones'][zone]
    if entry.get('stores') != 'site':
        return False
    key = json.loads((PRIVATE / 'zones' / 'secrets.json').read_text())[zone]['objectstore_key']
    changed = objectstore.ensure(zone, key)
    if changed:
        step('objectstore', zone=zone, changed=changed)
    if objectstore.on_garage(entry):
        apply_manifest(json.dumps(objectstore.ingress(zone)), objectstore.STORES_NS)
        return False
    if objectstore.seaweedfs_installed(zone):
        if not objectstore.can_keep_volumes():
            step('objectstore', zone=zone, result='the zone stays on SeaweedFS until deploy-k3s up moves its objects')
            return False
        objectstore.move(zone, key)
    state = zonestate.load()
    state['zones'][zone]['objectstore'] = 'garage'
    zonestate.save(state)
    clusterstate.checkpoint(PRIVATE)
    step('zone-state', zone=zone, change='objectstore garage')
    run(sys.executable, HERE / 'zones.py', quiet=True)
    apply_manifest(json.dumps(objectstore.ingress(zone)), objectstore.STORES_NS)
    return True


def apply(zone, home=None, values=None, full=False):
    register(zone, home, values)
    run(sys.executable, HERE / 'zones.py', quiet=True)
    # The zone secrets exist before the first object that uses them, so the cluster copy gets them now.
    clusterstate.checkpoint(PRIVATE)
    step('values', zone=zone)
    if not zonestate.enabled(zone):
        rendered = helmfile(zone, 'template')
        destination = PRIVATE / 'render' / f'{zone}-disabled.yaml'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.touch(mode=0o600)
        destination.chmod(0o600)
        destination.write_text(rendered.stdout)
        step('render-only', zone=zone, reason='the zone is disabled')
        return
    images()
    step('images', zone=zone)
    cluster()
    namespaces(zone)
    step('namespaces', zone=zone)
    moved = objects(zone)
    inputs = opendesk_inputs(zone)
    reasons = ['--full'] if full else opendesk_changes(zone, inputs, helm_revisions(zone))
    if reasons:
        step('opendesk-check', zone=zone, result='run', reasons=reasons[:12])
        opendesk(zone)
        if moved:
            import objectstore
            for entry in objectstore.SECOND_PASS:
                install_entry(zone, entry)
        step('opendesk', zone=zone)
        run('bash', HERE / 'zone-login-no-mfa.sh', zone, quiet=True)
        run(sys.executable, HERE / 'zone-users.py', zone)
        run(sys.executable, HERE / 'zone-patches.py', zone)
    else:
        step('opendesk-check', zone=zone, result='unchanged since the last complete run')
        run(sys.executable, HERE / 'zone-patches.py', zone, '--discovery')
    apply_manifest((HERE / 'manifests/zone-keycloak-admin.yaml').read_text().replace('KEYCLOAK_HOST', settings.zone_host(zone, 'id')), zone)
    import gate
    apply_manifest(json.dumps(gate.objects(zone)), zone)
    if reasons:
        # The inputs again, because the steps can write a zone file, for example the password of a new test.user.
        write_record(zone, opendesk_inputs(zone))
    finish_move(zone)
    step('zone-state-of-apps', zone=zone)
    hoover(zone)
    step('hoover', zone=zone)
    run(sys.executable, SOURCE / 'tools' / 'write-password-table.py')
    step('done', zone=zone)


def finish_move(zone):
    """Restart the applications that hold the object store key after the waves of a move (objectstore.py finish())."""
    import objectstore
    if objectstore.on_garage(zonestate.load()['zones'][zone]) and objectstore.read_record(zone):
        objectstore.finish(zone, json.loads((PRIVATE / 'zones' / 'secrets.json').read_text())[zone]['objectstore_key'])


def delete(zone):
    state = zonestate.load()
    if zone not in state['zones']:
        raise SystemExit(f'the zone state has no zone {zone}')
    if state['zones'][zone].get('stores') == 'site':
        # The tenant of the zone in the shared stores goes first. A failed removal stops the delete here, so the zone
        # state keeps the zone and a new zone cannot take its id while its objects remain.
        run(sys.executable, STORES / 'shared.py', 'remove', zone)
        step('shared-stores', zone=zone, change='tenant removed')
    # The namespaces go at the same time. TopoLVM removes the logical volume of each claim when its namespace goes.
    namespaces = state['zones'][zone]['namespaces']
    kubectl('delete', 'namespace', *namespaces, '--ignore-not-found', '--wait=false')
    kubectl('wait', '--for=delete', *[f'namespace/{n}' for n in namespaces], '--timeout=900s', check=False)
    for namespace in namespaces:
        if kubectl('get', 'namespace', namespace, '--ignore-not-found', '-o', 'name').strip():
            raise SystemExit(f'the namespace {namespace} still exists 900 s after its delete')
        step('namespace-deleted', zone=zone, namespace=namespace)
    # The SeaweedFS volume that a move kept goes with the zone. The zone runner cannot read or delete a volume.
    import objectstore
    if objectstore.can_keep_volumes():
        objectstore.drop_kept(zone)
    elif objectstore.read_record(zone):
        step('objectstore', zone=zone, result=f'a SeaweedFS volume with the label {objectstore.LABEL}={zone} can stay. '
             'Delete it with the admin kubeconfig.')
    del state['zones'][zone]
    zonestate.save(state)
    # The last zone of the store layout site takes the processing pools with it.
    pools()
    secrets_file = PRIVATE / 'zones' / 'secrets.json'
    if secrets_file.exists():
        data = json.loads(secrets_file.read_text())
        if data.pop(zone, None) is not None:
            secrets_file.write_text(json.dumps(data, indent=1))
    run('rm', '-rf', PRIVATE / 'zones' / zone)
    clusterstate.checkpoint(PRIVATE)
    step('zone-state', zone=zone, change='removed')
    run(sys.executable, SOURCE / 'tools' / 'write-password-table.py')


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('apply', 'delete'))
    parser.add_argument('zone')
    parser.add_argument('--home', help='accepted for an earlier version, without effect')
    parser.add_argument('--stores')
    parser.add_argument('--dataset', action='append', default=[], help='name:node:/path of a read-only dataset folder')
    parser.add_argument('--full', action='store_true', help='run the openDesk waves also when no input changed')
    args = parser.parse_args()
    if not zonestate_name(args.zone):
        raise SystemExit(__doc__)
    settings.use_kubeconfig()
    with operation(f'zone-{args.command}-{args.zone}'):
        if args.command == 'delete':
            delete(args.zone)
            return
        apply(args.zone, args.home, {'stores': args.stores, 'extra_datasets': args.dataset}, full=args.full)


@contextlib.contextmanager
def operation(operation_id):
    """Run inside the site operation of the caller, else hold the site lock and use the cluster copy of the state.

    deploy-k3s and the zone runner hold the lock and give HOOVER4_SITE_OPERATION to this process. A command of the
    workstation takes the lock itself. When the lock is the Lease of the cluster, the command first reads the cluster
    copy into the state folder and writes its changes back at the end (../clusterstate.py).
    """
    import oplock
    if os.environ.get(oplock.ENV):
        yield
        return
    lock = oplock.site_lock(PRIVATE / 'operator')
    try:
        lock.acquire('zone', operation_id)
    except oplock.Busy as error:
        raise SystemExit(str(error)) from None
    try:
        if isinstance(lock, oplock.LeaseLock):
            os.environ[clusterstate.ENV] = '1'
            clusterstate.pull(PRIVATE)
        try:
            yield
        finally:
            clusterstate.checkpoint(PRIVATE)
    finally:
        lock.release()


def zonestate_name(name):
    import zones
    return zones.ZONE_NAME.fullmatch(name) is not None


if __name__ == '__main__':
    main()
