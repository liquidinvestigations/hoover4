#!/usr/bin/env python3
"""Create, upgrade or delete one zone: openDesk, its stores and its Hoover. This is the one installer command of a zone.

Usage:
  zone.py apply <zone> [--home <node>] [--stores zone|local] [--temporal-backend postgresql|cassandra]
                [--dataset name:node:/path ...]
                                          create the zone, or bring it to the source state. --home is required for a
                                          new zone. The other options set the values of a new zone (zonestate.py),
                                          and each option must match for an existing zone.
  zone.py delete <zone>                   delete the zone namespaces with their volumes, and the zone entry.
The zone state of the state folder holds the zones. The site file names no zone.
Apply reads the current state before each step. Verify unchanged output with ../tools/zone-snapshot.py after an upgrade.
An apply of a disabled zone saves a private render without applying objects or running hooks.
The steps of apply, in order:
  1. The zone state (zonestate.py) gets the zone with its home node and the values of its Hoover installation.
     zones.py writes the openDesk values.
  2. The step checks that the registry has the images of the revision. deploy-k3s up builds them (step images).
  3. The cluster gets the zone pod policy (manifests/zone-pods.yaml) and the XWiki extension repository. The zone
     runner cannot change the pod policy, so with its kubeconfig the step only checks that the cluster has the policy
     of the source.
  4. The zone namespaces get their labels, the RoleBinding of the zone runner, the network policy and the Hoover and
     gate client Secrets.
  5. helmfile applies openDesk with postrender.py as the Helm post-renderer. A new zone has no 2fa-browser flow, and the
     openDesk Keycloak bootstrap Job needs it. zone-login-no-mfa.sh creates the flow as soon as the realm exists, while
     helmfile runs. Nextcloud restarts once when its pod started before the management Job stored the complete
     configuration. When the first pass still fails, helmfile runs once more. Before it, a zone whose first install
     has not completed loses the Nextcloud user OpenProject that a failed OpenProject bootstrap left behind. The zone
     state records the completion (bootstrapped), so an existing zone keeps its OpenProject integration.
     Each release that Helm lists as failed is synced again, because helmfile apply skips a release without a diff.
     The installer replaces outdated OnDelete pods and outdated pods that block a StatefulSet rollout.
  6. zone-login-no-mfa.sh, zone-users.py and zone-patches.py set the login flow, the users and the application state.
     gate.py adds the sign-in service of the zone gate.
  7. The Hoover stores, their users and buckets, and the Hoover deployment follow (../hoover/). A zone with
     stores = local in the zone state gets its Secrets from setup.py local-secrets and its objects from manifests.py.
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
import subprocess
import sys
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


def register(zone, home, values=None):
    """Add a new zone to the zone state, or check that an existing zone has the given home node and values.

    values holds the Hoover values of a new zone (config.ZONE_VALUES and extra_datasets). A value that is not given
    keeps its default.
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
        if not home:
            raise SystemExit(f'{zone} is a new zone, so it needs --home <node>')
        # bootstrapped turns true after the first complete openDesk install (opendesk()).
        entry = {'enabled': True, 'home': home, 'namespaces': [zone, f'hoover-{zone}'], 'bootstrapped': False, **values}
        problems = config.zone_problems(zone, entry, settings.SITE)
        if problems:
            raise SystemExit('; '.join(problems))
        kubectl('get', 'node', home)
        state['zones'][zone] = entry
        zonestate.save(state)
        step('zone-state', zone=zone, home=home, change='added')
        return zonestate.home(zone)
    if home and entry.get('home') != home:
        raise SystemExit(f'{zone} has the home node {entry.get("home")}. A move to another node is not supported.')
    for key, value in values.items():
        default = config.ZONE_VALUES.get(key, ('',))[0]
        if entry.get(key, default) != value:
            raise SystemExit(f'{zone} has {key} = {entry.get(key, default)}. A change of an existing zone is not supported.')
    return zonestate.home(zone)


def images():
    """Check that the registry has every image of a zone for the revision. The step images of deploy-k3s up builds them.

    The revision is HOOVER4_REVISION, which deploy-k3s and the operator pod set, else HEAD of the checkout.
    """
    sys.path.insert(0, str(SOURCE / 'driver'))
    import deploy
    revision = os.environ.get('HOOVER4_REVISION') or deploy.resolve_revision(deploy.REPO, 'HEAD')
    try:
        deploy.registry_references(settings.SITE, deploy.revision_image_names(revision))
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


