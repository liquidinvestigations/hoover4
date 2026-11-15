"""The deployment driver of ../deploy-k3s. Standard library only. It runs in the operator image (../images/operator).

The driver reads the site file (../config.py) and runs the Ansible playbooks of ../ansible for the hosts, the cluster
scripts of ../cluster/ and ../platform/, and the zone installer of ../zones/. A step of up starts when the steps that
it needs are done (PREREQUISITES), so independent steps run at the same time, and the output lines of each step start
with its name in brackets. records.py keeps the state of each run in the operator state of the site.

Host steps. Each one is one Ansible run on all target nodes in parallel (class Ansible):
  hosts:prepare  playbooks/hoover4-hosts.yml: the facts of each node, its packages, kernel modules, sysctl,
                 NetworkManager, SELinux, the local node of a single-node site, the backup folder, the optional public
                 firewall and the WireGuard peers. The facts go to facts/<node>.json of the state folder. A node
                 without a stored speed is measured once before k3s starts on it (speed/<node>.json, measure_speed()).
  hosts:k3s      playbooks/hoover4-k3s.yml: gVisor, Kata Containers, the GPU runtime, the tokens, the k3s configuration
                 and the registry mirror, then k3s on the server and on the agents. The server play converts a SQLite
                 datastore to etcd after a verified copy, verifies etcd and writes the admin kubeconfig into the state
                 folder with the node address of the server.
  hosts:verify   reads each target through the admin kubeconfig: Ready, the k3s version, the flannel interface, and
                 cluster-init and the etcd role of the server. A missing kubeconfig fails with its path.
The nodes connect with SSH as the user of the workstation. become uses sudo without a password, or the password that
--ask-become-pass reads once. down and up --start run playbooks/hoover4-service.yml on one node at a time.
A failed step ends the run after the steps that run at the same time finish. An interrupt waits for the running steps
to end, and their state stays running, so a resume runs them again. render and check change no host and no cluster.

Pinned inputs. The record of an up or a down keeps the commit of HEAD of the checkout, `git status --porcelain` of the
checkout, the SHA-256 of the site file, the settings revision of the operator state and the identity of the cluster
(the UID of the namespace kube-system). A resume refuses a changed site file, another commit or another cluster. The
commands of the steps get HOOVER4_REVISION and HOOVER4_SETTINGS_REVISION, so every render, also a nested one, uses the
pinned values. A zone step records the scopes of its zone and its Hoover installation as applied with the pinned
settings revision after their workloads are ready. A finished complete up records the revision for every scope.
The zone state (zone-state.json, ../zones/zonestate.py) names the zones. up applies each zone of it again. zone.py
and the operator portal create and delete zones.

Cluster copy of the state. The cluster holds the authoritative zone state, zone secrets and operator state
(../clusterstate.py). The command reads the cluster copy into the state folder after it takes the site lock, and before
render and check. Each finished or failed step writes the changes of the state folder back. The state folder keeps
the files that the workstation needs before a cluster exists (the tokens, the kubeconfig, the facts, the records and
the root certificate of the internal CA) and the export copy of the cluster state.
"""
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
REPO = SOURCE.parent
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import records as records_module  # noqa: E402

ARTIFACTS = json.loads((HERE / 'artifacts.json').read_text())
STOP_ORDER = ['stop:ingress', 'stop:applications', 'stop:temporal', 'stop:stores']
START_ORDER = ['start:stores', 'start:temporal', 'start:applications', 'start:ingress']
# tier() puts each Deployment and StatefulSet of a zone into a shutdown tier by its name. A name without a store word
# and without a Temporal word is an application. The ingress tier holds the ingress controller and the zone gates.
# Keycloak counts as a store, because the openDesk LDAP server reads its keys at start.
STORE_WORDS = ('clickhouse', 'manticore', 'garage', 'cassandra', 'elasticsearch', 'opensearch', 'zookeeper', 'postgres',
               'redis', 'memcached', 'seaweedfs', 'minio', 'mariadb', 'nats', 'ldap', 'keycloak')
TEMPORAL_WORDS = ('temporal',)
# The namespace of the shared Hoover stores of the site (../hoover/stores/shared.py).
SHARED_STORES = 'hoover-stores'


class StepFailed(RuntimeError):
    """A step failed. The message tells the operator what to do."""


class StepWaiting(RuntimeError):
    """A step needs an operator action. A waiting step blocks the steps that depend on it."""


# ----------------------------------------------------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------------------------------------------------

