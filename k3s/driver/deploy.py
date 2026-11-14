"""The deployment driver of ../deploy-k3s. Standard library only. It runs in the operator image (../images/operator).

The driver reads the site file (../config.py) and runs the Ansible playbooks of ../ansible for the hosts, the cluster
scripts of ../cluster/ and ../platform/, and the zone installer of ../zones/ in their order. records.py keeps the
state of each run in the operator state of the site.

Host steps. Each one is one Ansible run on all target nodes in parallel (class Ansible):
  hosts:prepare  playbooks/hoover4-hosts.yml: the facts of each node, its packages, kernel modules, sysctl,
                 NetworkManager, SELinux, the local node of a single-node site, the backup folder, the optional public
                 firewall and the WireGuard peers. The facts go to facts/<node>.json of the state folder.
  hosts:k3s      playbooks/hoover4-k3s.yml: gVisor, Kata Containers, the GPU runtime, the tokens, the k3s configuration
                 and the registry mirror, then k3s on the server and on the agents. The server play converts a SQLite
                 datastore to etcd after a verified copy, verifies etcd and writes the admin kubeconfig into the state
                 folder with the node address of the server.
  hosts:verify   reads each target through the admin kubeconfig: Ready, the k3s version, the flannel interface, and
                 cluster-init and the etcd role of the server. A missing kubeconfig fails with its path.
The nodes connect with SSH as the user of the workstation. become uses sudo without a password, or the password that
--ask-become-pass reads once. down and up --start run playbooks/hoover4-service.yml on one node at a time.
A failed step ends the run. render and check change no host and no cluster.

Pinned inputs. The record of an up or a down keeps the commit of HEAD of the checkout, `git status --porcelain` of the
checkout, the SHA-256 of the site file, the settings revision of the operator state and the identity of the cluster
(the UID of the namespace kube-system). A resume refuses a changed site file, another commit or another cluster. The
commands of the steps get HOOVER4_REVISION and HOOVER4_SETTINGS_REVISION, so every render, also a nested one, uses the
pinned values. A zone step records the scopes of its zone and its Hoover installations as applied with the pinned
settings revision after their workloads are ready. A finished complete up records the revision for every scope.
"""
import json
import os
import re
import shlex
import signal
import subprocess
import sys
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
STORE_WORDS = ('clickhouse', 'manticore', 'garage', 'cassandra', 'elasticsearch', 'zookeeper', 'postgres', 'redis',
               'memcached', 'seaweedfs', 'minio', 'mariadb', 'nats', 'ldap', 'keycloak')
TEMPORAL_WORDS = ('temporal',)


class StepFailed(RuntimeError):
    """A step failed. The message tells the operator what to do."""


class StepWaiting(RuntimeError):
    """A step needs an operator action. A waiting step blocks the steps that depend on it."""


# ----------------------------------------------------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------------------------------------------------