def namespaces(zone, home):
    for name in (zone, f'hoover-{zone}'):
        apply_manifest(json.dumps({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': name, 'labels': {
            'hoover.dev/zone': 'true', 'hoover.dev/home-node': home}}}))
        # The zone runner of the operator portal has its rights in a zone namespace through this binding
        # (../platform/operator/runner-rights.yaml).
        apply_manifest(json.dumps({'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
                                   'metadata': {'name': 'zone-runner', 'namespace': name},
                                   'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': 'zone-admin'},
                                   'subjects': [{'kind': 'ServiceAccount', 'name': 'zone-runner', 'namespace': 'operator-portal'}]}))
    apply_manifest((HERE / 'manifests/zone-network.yaml').read_text().replace('ZONE', zone), zone)
    # The Keycloak bootstrap reads the Hoover and gate client secrets, which zones.py writes.
    apply_manifest((PRIVATE / 'zones' / zone / 'hoover-oidc-secret.json').read_text())


def helmfile_env(zone):
    return dict(os.environ, PWD=str(OPENDESK), PATH=f"{TOOLS}:{os.environ['PATH']}", HELM_PLUGINS=str(TOOLS / 'plugins'),
                HELM_CONFIG_HOME=str(TOOLS / 'config'), HELM_CACHE_HOME=str(TOOLS / 'cache'), HELM_DATA_HOME=str(TOOLS / 'data'),
                KUBECONFIG=str(settings.KUBECONFIG), MASTER_PASSWORD=(PRIVATE / 'zones' / zone / 'master-password').read_text().strip(),
                DOMAIN=f'{zone}.{settings.SUFFIX}')


def helmfile(zone, command, *extra, check=True):
    # helmfile resolves its relative includes from PWD, so PWD must name the source directory.
    args = ['helmfile', command, '-e', 'dev', '-n', zone, '--state-values-file', PRIVATE / 'zones' / zone / 'values.yaml',
            '--post-renderer', HERE / 'postrender.py', '--post-renderer-args', zone, *extra]
    if command == 'apply':
        # The diff renders with cluster access, so a chart that keeps a generated password through lookup, such as
        # SeaweedFS, renders the stored value and shows no difference.
        args += ['--suppress-diff', '--diff-args', '--dry-run=server']
    return run(*args, env=helmfile_env(zone), cwd=OPENDESK, check=check, quiet=command == 'template')


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
    return f'files.{zone}.{settings.SUFFIX}'