class Shell:
    """Runs commands, prints each command, and appends the output to the log of the deployment.

    Steps can run at the same time (execute()). Each line of a command of a step then starts with the step name in
    brackets, so the lines of the steps stay apart in the output and in the log.
    """
    step = threading.local()
    _lock = threading.Lock()

    def __init__(self, log=None, env=None):
        self.log = Path(log) if log else None
        self.env = dict(os.environ, **(env or {}))

    def _label(self, text):
        name = getattr(Shell.step, 'name', None)
        return f'[{name}] {text}' if name else text

    def _write(self, text):
        if self.log:
            with Shell._lock:
                self.log.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log, 'a') as f:
                    f.write(self._label(text))

    def run(self, argv, sudo=False, cwd=None, env=None, check=True, capture=False, input=None):
        argv = [str(a) for a in argv]
        if sudo:
            argv = ['sudo', '-n', *argv]
        line = '$ ' + ' '.join(shlex.quote(a) for a in argv)
        print(self._label(line), flush=True)
        self._write(line + '\n')
        proc = subprocess.Popen(argv, cwd=cwd, env=dict(self.env, **(env or {})), text=True,
                                stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if input is not None:
            proc.stdin.write(input)
            proc.stdin.close()
        lines = []
        for out in proc.stdout:
            lines.append(out)
            self._write(out)
            if not capture:
                print(self._label('  ' + out), end='', flush=True)
        code = proc.wait()
        text = ''.join(lines)
        if check and code:
            tail = text.strip().splitlines()[-3:] if text.strip() else []
            raise StepFailed(f'{" ".join(argv[:4])} exited with code {code}' + (': ' + ' | '.join(tail) if tail else ''))
        return code, text


def read(argv, cwd=None, env=None, timeout=60):
    """Run a read-only command and return (code, output)."""
    try:
        r = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, f'{argv[0]} is not installed'
    except subprocess.TimeoutExpired:
        return 124, f'{argv[0]} did not answer in {timeout} s'
    return r.returncode, (r.stdout + r.stderr).strip()


# ----------------------------------------------------------------------------------------------------------------------
# Context
# ----------------------------------------------------------------------------------------------------------------------

class Context:
    def __init__(self, site_path, site, private=None, repo=REPO):
        self.site_path = Path(site_path).resolve()
        self.site = site
        self.repo = Path(repo)
        self.private = Path(private) if private else config.state_folder(self.site_path)
        self.state = self.private / 'operator'
        self.records = records_module.Records(self.state / 'deploy')
        self.kubeconfig = Path(os.environ.get('KUBECONFIG') or self.private / 'kubeconfig')
        self.revision = None
        self.settings_revision = None
        self.record = None
        self.shell = Shell()
        self.become_password_file = ''
        # Steps that run at the same time hold it while they write the cluster copy or the operator state.
        self.state_lock = threading.RLock()

    def ask_become_pass(self):
        """Ask once for the sudo password of the nodes and keep it in a private file of this process for Ansible."""
        import getpass
        import tempfile
        password = getpass.getpass('sudo password of the nodes: ')
        fd, path = tempfile.mkstemp(prefix='hoover4-become-')
        with os.fdopen(fd, 'w') as f:
            f.write(password + '\n')
        import atexit
        atexit.register(lambda: os.path.exists(path) and os.unlink(path))
        self.become_password_file = path

    def env(self):
        # HOOVER4_CLUSTER_STATE makes the zone installer write the zone state and the zone secrets into the cluster copy
        # as soon as they change (../clusterstate.py).
        env = {'KUBECONFIG': str(self.kubeconfig), 'HOOVER4_SITE': str(self.site_path), 'HELM': str(self.private / 'bin/helm'),
               'PATH': f"{self.private / 'bin'}:{os.environ.get('PATH', '')}", 'HOOVER4_CLUSTER_STATE': '1'}
        if self.revision:
            env['HOOVER4_REVISION'] = self.revision
        if self.settings_revision is not None:
            env['HOOVER4_SETTINGS_REVISION'] = str(self.settings_revision)
        return env

    def hoovers(self):
        """{zone: Hoover} of the zone state of the state folder. A site without a zone state has no zone."""
        path = self.private / 'zone-state.json'
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except ValueError as error:
            raise StepFailed(f'the zone state {path} is unreadable: {error}') from None
        return config.hoovers(self.site, data)

    def operator_state(self):
        """The operator settings State of the site, or None before the first save."""
        if not (self.state / 'desired.json').exists():
            return None
        return operator_settings_module().State(self.state)

    def run(self, argv, **kw):
        kw['env'] = dict(self.env(), **(kw.get('env') or {}))
        return self.shell.run(argv, **kw)

    def kubectl(self, *args, check=True):
        return self.run(['kubectl', '--kubeconfig', self.kubeconfig, *args], capture=True, check=check)[1]


def sync_state(ctx, direction):
    """Read (pull) or write (push) the cluster copy of the zone state and the operator state (../clusterstate.py).

    The cluster holds the authoritative copy. The state folder keeps an export copy. Before the cluster answers, for
    example before the k3s step of a first up, the state folder is the only copy, and the first push copies it into the
    cluster. Return the changed files, or None when the cluster does not answer.
    """
    import clusterstate
    import oplock
    if not oplock.cluster_answers(ctx.kubeconfig):
        return None
    store = clusterstate.Kubectl(ctx.kubeconfig)
    try:
        if direction == 'push':
            store.ensure_namespace()
        return getattr(clusterstate, direction)(ctx.private, store=store)
    except (clusterstate.Conflict, clusterstate.Unavailable, subprocess.CalledProcessError) as error:
        raise StepFailed(f'the {direction} of the cluster copy of the state failed: {error}') from None


def operator_settings_module():
    import importlib.util
    if 'operator_settings' not in sys.modules:
        spec = importlib.util.spec_from_file_location('operator_settings', SOURCE / 'platform/operator/settings.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules['operator_settings'] = module
        spec.loader.exec_module(module)
    return sys.modules['operator_settings']


def site_fingerprint(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cluster_identity(ctx):
    """The UID of the namespace kube-system, or an empty text before the cluster answers."""
    if not ctx.kubeconfig.exists():
        return ''
    # Only standard output counts: the kubectl of a k3s host writes configuration warnings with a time to stderr.
    try:
        r = subprocess.run(['kubectl', '--kubeconfig', str(ctx.kubeconfig), 'get', 'namespace', 'kube-system', '-o',
                            'jsonpath={.metadata.uid}'], capture_output=True, text=True, timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ''
    return r.stdout.strip() if r.returncode == 0 else ''


def pinned_inputs(ctx):
    """The inputs that a record pins at its start."""
    state = ctx.operator_state()
    return {'site_fingerprint': site_fingerprint(ctx.site_path), 'site_file': str(ctx.site_path),
            'settings_revision': state.revision() if state else 0, 'cluster_identity': cluster_identity(ctx)}


def verify_inputs(ctx, record):
    """Refuse a resume whose site file or cluster changed. Record the cluster identity once it exists."""
    inputs = record.get('inputs')
    if not inputs:
        return
    problems = []
    if site_fingerprint(ctx.site_path) != inputs['site_fingerprint']:
        problems.append(f'the site file {ctx.site_path} changed after the start of the record')
    current = cluster_identity(ctx)
    if inputs.get('cluster_identity') and current and current != inputs['cluster_identity']:
        problems.append(f'the kubeconfig names another cluster ({current}, not {inputs["cluster_identity"]})')
    if problems:
        raise StepFailed('the record cannot resume: ' + '; '.join(problems) + '. Start a new run.')
    if current and not inputs.get('cluster_identity'):
        inputs['cluster_identity'] = current
        ctx.records.save(record)


def resolve_revision(repo, ref):
    code, out = read(['git', '-C', repo, 'rev-parse', '--verify', f'{ref}^{{commit}}'])
    if code:
        raise StepFailed(f'{ref} is not a commit of {repo}: {out}')
    return out.strip()


def dirty_files(repo):
    """The lines of `git status --porcelain` of the checkout. The driver never resets the changes.

    --no-optional-locks keeps git from writing the index, because the operator image mounts the checkout read-only.
    """
    r = subprocess.run(['git', '--no-optional-locks', '-C', str(repo), 'status', '--porcelain'], capture_output=True,
                       text=True)
    return r.stdout.splitlines() if r.returncode == 0 else [f'git status failed: {r.stderr.strip()}']


# ----------------------------------------------------------------------------------------------------------------------
# Host steps
# ----------------------------------------------------------------------------------------------------------------------

ANSIBLE = SOURCE / 'ansible'
K3S_VERSION = re.search(r'(?m)^hoover4_k3s_version: (\S+)$',
                        (ANSIBLE / 'roles/hoover4_k3s/defaults/main.yml').read_text()).group(1)
# The image of the short check pods of the driver. The digest is the amd64 image.
POD_IMAGE = 'docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'


class Ansible:
    """Runs the playbooks of ../ansible on target nodes, with the site file as the inventory.

    The variables that the driver derives from the site file go to the plays as extra variables
    (config.ansible_variables). New host keys go to known_hosts of the state folder, because ~/.ssh is read-only in the
    operator image. A run with a sudo password reads it from a private file of the container, which ask_become_pass()
    of the context writes.
    """

    def __init__(self, ctx):
        self.ctx = ctx

    def env(self):
        known = self.ctx.private / 'known_hosts'
        return {'ANSIBLE_CONFIG': str(ANSIBLE / 'hoover4.cfg'), 'ANSIBLE_NOCOLOR': '1',
                'ANSIBLE_SSH_ARGS': '-o ControlMaster=auto -o ControlPersist=60s -o ConnectTimeout=15 '
                                    '-o StrictHostKeyChecking=accept-new '
                                    f'-o "UserKnownHostsFile={known} ~/.ssh/known_hosts"'}

    def argv(self, playbook, targets, extra=None, tags=()):
        argv = ['ansible-playbook', '-i', self.ctx.site_path, '--limit', ','.join(targets), ANSIBLE / 'playbooks' / playbook,
                '-e', json.dumps(config.ansible_variables(self.ctx.site, self.ctx.private))]
        if self.ctx.become_password_file:
            argv += ['--become-password-file', self.ctx.become_password_file]
        if extra:
            argv += ['-e', json.dumps(extra)]
        if tags:
            argv += ['--tags', ','.join(tags)]
        return argv

    def run(self, playbook, targets, extra=None, tags=()):
        """Run a playbook. Raise StepFailed with the recap when a task failed or a node was unreachable."""
        (self.ctx.private / 'facts').mkdir(parents=True, exist_ok=True)
        if 'speed' in tags or not tags:
            # The play of the role hoover4_speed writes speed/<node>.json.
            (self.ctx.private / 'speed').mkdir(parents=True, exist_ok=True)
        # The facts play of this version writes no cpu_speed, so the value of an earlier version moves to speed/ first.
        config.adopt_facts_speed(self.ctx.private)
        code, out = self.ctx.run(self.argv(playbook, targets, extra, tags), env=self.env(), check=False)
        if code:
            failed = [name.split(' -> ')[0] for name in re.findall(r'(?m)^\s*fatal: \[([^\]]+)\]', out)]
            recap = [line.strip() for line in out.splitlines() if re.search(r'(unreachable|failed)=[1-9]', line)]
            raise StepFailed(f'the play {playbook} failed' + (f' on {", ".join(sorted(set(failed)))}' if failed else '')
                             + (': ' + ' | '.join(recap) if recap else f' with exit code {code}')
                             + f'. The log of the record holds the output of each task.')
        return out


def step_hosts(ctx):
    """The host play of the targets: facts, packages, settings and the WireGuard peers (playbooks/hoover4-hosts.yml)."""
    Ansible(ctx).run('hoover4-hosts.yml', ctx.record['targets'])
    return {'facts': str(ctx.private / 'facts')}


def step_k3s(ctx):
    """The k3s play of the targets: the server, then the agents (playbooks/hoover4-k3s.yml)."""
    if ctx.site.control_plane in ctx.record['targets'] and 'etcd_before' not in ctx.record:
        # verify compares the etcd role after the step with this value, to find a conversion from SQLite.
        ctx.record['etcd_before'] = (node_label(ctx, ctx.site.control_plane, 'node-role.kubernetes.io/etcd')
                                     if node_ready(ctx, ctx.site.control_plane) else 'absent')
        ctx.records.save(ctx.record)
    Ansible(ctx).run('hoover4-k3s.yml', ctx.record['targets'])
    return {'kubeconfig': str(ctx.kubeconfig)}


def node_problems(ctx, name, k3s_args=None):
    """The differences of a node from the site file, as the cluster shows them through the admin kubeconfig."""
    node = ctx.site.nodes[name]
    problems = []
    if not node_ready(ctx, name):
        return ['the node is not Ready']
    version = ctx.kubectl('get', 'node', name, '-o', 'jsonpath={.status.nodeInfo.kubeletVersion}', check=False).strip()
    if version != K3S_VERSION:
        problems.append(f'k3s is {version or "unknown"}, not {K3S_VERSION}')
    args = node_args(ctx, name) if k3s_args is None else k3s_args
    interface = arg_value(args, '--flannel-iface')
    expected = expected_interface(ctx, node)
    if not expected:
        problems.append(f'the facts of the node name no interface of its address {config.node_address(ctx.site, node)}. '
                        f'Run deploy-k3s check --target {name}')
    elif interface != expected:
        problems.append(f'flannel-iface is {interface!r}, not {expected!r}')
    if name == ctx.site.control_plane:
        if arg_value(args, '--cluster-init') != 'true':
            problems.append('k3s runs without cluster-init')
        if node_label(ctx, name, 'node-role.kubernetes.io/etcd') != 'true':
            problems.append('the node has no etcd role')
    return problems


def step_verify(ctx, attempts=24, pause=5):
    """Verify each target through the admin kubeconfig: Ready, the k3s version, the flannel interface and etcd."""
    if not ctx.kubeconfig.exists():
        raise StepFailed(f'the admin kubeconfig {ctx.kubeconfig} is missing. The k3s play of the control plane '
                         f'{ctx.site.control_plane} writes it. Run deploy-k3s up --target {ctx.site.control_plane} '
                         '--steps hosts:k3s.')
    pending = list(ctx.record['targets'])
    found = {}
    for attempt in range(attempts):
        found = {name: node_problems(ctx, name) for name in pending}
        pending = [name for name, problems in found.items() if problems]
        if not pending:
            break
        if attempt < attempts - 1:
            time.sleep(pause)
    if pending:
        raise StepFailed('; '.join(f'node {name}: {", ".join(found[name])}' for name in pending) + '.')
    out = {'nodes': list(ctx.record['targets'])}
    if (ctx.site.control_plane in ctx.record['targets'] and ctx.record.get('etcd_before') == ''
            and node_label(ctx, ctx.site.control_plane, 'node-role.kubernetes.io/etcd') == 'true'):
        out['restarted'] = restart_watchers(ctx)
    return out


def service_step(action, name):
    """Start or stop k3s on one node with playbooks/hoover4-service.yml."""
    def run(ctx):
        Ansible(ctx).run('hoover4-service.yml', [name], extra={'hoover4_action': action})
        if action == 'start' and name == ctx.site.control_plane:
            wait_api(ctx)
        return {}
    return run


HOST_STEPS = {'hosts:prepare': step_hosts, 'hosts:k3s': step_k3s, 'hosts:verify': step_verify}


# The namespaces of the controllers that hold a watch of the API. After the conversion of the server from SQLite to
# etcd, these controllers saw no object that was created later: CoreDNS resolved no new Service, the ingress
# controller answered 404 for new hosts, and cert-manager, TopoLVM and the monitoring operators missed new objects. A
# restart of their pods made them read the API again. The likely cause is that the watches resume from revisions of
# the earlier datastore, which etcd does not have. No source confirms the cause.
WATCH_NAMESPACES = ('kube-system', 'ingress', 'cert-manager', 'topolvm-system', 'monitoring', 'operator-portal')


def restart_watchers(ctx):
    """Restart the Deployments and DaemonSets of WATCH_NAMESPACES and wait for them. Return the restarted namespaces."""
    restarted = []
    for ns in WATCH_NAMESPACES:
        if not ctx.kubectl('get', 'namespace', ns, '--ignore-not-found', '-o', 'name', check=False).strip():
            continue
        for kind in ('deployment', 'daemonset'):
            if ctx.kubectl('-n', ns, 'get', kind, '-o', 'name', check=False).strip():
                ctx.kubectl('-n', ns, 'rollout', 'restart', kind)
        restarted.append(ns)
    for ns in restarted:
        for name in ctx.kubectl('-n', ns, 'get', 'deployment,daemonset', '-o', 'name', check=False).split():
            ctx.kubectl('-n', ns, 'rollout', 'status', name, '--timeout=300s')
    return restarted


def node_ready(ctx, name):
    if not ctx.kubeconfig.exists():
        return False
    code, out = read(['kubectl', '--kubeconfig', ctx.kubeconfig, 'get', 'node', name, '--no-headers'])
    return code == 0 and ' Ready ' in f' {out} '


def node_label(ctx, name, label):
    if not ctx.kubeconfig.exists():
        return ''
    escaped = label.replace('.', '\\.')
    code, out = read(['kubectl', '--kubeconfig', ctx.kubeconfig, 'get', 'node', name, '-o',
                      f'jsonpath={{.metadata.labels.{escaped}}}'])
    return out.strip() if code == 0 else ''


def node_args(ctx, name):
    """The k3s arguments that the node recorded in its annotation k3s.io/node-args, or an empty list."""
    if not ctx.kubeconfig.exists():
        return []
    try:
        r = subprocess.run(['kubectl', '--kubeconfig', str(ctx.kubeconfig), 'get', 'node', name, '-o',
                            r'jsonpath={.metadata.annotations.k3s\.io/node-args}'], capture_output=True, text=True,
                           timeout=60)
        args = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return []
    return [str(a) for a in args] if isinstance(args, list) else []


def arg_value(args, name):
    return next((args[i + 1] for i, a in enumerate(args[:-1]) if a == name), '')


def node_facts(ctx, name):
    """The facts of a node in facts/<node>.json of the state folder, which the facts play writes, or an empty dict."""
    try:
        return json.loads((ctx.private / 'facts' / f'{name}.json').read_text())
    except (OSError, ValueError):
        return {}


def expected_interface(ctx, node):
    """The flannel interface of node: the interface of its network, else the interface that holds its LAN address in
    the facts of the node, else empty when the facts are missing."""
    return config.node_interface(ctx.site, node) or (node_facts(ctx, node.name).get('addresses') or {}).get(
        config.node_address(ctx.site, node), '')


def private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        f.write(text)


# ----------------------------------------------------------------------------------------------------------------------
# Cluster steps
# ----------------------------------------------------------------------------------------------------------------------

def tool_paths(ctx):
    return [ctx.private / item['install'][0].rstrip('/') for item in ARTIFACTS['tools']]


def step_tools(ctx):
    """Download the pinned operator tools once, verify their digests and install them into the state folder."""
    import hashlib
    import shutil
    import tarfile
    arch = node_architecture(ctx, ctx.site.control_plane)
    installed = {}
    for item in ARTIFACTS['tools']:
        targets = [ctx.private / t.rstrip('/') for t in item['install']]
        stamp = ctx.private / 'downloads' / f'.{item["name"]}-{item["version"]}-{arch}'
        if stamp.exists() and all(t.exists() for t in targets):
            installed[item['name']] = item['version']
            continue
        digest = item['sha256'].get(arch)
        if not digest:
            raise StepFailed(f'{item["name"]} {item["version"]} has no pinned digest for {arch}.')
        url = item['url'].format(arch=arch)
        archive = ctx.private / 'downloads' / url.rsplit('/', 1)[1]
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            print(f'download {url}', flush=True)
            with urllib.request.urlopen(url, timeout=120) as response, open(str(archive) + '.part', 'wb') as f:
                shutil.copyfileobj(response, f)
            os.replace(str(archive) + '.part', archive)
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != digest:
            raise StepFailed(f'{archive.name} has the digest {actual}, not the pinned {digest}.')
        member = item['member'].format(arch=arch)
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not member:
                shutil.copy(archive, target)
                target.chmod(0o755)
                continue
            with tarfile.open(archive) as tar:
                if member.endswith('/'):
                    shutil.rmtree(target, ignore_errors=True)
                    target.mkdir(parents=True)
                    for entry in tar.getmembers():
                        if entry.name.startswith(member) and entry.name != member:
                            entry.name = entry.name[len(member):]
                            tar.extract(entry, target, filter='data')
                else:
                    target.write_bytes(tar.extractfile(member).read())
                    target.chmod(0o755)
        stamp.write_text(digest + '\n')
        installed[item['name']] = item['version']
    ctx.run(['bash', SOURCE / 'platform/frontend/build-caddy.sh'])
    return {'tools': installed}


def step_script(*argv):
    def run(ctx):
        ctx.run([SOURCE / a[1:] if isinstance(a, str) and a.startswith('@') else a for a in argv])
        return {}
    return run


def image_names(ctx):
    return revision_image_names(ctx.revision)


def revision_image_names(revision):
    """The images of the zones for a revision: the Hoover images and the images of ../images/."""
    sys.path.insert(0, str(SOURCE / 'hoover'))
    sys.path.insert(0, str(SOURCE / 'zones'))
    import compose
    import zones
    tag = revision[:12]
    return ([f'hoover/hoover-{n}:{tag}' for n in compose.IMAGES] +
            [f'hoover/nextcloud-ai:{zones.NEXTCLOUD_IMAGE_TAG}', f'hoover/xwiki-extensions:{zones.XWIKI_EXTENSIONS_TAG}',
             'hoover/blockmount:8'])


MANIFEST_TYPES = ('application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,'
                  'application/vnd.docker.distribution.manifest.v2+json,application/vnd.docker.distribution.manifest.list.v2+json')


def registry_get(endpoint, path, accept=MANIFEST_TYPES):
    request = urllib.request.Request(f'http://{endpoint}{path}', headers={'Accept': accept})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.headers.get('Docker-Content-Digest', ''), json.loads(response.read())


def image_architectures(endpoint, repo, manifest):
    """The architectures of an image manifest or index."""
    if 'manifests' in manifest:
        return sorted({m.get('platform', {}).get('architecture', '') for m in manifest['manifests']} - {'', 'unknown'})
    _, blob = registry_get(endpoint, f'/v2/{repo}/blobs/{manifest["config"]["digest"]}', accept='*/*')
    return [blob.get('architecture', '')]


def image_references(ctx, names=None, architecture=None):
    """{reference: {digest, architectures}} of images in the registry. architecture is the one that each must have."""
    return registry_references(ctx.site, names if names is not None else image_names(ctx), architecture)


def registry_references(site, names, architecture=None):
    """image_references() for a Site. The zone runner checks the images of a zone with it (../zones/zone.py)."""
    endpoint = config.legacy_settings(site)['registry_endpoint']
    out = {}
    for name in names:
        repo, image_tag = name.rsplit(':', 1)
        try:
            digest, manifest = registry_get(endpoint, f'/v2/{repo}/manifests/{image_tag}')
            architectures = image_architectures(endpoint, repo, manifest)
        except (OSError, ValueError, KeyError) as error:
            raise StepFailed(f'the registry {endpoint} has no image {name}: {error}')
        if architecture and architecture not in architectures:
            raise StepFailed(f'the image {name} has the architectures {architectures}, not {architecture}.')
        out[f'registry.hoover.internal/{name}'] = {'digest': digest, 'architectures': architectures}
    return out


def step_images(ctx):
    """Build and push the images of the revision and the image of the operator pod. The registry step runs before, so
    the push has a target. The zone runner only checks that the registry has these images.

    The three zone images and build-hoover.py build at the same time, and build-hoover.py builds its images in parallel
    up to the CPU count of this host.
    """
    from concurrent.futures import ThreadPoolExecutor
    sys.path.insert(0, str(SOURCE / 'zones'))
    import zones
    builds = [['bash', SOURCE / 'images/build-image.sh', SOURCE / 'images' / directory, image]
              for directory, image in (('blockmount', 'hoover/blockmount:8'),
                                       ('nextcloud-ai', f'hoover/nextcloud-ai:{zones.NEXTCLOUD_IMAGE_TAG}'),
                                       ('xwiki-extensions', f'hoover/xwiki-extensions:{zones.XWIKI_EXTENSIONS_TAG}'))]
    builds.append([sys.executable, SOURCE / 'images/build-hoover.py', '--revision', ctx.revision])
    with ThreadPoolExecutor(max_workers=len(builds)) as pool:
        for future in [pool.submit(ctx.run, argv) for argv in builds]:
            future.result()
    arch = node_architecture(ctx, ctx.site.control_plane)
    references = image_references(ctx, architecture=arch)
    with ctx.records.guard:
        ctx.record.setdefault('images', {}).update(references)
    operator = step_operator_image(ctx)
    return {'images': len(ctx.record['images']), 'architecture': arch, 'operator_image': operator}


# The image of the operator pod (../platform/operator/pod.py): the operator image of ../deploy-k3s with the parts of
# the checkout that the portal and the zone runner run, and the operator tools of the state folder.
OPERATOR_IMAGE = 'hoover/operator'
# The Hoover render reads the Compose files, the storage identities and the files of its ConfigMaps (manifests.py
# config_maps()).
OPERATOR_TREE = ('k3s', 'deploy.py', 'hoover4.ini.release', 'main_services/processing/tasks/storage_identity.json',
                 'main_services/processing/tasks/temporal_readiness.py',
                 'main_services/processing/tasks/signal_calibration.json', 'website/backend/src/temporal_ready.rs',
                 'main_services/ops/docker', 'ai_services/compose', 'ai_services/docker-compose.yaml')
OPERATOR_EXCLUDED = ('k3s/private/', 'k3s/tests/')


def operator_tree(repo=REPO):
    """The files of the checkout that the operator image holds: tracked and new files, with their local changes."""
    out = subprocess.run(['git', '--no-optional-locks', '-C', str(repo), 'ls-files', '-co', '--exclude-standard', '-z',
                          '--', *OPERATOR_TREE], capture_output=True, check=True).stdout.decode().split('\0')
    return sorted(f for f in out if f and not f.startswith(OPERATOR_EXCLUDED) and '__pycache__' not in f
                  and (Path(repo) / f).is_file())


def operator_image_tag(ctx, base, files):
    """The tag of the operator image: a digest of the base image, the files and the tool versions."""
    import hashlib
    digest = hashlib.sha256(base.encode() + b'\0')
    for name in files:
        digest.update(name.encode() + b'\0' + (ctx.repo / name).read_bytes() + b'\0')
    for item in ARTIFACTS['tools']:
        digest.update(f'{item["name"]} {item["version"]}\n'.encode())
    return digest.hexdigest()[:16]


def build_operator_image(ctx, files, name, base, arch):
    """Copy the files and the operator tools into a build folder of the state folder, then build and push the image."""
    import shutil
    context = ctx.private / 'build-operator.tmp'
    shutil.rmtree(context, ignore_errors=True)
    try:
        for item in files:
            target = context / 'tree' / item
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ctx.repo / item, target)
        for item in ARTIFACTS['tools']:
            for path in item['install']:
                source = ctx.private / path.rstrip('/')
                target = context / 'tools' / path.rstrip('/')
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target, symlinks=True)
                else:
                    shutil.copy2(source, target)
        shutil.copy2(SOURCE / 'images/operator-pod/Containerfile', context / 'Containerfile')
        ctx.run(['bash', SOURCE / 'images/build-image.sh', context, name],
                env={'BUILD_ARGS': f'BASE={base}', 'PLATFORM': f'linux/{arch}'})
    finally:
        shutil.rmtree(context, ignore_errors=True)


def step_operator_image(ctx):
    """Build the image of the operator pod and push it to the registry. Return its reference in the registry.

    The base image is the operator image that runs this command (HOOVER4_OPERATOR_BASE of ../deploy-k3s), so the image
    has the architecture of the workstation, which must be the architecture of the control plane.
    """
    import platform
    base = os.environ.get('HOOVER4_OPERATOR_BASE', '')
    if not base:
        raise StepFailed('HOOVER4_OPERATOR_BASE names no operator image. Run the command through k3s/deploy-k3s.')
    local = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine(), platform.machine())
    arch = node_architecture(ctx, ctx.site.control_plane)
    if arch != local:
        raise StepFailed(f'the control plane {ctx.site.control_plane} is {arch}, and the operator image of this '
                         f'workstation is {local}. Run deploy-k3s from a workstation of the architecture {arch}.')
    files = operator_tree(ctx.repo)
    name = f'{OPERATOR_IMAGE}:{operator_image_tag(ctx, base, files)}'
    try:
        references = registry_references(ctx.site, [name], architecture=arch)
    except StepFailed:
        build_operator_image(ctx, files, name, base, arch)
        references = registry_references(ctx.site, [name], architecture=arch)
    with ctx.records.guard:
        ctx.record.setdefault('images', {}).update(references)
        ctx.record['operator_image'] = f'registry.hoover.internal/{name}'
        ctx.records.save(ctx.record)
    return ctx.record['operator_image']


def gpu_image_names(ctx):
    sys.path.insert(0, str(SOURCE / 'hoover'))
    import compose
    return [f'hoover/hoover-{n}:{ctx.revision[:12]}' for n in compose.GPU_IMAGES]


def node_architecture(ctx, name):
    """The architecture of a node from its facts (config.architecture())."""
    try:
        return config.architecture(ctx.site, name, node_facts(ctx, name))
    except config.SiteError as error:
        raise StepFailed(str(error)) from None


def gpu_architecture(ctx):
    architectures = {node_architecture(ctx, n) for n in ctx.site.gpu_pool.get('nodes', ())}
    if len(architectures) != 1:
        raise StepFailed(f'the GPU nodes have the architectures {sorted(architectures)}. One architecture is supported.')
    return architectures.pop()


def step_gpu_images(ctx):
    """Build the GPU images for the architecture of the GPU nodes and verify the architecture of each in the registry.

    build-hoover.py --gpu builds on a GPU node when its architecture differs from this host (--builder), because an
    emulated build of the model server image is not practical.
    """
    import platform
    arch = gpu_architecture(ctx)
    local = {'x86_64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine(), platform.machine())
    argv = [sys.executable, SOURCE / 'images/build-hoover.py', '--gpu', '--revision', ctx.revision]
    builder = ''
    if arch != local:
        builder = ctx.site.gpu_pool['nodes'][0]
        argv += ['--builder', builder]
    ctx.run(argv)
    references = image_references(ctx, gpu_image_names(ctx), architecture=arch)
    with ctx.records.guard:
        ctx.record.setdefault('images', {}).update(references)
    return {'gpu_images': len(references), 'architecture': arch, 'builder': builder or 'this host'}


def step_frontend(ctx):
    """Install the HTTPS frontend. With the TLS mode internal, the result names the root certificate of the local CA,
    which the person installs in each browser that opens the site."""
    public = ctx.site.with_role('public')[0]
    if not public.local:
        ctx.run(['bash', SOURCE / 'platform/frontend/install-frontend.sh'])
    else:
        ctx.run(['bash', SOURCE / 'platform/frontend/install-local-frontend.sh'])
        Ansible(ctx).run('hoover4-local.yml', [public.name], tags=['frontend'])
        ctx.run(['bash', SOURCE / 'platform/frontend/install-local-frontend.sh', '--ca'])
        Ansible(ctx).run('hoover4-local.yml', [public.name], tags=['trust'])
    if config.tls_mode(public) == 'internal':
        return {'tls_mode': 'internal', 'local_ca': str(ctx.private / 'frontend' / 'local-ca.crt')}
    return {'tls_mode': config.tls_mode(public)}


def wait_rollouts(ctx, namespace, timeout=1800):
    """Wait until every Deployment and StatefulSet of a namespace with replicas is ready, and every claim is Bound."""
    text = ctx.kubectl('-n', namespace, 'get', 'deployments,statefulsets', '-o', 'json', check=False)
    try:
        items = json.loads(text)['items']
    except (ValueError, KeyError):
        raise StepFailed(f'the workloads of {namespace} are unreadable')
    for item in items:
        name = item['metadata']['name']
        if item['spec'].get('replicas', 1) == 0:
            continue
        if (item['spec'].get('updateStrategy') or {}).get('type') == 'OnDelete':
            # kubectl rollout status refuses an OnDelete StatefulSet. Its ready replicas show that it runs.
            code, out = ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', namespace, 'wait',
                                 f'statefulset/{name}', f'--for=jsonpath={{.status.readyReplicas}}={item["spec"].get("replicas", 1)}',
                                 f'--timeout={timeout}s'], capture=True, check=False)
        else:
            code, out = ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', namespace, 'rollout', 'status',
                                 f'{item["kind"].lower()}/{name}', f'--timeout={timeout}s'], capture=True, check=False)
        if code:
            raise StepFailed(f'{namespace}/{item["kind"].lower()}/{name} did not become ready: {out.strip()[-300:]}')
    claims = json.loads(ctx.kubectl('-n', namespace, 'get', 'pvc', '-o', 'json', check=False) or '{"items": []}')['items']
    # A claim with WaitForFirstConsumer and no pod stays Pending without a selected node. That is not a failure.
    pending = [c['metadata']['name'] for c in claims if c.get('status', {}).get('phase') != 'Bound'
               and 'volume.kubernetes.io/selected-node' in (c['metadata'].get('annotations') or {})]
    if pending:
        raise StepFailed(f'the claims {", ".join(pending)} of {namespace} are not Bound.')