class Shell:
    """Runs commands, prints each command, and appends the output to the log of the deployment."""

    def __init__(self, log=None, env=None):
        self.log = Path(log) if log else None
        self.env = dict(os.environ, **(env or {}))

    def _write(self, text):
        if self.log:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log, 'a') as f:
                f.write(text)

    def run(self, argv, sudo=False, cwd=None, env=None, check=True, capture=False, input=None):
        argv = [str(a) for a in argv]
        if sudo:
            argv = ['sudo', '-n', *argv]
        line = '$ ' + ' '.join(shlex.quote(a) for a in argv)
        print(line, flush=True)
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
                print('  ' + out, end='', flush=True)
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
        env = {'KUBECONFIG': str(self.kubeconfig), 'HOOVER4_SITE': str(self.site_path), 'HELM': str(self.private / 'bin/helm'),
               'PATH': f"{self.private / 'bin'}:{os.environ.get('PATH', '')}"}
        if self.revision:
            env['HOOVER4_REVISION'] = self.revision
        if self.settings_revision is not None:
            env['HOOVER4_SETTINGS_REVISION'] = str(self.settings_revision)
        return env

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
    sys.path.insert(0, str(SOURCE / 'hoover'))
    sys.path.insert(0, str(SOURCE / 'zones'))
    import compose
    import zones
    tag = ctx.revision[:12]
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
    endpoint = config.legacy_settings(ctx.site)['registry_endpoint']
    out = {}
    for name in names if names is not None else image_names(ctx):
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
    """Build and push the images of the revision. The registry step runs before, so the push has a target."""
    sys.path.insert(0, str(SOURCE / 'zones'))
    import zones
    for directory, image in (('blockmount', 'hoover/blockmount:8'),
                             ('nextcloud-ai', f'hoover/nextcloud-ai:{zones.NEXTCLOUD_IMAGE_TAG}'),
                             ('xwiki-extensions', f'hoover/xwiki-extensions:{zones.XWIKI_EXTENSIONS_TAG}')):
        ctx.run(['bash', SOURCE / 'images/build-image.sh', SOURCE / 'images' / directory, image])
    ctx.run([sys.executable, SOURCE / 'images/build-hoover.py', '--revision', ctx.revision])
    arch = node_architecture(ctx, ctx.site.control_plane)
    ctx.record['images'] = image_references(ctx, architecture=arch)
    return {'images': len(ctx.record['images']), 'architecture': arch}


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
    zone = f'{hoover.zone}.{ctx.site.domain}'
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': 'sign-in-check', 'namespace': hoover.namespace,
                         'labels': {'app.kubernetes.io/name': 'sign-in-check', 'hoover.dev/oidc': 'client'}},
            'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'enableServiceLinks': False,
                     'containers': [{'name': 'check', 'image': POD_IMAGE,
                                     'command': ['python3', '-c', SIGN_IN_CHECK, f'https://id.{zone}/realms/opendesk',
                                                 f'https://hoover.{zone}/oauth2/callback'],
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


def step_zone(zone, home):
    def run(ctx):
        # As the runner does for create-zone: the zone state gets the zone first, and the frontend then serves its
        # names with a certificate. The install needs those names, for example the object storage of openDesk.
        ctx.run([sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); import zone; zone.register(sys.argv[2], sys.argv[3])',
                 SOURCE / 'zones', zone, home])
        step_frontend(ctx)
        ctx.run([sys.executable, SOURCE / 'zones/zone.py', 'apply', zone, '--home', home])
        hoovers = [h for h in ctx.site.hoovers.values() if h.zone == zone]
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
    ctx.run(['bash', SOURCE / 'platform/operator/start-web-tools.sh'])
    ctx.run(['bash', SOURCE / 'platform/operator/install-runner.sh'])
    return {}


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
    if ctx.site.single:
        # The Hoover pods of a single-node site share one node, so their dataset folders are claims and need no NFS.
        del steps['hoover-data']
    for hoover in ctx.site.hoovers.values():
        steps[f'zone:{hoover.zone}'] = step_zone(hoover.zone, hoover.home_node)
    if ctx.site.single and ctx.site.hoovers:
        # The development relay of a single-node site serves the loopback ports of one Hoover installation, the
        # migrated one when the site has it. install-relay.py keeps the port mode that the operator chose.
        relayed = next((h for h in ctx.site.hoovers.values() if h.source_ini), next(iter(ctx.site.hoovers.values())))
        steps['mcp-relay'] = step_script(sys.executable, '@platform/mcp-relay/install-relay.py', relayed.name, 'apply')
    # The call services join the Jitsi of every zone, so they follow the zones.
    steps['calls'] = step_script(sys.executable, '@platform/calls/install-calls.py')
    return steps


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
    # The stores of Temporal, for example temporal-cassandra, belong to the stores.
    if any(w in lowered for w in STORE_WORDS):
        return 'stores'
    if any(w in lowered for w in TEMPORAL_WORDS):
        return 'temporal'
    return 'applications'


def zone_namespaces(ctx):
    names = []
    for hoover in ctx.site.hoovers.values():
        names += [hoover.zone, hoover.namespace]
    return names


def workloads(ctx):
    """{tier: [(namespace, kind, name, replicas)]} of the zone namespaces and the ingress."""
    out = {'ingress': [], 'applications': [], 'temporal': [], 'stores': []}
    for namespace in ['ingress'] + zone_namespaces(ctx):
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


def execute(ctx, record, steps):
    """Run the unfinished steps of a record in order. Return the exit code.

    A failed step ends the run. A waiting step blocks every later step that depends on it, and the run continues with
    the independent steps, for example the start of the other nodes.
    """
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
    try:
        verify_inputs(ctx, record)
        for entry in record['steps']:
            name = entry['name']
            if entry['state'] == 'done':
                continue
            holding = [w for w in waiting + blocked if not independent(name, w)]
            if holding:
                blocked.append(name)
                ctx.records.mark(record, name, 'pending', blocked_by=holding[0])
                continue
            ctx.records.mark(record, name, 'running')
            print(json.dumps({'at': time.strftime('%H:%M:%S'), 'record': record['id'], 'step': name}), flush=True)
            try:
                fields = steps[name](ctx) or {}
            except StepWaiting as wait:
                ctx.records.mark(record, name, 'waiting', message=str(wait))
                waiting.append(name)
                record.setdefault('messages', {})[name] = str(wait)
                continue
            except (StepFailed, config.SiteError, subprocess.SubprocessError, OSError) as error:
                ctx.records.mark(record, name, 'failed', error=str(error))
                record['status'] = 'failed'
                record['error'] = f'{name}: {error}'
                ctx.records.save(record)
                print(f'deploy-k3s: step {name} failed: {error}', file=sys.stderr)
                print(f'deploy-k3s: the record {record["id"]} keeps the finished steps and the revision '
                      f'{record["revision"][:12]}. Fix the cause, then run: deploy-k3s {record["command"]} '
                      f'--resume {record["id"]}', file=sys.stderr)
                return 2
            entry.pop('blocked_by', None)
            ctx.records.mark(record, name, 'done', **fields)
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
        for hoover in ctx.site.hoovers.values():
            try:
                target = hoover_manifests.target_from_site(str(ctx.site_path), hoover.name, revision=revision,
                                                           nfs=nfs_read_only(ctx))
                out['manifests'][hoover.name] = json.loads(hoover_manifests.render(target))
            except Exception as error:  # noqa: BLE001 - the render names the reason of each installation
                out['manifests'][hoover.name] = {'error': str(error)}
    return out


def check(ctx, targets):
    """The problems of the selected targets, as messages, and their state, as a dict.

    The facts play (playbooks/hoover4-hosts.yml, tag facts) reads each node and changes nothing on it. It writes the
    facts into facts/<node>.json of the state folder.
    """
    problems, state = list(config.missing_files(ctx.site)), {}
    try:
        Ansible(ctx).run('hoover4-hosts.yml', targets, tags=['facts'])
    except StepFailed as error:
        problems.append(str(error))
    for name in targets:
        facts = ctx.private / 'facts' / f'{name}.json'
        state[name] = json.loads(facts.read_text()) if facts.exists() else {'reachable': False}
        state[name]['ready'] = node_ready(ctx, name)
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
    return problems, state