def nextcloud_config(zone, wait=True):
    """Restart Nextcloud when it runs without the configuration of the management Job. Return True after a restart.

    The Nextcloud pod loads config.php from the table fs_config_store of its database when it starts. The management Job
    writes the complete configuration there. A pod that starts before the Job keeps the minimal configuration of the
    install, and answers every request for files.<zone>.<suffix> with a trusted domain error. The OpenProject bootstrap
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


def failed_releases(zone):
    return run('helm', 'list', '-n', zone, '--failed', '-q', env=helmfile_env(zone), quiet=True).stdout.split()


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


def opendesk(zone):
    import threading
    stop = threading.Event()
    errors = []
    refresh_statefulsets(zone)
    helper = threading.Thread(target=login_flow, args=(zone, stop, errors), daemon=True)
    helper.start()
    try:
        first = helmfile(zone, 'apply', check=False)
        if first.returncode:
            if not kubectl('-n', zone, 'get', 'secret', 'keycloak-admin-password', '--ignore-not-found', '-o', 'name').strip():
                raise SystemExit('helmfile failed before Keycloak exists')
            step('helmfile', zone=zone, result='first pass failed, the login flow follows')
            run('bash', HERE / 'zone-login-no-mfa.sh', zone)
            nextcloud_config(zone)
            if 'opendesk-openproject-bootstrap' in failed_releases(zone):
                openproject_reset(zone)
            helmfile(zone, 'apply')
        nextcloud_config(zone)
        for release in failed_releases(zone):
            step('helmfile-sync', zone=zone, release=release)
            if release == 'opendesk-openproject-bootstrap':
                openproject_reset(zone)
            helmfile(zone, 'sync', '-l', f'name={release}')
    finally:
        stop.set()
        helper.join()
    if errors:
        raise errors[0]
    mark_bootstrapped(zone)
    # The portal server reads the portal data once at its start. On a new zone it can start before the portal
    # consumer wrote the data, and then it answers every page with an error until it restarts.
    kubectl('-n', zone, 'rollout', 'restart', 'deployment/ums-portal-server')
    kubectl('-n', zone, 'rollout', 'status', 'deployment/ums-portal-server', '--timeout=300s')


def hoover(zone):
    import config
    installation = config.zone_hoover(zone, zonestate.load()['zones'][zone])
    if installation.stores == 'local':
        # The local store layout runs the Compose stores in the Hoover namespace (../hoover/manifests.py).
        run(sys.executable, SOURCE / 'hoover' / 'setup.py', zone, 'local-secrets')
        run(sys.executable, SOURCE / 'hoover' / 'manifests.py', installation.name, 'apply')
        return
    env = dict(os.environ, KATA_NS=zone)
    run(sys.executable, STORES / 'creds.py', zone)
    for store in ('clickhouse', 'manticore', 'manticore-vectors', 'garage'):
        run(sys.executable, STORES / 'hoover.py', 'apply', store, zone)
    deadline = time.monotonic() + 600
    while True:
        refresh_statefulsets(zone)
        ready = True
        for store in ('clickhouse', 'manticore', 'manticore-vectors', 'garage'):
            controller = json.loads(kubectl('-n', zone, 'get', 'statefulset', f'{store}-kata', '-o', 'json'))
            status = controller.get('status', {})
            pods = json.loads(kubectl('-n', zone, 'get', 'pods', '-l', f'hoover.dev/store={store}', '-o', 'json'))['items']
            ready &= (status.get('observedGeneration', 0) >= controller['metadata']['generation']
                      and len(pods) == 1 and not pods[0]['metadata'].get('deletionTimestamp')
                      and pods[0]['metadata']['labels'].get('controller-revision-hash') == status.get('updateRevision')
                      and any(c['type'] == 'Ready' and c['status'] == 'True' for c in pods[0].get('status', {}).get('conditions', [])))
        if ready:
            break
        if time.monotonic() >= deadline:
            raise SystemExit('the Hoover stores did not become ready with their current templates')
        time.sleep(3)
    run(sys.executable, STORES / 'garage-setup.py', env=env)
    run(sys.executable, SOURCE / 'hoover' / 'setup.py', zone)
    run(sys.executable, SOURCE / 'hoover' / 'manifests.py', zone, 'apply')


def apply(zone, home, values=None):
    home = register(zone, home, values)
    run(sys.executable, HERE / 'zones.py', quiet=True)
    # The zone secrets exist before the first object that uses them, so the cluster copy gets them now.
    clusterstate.checkpoint(PRIVATE)
    step('values', zone=zone, home=home)
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
    namespaces(zone, home)
    step('namespaces', zone=zone)
    opendesk(zone)
    step('opendesk', zone=zone)
    run('bash', HERE / 'zone-login-no-mfa.sh', zone, quiet=True)
    run(sys.executable, HERE / 'zone-users.py', zone)
    run(sys.executable, HERE / 'zone-patches.py', zone)
    apply_manifest((HERE / 'manifests/zone-keycloak-admin.yaml').read_text().replace('ZONE', zone).replace('SUFFIX', settings.SUFFIX), zone)
    import gate
    apply_manifest(json.dumps(gate.objects(zone)), zone)
    step('zone-state-of-apps', zone=zone)
    hoover(zone)
    step('hoover', zone=zone)
    run(sys.executable, SOURCE / 'tools' / 'write-password-table.py')
    step('done', zone=zone)


def delete(zone):
    state = zonestate.load()
    if zone not in state['zones']:
        raise SystemExit(f'the zone state has no zone {zone}')
    for namespace in state['zones'][zone]['namespaces']:
        # TopoLVM removes the logical volume of each claim when the namespace goes.
        kubectl('delete', 'namespace', namespace, '--ignore-not-found', '--wait=true', '--timeout=900s')
        step('namespace-deleted', zone=zone, namespace=namespace)
    del state['zones'][zone]
    zonestate.save(state)
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
    parser.add_argument('--home')
    parser.add_argument('--stores')
    parser.add_argument('--temporal-backend')
    parser.add_argument('--dataset', action='append', default=[], help='name:node:/path of a read-only dataset folder')
    args = parser.parse_args()
    if not zonestate_name(args.zone):
        raise SystemExit(__doc__)
    settings.use_kubeconfig()
    with operation(f'zone-{args.command}-{args.zone}'):
        if args.command == 'delete':
            delete(args.zone)
            return
        apply(args.zone, args.home, {'stores': args.stores, 'temporal_backend': args.temporal_backend,
                                     'extra_datasets': args.dataset})


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