def record_settings(ctx, scopes):
    """Record that scopes run the pinned settings revision, after their workloads are ready."""
    state = ctx.operator_state()
    if state is None or ctx.settings_revision is None:
        return []
    with ctx.state_lock:
        state.record_scopes(scopes, ctx.settings_revision, f'deploy:{ctx.record["id"]}', ctx.revision)
    return scopes


# The check sends an invalid code with the client secret of the proxy. Keycloak answers invalid_grant only after it
# accepted the client, so the answer proves the address, the certificate and the secret of the token exchange.
SIGN_IN_CHECK = r"""
import json, os, ssl, sys, urllib.error, urllib.parse, urllib.request
issuer, redirect = sys.argv[1], sys.argv[2]
tls = ssl.create_default_context()
if os.path.exists('/ca/local-ca.crt'):
    tls.load_verify_locations('/ca/local-ca.crt')
try:
    conf = json.load(urllib.request.urlopen(issuer + '/.well-known/openid-configuration', timeout=20, context=tls))
    form = {'grant_type': 'authorization_code', 'code': 'hoover-deploy-check', 'redirect_uri': redirect,
            'client_id': 'opendesk-hoover', 'client_secret': open('/secrets/client-secret').read().strip()}
    urllib.request.urlopen(conf['token_endpoint'], urllib.parse.urlencode(form).encode(), timeout=20, context=tls)
    sys.exit('the token endpoint accepted an invalid code')
except urllib.error.HTTPError as e:
    answer = e.read().decode(errors='replace')
    if e.code == 400 and json.loads(answer or '{}').get('error') == 'invalid_grant':
        print('the token endpoint accepted the client of the proxy')
        sys.exit(0)
    sys.exit(f'the token endpoint answered HTTP {e.code}: {answer[:300]}')
except Exception as e:
    sys.exit(f'the proxy cannot reach the sign-in service: {e}')
"""


def sign_in_check_pod(ctx, hoover):
    """A pod with the OIDC egress label of oauth2-proxy, so the NetworkPolicy of the proxy applies to it."""
    issuer = config.zone_host(hoover.zone, 'id', ctx.site.domain)
    host = config.zone_host(hoover.zone, 'hoover', ctx.site.domain)
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': 'sign-in-check', 'namespace': hoover.namespace,
                         'labels': {'app.kubernetes.io/name': 'sign-in-check', 'hoover.dev/oidc': 'client'}},
            'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'enableServiceLinks': False,
                     'containers': [{'name': 'check', 'image': POD_IMAGE,
                                     'command': ['python3', '-c', SIGN_IN_CHECK, f'https://{issuer}/realms/opendesk',
                                                 f'https://{host}/oauth2/callback'],
                                     'resources': {'limits': {'cpu': '200m', 'memory': '64Mi'}},
                                     'volumeMounts': [{'name': 'secrets', 'mountPath': '/secrets', 'readOnly': True},
                                                      {'name': 'local-ca', 'mountPath': '/ca', 'readOnly': True}]}],
                     'volumes': [{'name': 'secrets', 'secret': {'secretName': 'oauth2-proxy', 'items': [
                                     {'key': 'client-secret', 'path': 'client-secret'}]}},
                                 # Only a site with the TLS mode internal has the local CA of its frontend.
                                 {'name': 'local-ca', 'configMap': {'name': 'local-ca', 'optional': True}}]}}


def check_sign_in(ctx, hoover, timeout=300):
    """Fail the step when oauth2-proxy of the installation cannot exchange a sign-in code with Keycloak.

    A pod that starts reaches the issuer for its discovery. A policy or DNS change after the start breaks only the
    token exchange of the next sign-in, so the rollouts do not show it.
    """
    ns = hoover.namespace
    ctx.kubectl('-n', ns, 'delete', 'pod', 'sign-in-check', '--ignore-not-found', '--wait=true')
    ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, 'apply', '-f', '-'], capture=True,
            input=json.dumps(sign_in_check_pod(ctx, hoover)))
    deadline = time.monotonic() + timeout
    phase = ''
    while time.monotonic() < deadline:
        phase = ctx.kubectl('-n', ns, 'get', 'pod', 'sign-in-check', '-o', 'jsonpath={.status.phase}', check=False).strip()
        if phase in ('Succeeded', 'Failed'):
            break
        time.sleep(3)
    logs = ctx.kubectl('-n', ns, 'logs', 'sign-in-check', check=False).strip()
    events = '' if phase in ('Succeeded', 'Failed') else ctx.kubectl(
        '-n', ns, 'get', 'events', '--field-selector', 'involvedObject.name=sign-in-check', '-o',
        'jsonpath={range .items[*]}{.reason}: {.message}{"\\n"}{end}', check=False).strip()
    ctx.kubectl('-n', ns, 'delete', 'pod', 'sign-in-check', '--wait=false', check=False)
    if phase != 'Succeeded':
        raise StepFailed(f'the sign-in check of {ns} ended in phase {phase or "unknown"}: {(logs or events)[-500:]}')


def step_zone(zone):
    def run(ctx):
        # As the runner does for create-zone: the zone state gets the zone first. The frontend serves every zone host
        # with the certificate of *.<domain>, so a zone needs no frontend change.
        ctx.run([sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); import zone; zone.register(sys.argv[2])',
                 SOURCE / 'zones', zone])
        ctx.run([sys.executable, SOURCE / 'zones/zone.py', 'apply', zone])
        hoovers = [h for h in ctx.hoovers().values() if h.zone == zone]
        for namespace in [zone] + [h.namespace for h in hoovers]:
            wait_rollouts(ctx, namespace)
        for hoover in hoovers:
            check_sign_in(ctx, hoover)
        scopes = record_settings(ctx, [f'zone:{zone}'] + [f'hoover:{h.name}' for h in hoovers])
        return {'settings_revision': ctx.settings_revision, 'scopes': scopes}
    return run


def step_gpu_pool(ctx):
    """Apply the GPU pool with the pinned runtime, wait for it, and call each service with and without the key."""
    ctx.run([sys.executable, SOURCE / 'platform/gpu/gpu_pool.py', 'apply'])
    ctx.run([sys.executable, SOURCE / 'platform/gpu/gpu_pool.py', 'verify'])
    return {'settings_revision': ctx.settings_revision}


def step_operator(ctx):
    """The rights of the zone runner, then the operator login, the portal and the runner in the operator pod.

    The pod runs the operator image of the files of the checkout. The step images builds it, and this step builds it
    only when the registry does not have it, for example after a change of the checkout.
    """
    image = step_operator_image(ctx)
    # The step calls of a portal zone operation needs the record of the coturn peer check, and the runner has no right
    # to run the probe pod.
    ctx.run([sys.executable, SOURCE / 'platform/calls/install-calls.py', '--probe'])
    ctx.run(['bash', SOURCE / 'platform/operator/install-runner.sh'])
    ctx.run(['bash', SOURCE / 'platform/operator/start-web-tools.sh'],
            env={'OPERATOR_IMAGE': image, 'OPERATOR_REVISION': ctx.revision})
    return {'operator_image': image}


def cluster_steps(ctx):
    steps = {
        'tools': step_tools,
        'cluster': step_script('bash', '@cluster/setup.sh'),
        'registry': step_script('bash', '@platform/registry/install-registry.sh'),
        'images': step_images,
        'gpu-images': step_gpu_images,
        'ingress': step_script('bash', '@platform/ingress/install-ingress.sh'),
        'frontend': step_frontend,
        'monitoring': step_script('bash', '@platform/monitoring/install-dashboards.sh'),
        'operator': step_operator,
        'hoover-data': step_script(sys.executable, '@platform/hoover-data/install-hoover-data.py'),
        'gpu-pool': step_gpu_pool,
        'gpu-proxy': step_script(sys.executable, '@hoover/gpu.py', 'install'),
    }
    if not ctx.site.gpu_pool.get('nodes'):
        # A pool at an address runs outside the site, for example on a Compose GPU host.
        del steps['gpu-pool']
        del steps['gpu-images']
    if not ctx.site.gpu_pool:
        # A site without a GPU pool has no GPU services, so it needs no proxy.
        del steps['gpu-proxy']
    if ctx.site.single:
        # The Hoover pods of a single-node site share one node, so their dataset folders are claims and need no NFS.
        del steps['hoover-data']
    # The shared ClickHouse and Garage of the site (../hoover/stores/shared.py). Each zone of the store layout site
    # adds its tenant to them.
    steps['stores'] = step_script(sys.executable, '@hoover/stores/shared.py', 'apply')
    # The scheduler can place a zone pod on any node, so every eligible node pulls the zone images while the zones
    # apply (../images/prepull.py).
    steps['prepull'] = step_prepull
    zones = ctx.hoovers()
    for hoover in zones.values():
        steps[f'zone:{hoover.zone}'] = step_zone(hoover.zone)
    if ctx.site.single and zones:
        # The development relay of a single-node site serves the loopback ports of one Hoover installation, the first
        # zone of the zone state. install-relay.py keeps the port mode that the operator chose.
        relayed = next(iter(zones.values()))
        steps['mcp-relay'] = step_script(sys.executable, '@platform/mcp-relay/install-relay.py', relayed.name, 'apply')
    # The call services join the Jitsi of every zone, so they follow the zones.
    steps['calls'] = step_calls
    return steps


def step_prepull(ctx):
    """Pull the Hoover images of the revision and the images of the zone pods on every eligible node."""
    names = [f'registry.hoover.internal/{n}' for n in image_names(ctx)]
    code, out = ctx.run([sys.executable, SOURCE / 'images/prepull.py', *names], capture=True)
    return json.loads(out.strip().splitlines()[-1])


def step_calls(ctx):
    """Record the coturn peer check of the media node, then install the call services that every zone shares."""
    ctx.run([sys.executable, SOURCE / 'platform/calls/install-calls.py', '--probe'])
    ctx.run([sys.executable, SOURCE / 'platform/calls/install-calls.py'])
    return {}


# ----------------------------------------------------------------------------------------------------------------------
# Shutdown and startup
# ----------------------------------------------------------------------------------------------------------------------

def tier(namespace, name):
    lowered = name.lower()
    # The ingress controller carries the calls of the pods to the zone names, for example the sign-in of an
    # application at its zone Keycloak, so it stops and starts with the stores. The frontend, the zone gates and the
    # Hoover proxies take the requests of the users, so they stop first and start last.
    if namespace == 'ingress':
        return 'stores'
    if lowered == 'gate' or lowered.endswith('-gate') or lowered.startswith('oauth2-proxy'):
        return 'ingress'
    # The stores of Temporal, for example temporal-cassandra and temporal-opensearch, belong to the stores.
    if any(w in lowered for w in STORE_WORDS):
        return 'stores'
    if any(w in lowered for w in TEMPORAL_WORDS):
        return 'temporal'
    return 'applications'


def zone_namespaces(ctx):
    names = []
    for hoover in ctx.hoovers().values():
        names += [hoover.zone, hoover.namespace]
    return names


def workloads(ctx):
    """{tier: [(namespace, kind, name, replicas)]} of the zone namespaces, the shared stores and the ingress."""
    out = {'ingress': [], 'applications': [], 'temporal': [], 'stores': []}
    for namespace in ['ingress', SHARED_STORES] + zone_namespaces(ctx):
        text = ctx.kubectl('-n', namespace, 'get', 'deployments,statefulsets', '-o', 'json', check=False)
        try:
            items = json.loads(text)['items']
        except (ValueError, KeyError):
            continue
        for item in items:
            name = item['metadata']['name']
            out[tier(namespace, name)].append((namespace, item['kind'].lower(), name, item['spec'].get('replicas', 1)))
    return out


def stop_tier(group):
    def run(ctx):
        stopped = ctx.records.stopped()
        found = workloads(ctx)[group]
        for namespace, kind, name, replicas in found:
            key = f'{namespace}/{kind}/{name}'
            if replicas and key not in stopped:
                stopped[key] = replicas
                ctx.records.save_stopped(stopped)
            if replicas:
                ctx.kubectl('-n', namespace, 'scale', kind, name, '--replicas=0')
        if group == 'applications':
            # Scheduled writers stop with the applications: each CronJob of a zone namespace that runs on its schedule
            # is suspended, and the record names it, so the start resumes only these CronJobs.
            for namespace in zone_namespaces(ctx):
                text = ctx.kubectl('-n', namespace, 'get', 'cronjobs', '-o', 'json', check=False)
                try:
                    items = json.loads(text)['items']
                except (ValueError, KeyError):
                    continue
                for item in items:
                    if item['spec'].get('suspend'):
                        continue
                    key = f'{namespace}/cronjob/{item["metadata"]["name"]}'
                    stopped[key] = 1
                    ctx.records.save_stopped(stopped)
                    ctx.kubectl('-n', namespace, 'patch', 'cronjob', item['metadata']['name'], '--type', 'merge',
                                '-p', '{"spec":{"suspend":true}}')
        # Each workload ends through its own shutdown. The workers drain their activities in their grace period.
        for namespace, kind, name, _ in found:
            wait_pods_gone(ctx, namespace, kind, name)
        return {'stopped': len(found)}
    return run


def wait_pods_gone(ctx, namespace, kind, name, timeout=900):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = ctx.kubectl('-n', namespace, 'get', kind, name, '-o', 'jsonpath={.status.replicas}', check=False)
        if text.strip() in ('', '0'):
            return
        time.sleep(3)
    raise StepFailed(f'{namespace}/{kind}/{name} still has pods after {timeout} s.')


def start_tier(group):
    def run(ctx):
        stopped = ctx.records.stopped()
        started = []
        for key, replicas in sorted(stopped.items()):
            namespace, kind, name = key.split('/')
            if kind == 'cronjob':
                if group == 'applications':
                    ctx.kubectl('-n', namespace, 'patch', 'cronjob', name, '--type', 'merge',
                                '-p', '{"spec":{"suspend":false}}')
                    started.append((namespace, kind, name))
            elif tier(namespace, name) == group:
                ctx.kubectl('-n', namespace, 'scale', kind, name, f'--replicas={replicas}')
                started.append((namespace, kind, name))
        for namespace, kind, name in started:
            if kind == 'cronjob':
                continue
            ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', namespace, 'rollout', 'status', f'{kind}/{name}',
                     '--timeout=900s'], capture=True)
        for namespace, kind, name in started:
            stopped.pop(f'{namespace}/{kind}/{name}', None)
        ctx.records.save_stopped(stopped)
        if group == 'ingress' and not stopped:
            ctx.records.clear_stopped()
        return {'started': len(started)}
    return run


def wait_api(ctx, timeout=300):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if node_ready(ctx, ctx.site.control_plane):
            return
        time.sleep(5)
    raise StepFailed(f'the node {ctx.site.control_plane} is not Ready after {timeout} s. See journalctl -u k3s.')


# ----------------------------------------------------------------------------------------------------------------------
# Plans
# ----------------------------------------------------------------------------------------------------------------------

def ordered_nodes(site, targets):
    nodes = [site.nodes[t] for t in targets]
    return sorted(nodes, key=lambda n: (n.name != site.control_plane, n.has('gpu'), n.name))


def plan(ctx, command, targets, start=False):
    """{step name: function} in order."""
    steps = {}
    nodes = ordered_nodes(ctx.site, targets)
    control = ctx.site.control_plane in targets
    if command == 'up' and start:
        for node in nodes:
            steps[f'start:k3s:{node.name}'] = service_step('start', node.name)
        if control:
            for name in START_ORDER:
                steps[name] = start_tier(name.split(':')[1])
        return steps
    if command == 'up':
        steps.update(HOST_STEPS)
        if control:
            steps.update(cluster_steps(ctx))
        return steps
    if command == 'down':
        if control:
            for name in STOP_ORDER:
                steps[name] = stop_tier(name.split(':')[1])
        for node in reversed(nodes):
            steps[f'stop:k3s:{node.name}'] = service_step('stop', node.name)
        return steps
    raise ValueError(command)


def matches(step, wanted):
    return step == wanted or step.startswith(wanted + ':') or step.endswith(':' + wanted)


def select(steps, only):
    if not only:
        return steps
    unknown = [o for o in only if not any(matches(k, o) for k in steps)]
    if unknown:
        raise StepFailed(f'the plan has no step {", ".join(unknown)}. The steps are: {", ".join(steps)}')
    return {k: v for k, v in steps.items() if any(matches(k, o) for o in only)}


# ----------------------------------------------------------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------------------------------------------------------

def independent(step, other):
    """True when step does not depend on the earlier step other: they act on different nodes."""
    a, b = step.split(':'), other.split(':')
    for prefix in (('start', 'k3s'), ('stop', 'k3s')):
        n = len(prefix)
        if tuple(a[:n]) == prefix and tuple(b[:n]) == prefix and len(a) > n and len(b) > n and a[n] != b[n]:
            return True
    return False


# The prerequisites of the cluster steps of up, by step name. A step starts when the named steps of the plan are done.
# The images of the revision come before every step that starts them, and the operator pod reads the monitoring
# Services. A zone needs every platform step except prepull, which pulls the zone images on the nodes while the zones
# apply. The call services join the Jitsi of every zone, and the relay serves a zone, so both follow the zones.
# A step that this table does not name, for example a host step or a step of down, waits for every earlier step that
# is not independent() of it.
PLATFORM = ('ingress', 'frontend', 'monitoring', 'operator', 'hoover-data', 'stores', 'gpu-images', 'gpu-pool', 'gpu-proxy')
PREREQUISITES = {
    'images': ('registry',),
    'gpu-images': ('registry',),
    'ingress': ('registry',),
    'frontend': ('registry',),
    'monitoring': ('registry',),
    'hoover-data': ('registry',),
    'operator': ('images', 'monitoring'),
    'stores': ('images',),
    'prepull': ('images',),
    'gpu-pool': ('gpu-images', 'images'),
    'gpu-proxy': ('gpu-pool', 'images'),
    'zone:': ('registry', 'images') + PLATFORM,
    'mcp-relay': ('zone:',) + PLATFORM,
    'calls': ('zone:',) + PLATFORM,
}
# The steps before the registry form a chain: each one waits for every earlier step.
CHAIN = ('hosts:', 'tools', 'cluster', 'registry')


def prerequisites(names):
    """{step: [earlier steps that it waits for]} for the steps of a plan in their order."""
    out = {}
    for index, name in enumerate(names):
        earlier = names[:index]
        rule = PREREQUISITES.get('zone:' if name.startswith('zone:') else name)
        if rule is None or name.startswith(CHAIN):
            out[name] = [e for e in earlier if not independent(name, e)]
            continue
        wanted = [e for e in earlier if any(e == r or (r.endswith(':') and e.startswith(r)) for r in rule)]
        # The chain steps before the registry stay before every later step.
        wanted += [e for e in earlier if e.startswith(CHAIN) and e not in wanted]
        out[name] = wanted
    return out


def execute(ctx, record, steps):
    """Run the unfinished steps of a record, each step when its prerequisites are done. Return the exit code.

    Steps without a dependency between them run at the same time, each in its own thread, and at most
    config.parallel_zones() zone steps at once. The record keeps the state of each step. A failed step stops the start
    of further steps, the running steps finish, and the run ends with the failure. A waiting step blocks every later
    step that depends on it, and the run continues with the independent steps, for example the start of the other
    nodes. An interrupt marks the record interrupted. A resume runs every step that is not done.
    """
    import threading
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as wait_futures
    ctx.record = record
    ctx.revision = record['revision']
    ctx.settings_revision = (record.get('inputs') or {}).get('settings_revision')
    ctx.shell = Shell(ctx.records.folder / 'logs' / f'{record["id"]}.log')

    def on_signal(number, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, on_signal)
    waiting, blocked = [], []
    record['status'] = 'running'
    record['error'] = ''
    ctx.records.save(record)
    names = [entry['name'] for entry in record['steps']]
    needs = prerequisites(names)
    done = {entry['name'] for entry in record['steps'] if entry['state'] == 'done'}
    todo = [n for n in names if n not in done]
    zone_limit = config.parallel_zones(ctx.site) if getattr(ctx, 'site', None) is not None else 1
    pool = ThreadPoolExecutor(max_workers=max(1, len(todo)))
    running = {}
    failure = None

    def run_step(name):
        Shell.step.name = name
        try:
            fields = steps[name](ctx) or {}
            with ctx.state_lock:
                sync_state(ctx, 'push')
            return fields
        finally:
            Shell.step.name = None

    try:
        verify_inputs(ctx, record)
        while todo or running:
            for name in list(todo):
                if failure:
                    break
                holding = [w for w in needs[name] if w in waiting or w in blocked]
                if holding:
                    todo.remove(name)
                    blocked.append(name)
                    ctx.records.mark(record, name, 'pending', blocked_by=holding[0])
                    continue
                if any(w not in done for w in needs[name]):
                    continue
                if name.startswith('zone:') and sum(r.startswith('zone:') for r in running.values()) >= zone_limit:
                    continue
                todo.remove(name)
                ctx.records.mark(record, name, 'running')
                print(json.dumps({'at': time.strftime('%H:%M:%S'), 'record': record['id'], 'step': name}), flush=True)
                running[pool.submit(run_step, name)] = name
            if not running:
                break
            finished, _ = wait_futures(list(running), return_when=FIRST_COMPLETED)
            for future in finished:
                name = running.pop(future)
                error = future.exception()
                if error is None:
                    record['steps'][names.index(name)].pop('blocked_by', None)
                    ctx.records.mark(record, name, 'done', **future.result())
                    done.add(name)
                elif isinstance(error, KeyboardInterrupt):
                    raise KeyboardInterrupt
                elif isinstance(error, StepWaiting):
                    ctx.records.mark(record, name, 'waiting', message=str(error))
                    waiting.append(name)
                    record.setdefault('messages', {})[name] = str(error)
                elif isinstance(error, (StepFailed, config.SiteError, subprocess.SubprocessError, OSError)):
                    ctx.records.mark(record, name, 'failed', error=str(error))
                    print(f'deploy-k3s: step {name} failed: {error}', file=sys.stderr)
                    failure = failure or (name, error)
                else:
                    raise error
        if failure:
            name, error = failure
            record['status'] = 'failed'
            record['error'] = f'{name}: {error}'
            ctx.records.save(record)
            try:
                sync_state(ctx, 'push')
            except StepFailed as sync_error:
                print(f'deploy-k3s: {sync_error}', file=sys.stderr)
            print(f'deploy-k3s: the record {record["id"]} keeps the finished steps and the revision '
                  f'{record["revision"][:12]}. Fix the cause, then run: deploy-k3s {record["command"]} '
                  f'--resume {record["id"]}', file=sys.stderr)
            return 2
    except StepFailed as error:
        record['status'] = 'failed'
        record['error'] = str(error)
        ctx.records.save(record)
        print(f'deploy-k3s: {error}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        record['status'] = 'interrupted'
        record['error'] = 'the driver stopped before the end of the steps'
        ctx.records.save(record)
        print(f'deploy-k3s: interrupted. Run deploy-k3s {record["command"]} --resume {record["id"]} to continue.',
              file=sys.stderr)
        return 130
    finally:
        # A running step ends with its command. Its state stays running in the record, so a resume runs it again.
        pool.shutdown(wait=False, cancel_futures=True)
        signal.signal(signal.SIGTERM, previous)
    if waiting:
        messages = [record['messages'][w] for w in waiting]
        record['status'] = 'waiting'
        record['error'] = ' '.join(messages) + (f' Blocked steps: {", ".join(blocked)}.' if blocked else '')
        ctx.records.save(record)
        print('deploy-k3s: the deployment is not complete. ' + record['error'], file=sys.stderr)
        return 3
    if record['command'] == 'up' and record.get('complete'):
        state = ctx.operator_state()
        if state is not None and ctx.settings_revision is not None:
            state.record_all(ctx.settings_revision, f'deploy:{record["id"]}', record['revision'])
            sync_state(ctx, 'push')
        ctx.records.finish(record)
    else:
        record['status'] = 'done'
        ctx.records.save(record)
    print(json.dumps({'record': record['id'], 'status': 'done', 'revision': record['revision']}), flush=True)
    return 0


# ----------------------------------------------------------------------------------------------------------------------
# render and check
# ----------------------------------------------------------------------------------------------------------------------

def nfs_read_only(ctx):
    out = {}
    for node in ctx.site.with_role('data'):
        code, text = read(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', 'hoover-data', 'get', 'service',
                           f'nfs-{node.name}', '-o', 'jsonpath={.spec.clusterIP}'], timeout=20)
        if code == 0 and text:
            out[node.name] = text
    return out


def public_endpoints(site):
    """The DNS records and the firewall rules of the public and calls nodes (platform/calls/public_endpoints.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('public_endpoints', SOURCE / 'platform/calls/public_endpoints.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {'media_node': config.calls_node(site).name, 'dns': module.dns(site), 'firewall': module.firewall(site)}


def render(ctx, targets, revision, manifests=False):
    """The configuration of the selected targets, as a dict. It reads files and the cluster, and changes nothing."""
    out = {'site': ctx.site.id, 'site_file': str(ctx.site_path), 'state': str(ctx.private), 'revision': revision,
           'checkout_changes': dirty_files(ctx.repo), 'settings': config.legacy_settings(ctx.site),
           'nodes': {t: config.project(ctx.site, t) for t in targets},
           'ansible_variables': config.ansible_variables(ctx.site, ctx.private),
           'up': list(plan(ctx, 'up', targets)), 'start': list(plan(ctx, 'up', targets, start=True)),
           'down': list(plan(ctx, 'down', targets)),
           'applied': (ctx.records.applied() or {}).get('revision'), 'operator_settings': {},
           'public_endpoints': public_endpoints(ctx.site)}
    if (ctx.state / 'desired.json').exists():
        sys.path.insert(0, str(SOURCE / 'platform/operator'))
        import settings as operator_settings
        state = operator_settings.State(ctx.state)
        out['operator_settings'] = {'revision': state.revision(), 'overrides': state.overrides()}
    if manifests:
        sys.path.insert(0, str(SOURCE / 'hoover'))
        import manifests as hoover_manifests
        out['manifests'] = {}
        for hoover in ctx.hoovers().values():
            try:
                target = hoover_manifests.target_from_site(str(ctx.site_path), hoover.name, revision=revision,
                                                           nfs=nfs_read_only(ctx))
                out['manifests'][hoover.name] = json.loads(hoover_manifests.render(target))
            except Exception as error:  # noqa: BLE001 - the render names the reason of each installation
                out['manifests'][hoover.name] = {'error': str(error)}
    return out


def measure_speed(ctx, targets):
    """Measure the CPU speed and the disk speeds of the targets again (role hoover4_speed with hoover4_speed_force).

    The play refuses a node where k3s or a container runs, or whose load is above 5, and names the reason. Return the
    stored speeds of the targets.
    """
    Ansible(ctx).run('hoover4-hosts.yml', targets, extra={'hoover4_speed_force': True}, tags=['speed'])
    return {name: config.speed_report(ctx.site, ctx.private)[name] for name in targets}


def check(ctx, targets):
    """The problems of the selected targets, as messages, and their state, as a dict.

    The facts play (playbooks/hoover4-hosts.yml, tag facts) reads each node and changes nothing on it. It writes the
    facts into facts/<node>.json of the state folder.
    """
    problems, state = list(config.missing_files(ctx.site)), {}
    try:
        zone_state = ctx.private / 'zone-state.json'
        problems += config.zones_problems(ctx.site, json.loads(zone_state.read_text()) if zone_state.exists() else {'zones': {}})
        problems += [f'the zone {h.zone} keeps its ClickHouse and Garage in its zone namespace, from an earlier version. '
                     'The installer refuses to apply it. Delete the zone and create it again: its data does not move.'
                     for h in ctx.hoovers().values() if h.stores == 'zone']
        problems += [f'the zone {h.zone} runs its own Temporal on the PostgreSQL of the zone, from an earlier version. '
                     'The installer refuses to apply it. Delete the zone and create it again: its workflow history does '
                     'not move to the Temporal of the site.'
                     for h in ctx.hoovers().values() if h.stores == 'site' and h.temporal == 'zone']
        problems += [f'the zone {h.zone} runs its own Manticore daemons in the zone namespace, from an earlier version. '
                     'The installer refuses to apply it. Delete the zone and create it again: its search tables do not '
                     'move to the Manticore of the site.'
                     for h in ctx.hoovers().values() if h.stores == 'site' and h.manticore == 'zone']
    except (ValueError, config.SiteError, StepFailed) as error:
        problems.append(str(error))
    try:
        Ansible(ctx).run('hoover4-hosts.yml', targets, tags=['facts'])
    except StepFailed as error:
        problems.append(str(error))
    speeds = config.speed_report(ctx.site, ctx.private)
    for name in targets:
        facts = ctx.private / 'facts' / f'{name}.json'
        state[name] = json.loads(facts.read_text()) if facts.exists() else {'reachable': False}
        state[name]['ready'] = node_ready(ctx, name)
        # The stored CPU and disk speeds (role hoover4_speed). note says how to measure a node without a value.
        state[name]['speed'] = speeds[name]
    if ctx.site.control_plane in targets:
        missing = [str(p) for p in tool_paths(ctx) if not p.exists()]
        if missing:
            problems.append('the operator tools are missing: ' + ', '.join(missing) + '. deploy-k3s up installs them.')
        if not ctx.kubeconfig.exists():
            problems.append(f'the admin kubeconfig {ctx.kubeconfig} is missing. deploy-k3s up writes it.')
        state['checkout_changes'] = dirty_files(ctx.repo)
        state['applied'] = (ctx.records.applied() or {}).get('revision')
        # The direct WireGuard peers. The person adds the rows with by = hand on the node that keeps its interface.
        state['peers'] = config.peer_table(ctx.site)
        state['switches'] = {n.name: config.switches(n) for n in ctx.site.nodes.values()}
        state['stopped'] = ctx.records.stopped()
        if ctx.kubeconfig.exists():
            found = ctx.kubectl('-n', SHARED_STORES, 'get', 'configmap', 'shared-stores', '--ignore-not-found', '-o', 'json', check=False).strip()
            try:
                before = json.loads(json.loads(found)['data']['plan']) if found else None
            except (ValueError, KeyError):
                before = None
            problems += config.store_change_problems(before, config.store_plan(ctx.site))
            # The placement plan of the store pods and the fit of vars.replicas (../hoover/stores/placement.py). The
            # last line of the command is its JSON answer.
            code, text = ctx.run([sys.executable, SOURCE / 'hoover/stores/shared.py', 'plan'], capture=True, check=False)
            try:
                answer = json.loads(text.strip().splitlines()[-1])
                state['store_placement'] = answer['placement']
                problems += answer['problems']
            except (ValueError, IndexError, KeyError):
                problems.append(f'the placement plan of the stores failed with code {code}: {text.strip()[-400:]}')
    return problems, state
