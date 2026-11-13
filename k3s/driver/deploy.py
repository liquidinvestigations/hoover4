"""The deployment driver of ../deploy-k3s. Standard library only.

The driver reads the site file (../config.py) and runs the host scripts of ../hosts/, the cluster scripts of
../cluster/ and ../platform/, and the zone installer of ../zones/ in their order. records.py keeps the state of each
run on the control-plane host.

Host adapters:
  local-arch      the local node of a single-node site on an Arch-based distribution. The driver writes the bundle
                  ~/k3s-install/<revision>/ with hosts.json and hard links of the staged files, and runs the root
                  scripts with sudo -n, the bundle name and the node name.
  remote          a node with dnf or apt, over SSH, or the local node of a site with more nodes, in a local shell.
                  probe   reads the OS family, the architecture and the root routes of the node (hostroute.py).
                  bundle  writes the node bundle into k3s/private/deploy/remote/<node>/<revision>/ and copies it into
                          ~/k3s-install/<revision>/ of the node over the user shell: the root scripts of the pinned
                          tree, hosts.json, the part of the site of the node, the token that the node needs, the stage
                          script and bootstrap.sh with README.txt. The token files are private and stay out of logs.
                  stage   downloads and verifies the k3s, gVisor and Kata files into the bundle on the node, as the
                          operator user.
                  root    runs the root scripts of the bundle through the first root route of the node: sudo -n, else
                          the cluster for a Ready node. The scripts get names only: the bundle (the revision), the
                          node and the operator user. The host paths come from hosts.json of the bundle. The cluster
                          route also refreshes the copies of the scripts in /usr/local/libexec/hoover4. A node without a route waits: the operator runs bootstrap.sh of
                          the bundle once as root, then resumes the record.
                  verify  reads the installed state of the node (root-install-k3s.py --report) and compares it with the
                          bundle: the script copies, the k3s version, the k3s configuration, the active unit, the
                          Ready node, and etcd on the server. A difference fails the step.
A waiting or failed step stops every step that depends on it: the later steps of its node and every cluster step.
The steps of the other nodes still run. render and check change no host and no cluster.

Pinned inputs. The record of an up or a down keeps the commit, the fingerprint of its exported tree (source.py), the
SHA-256 of the site file, the settings revision of the operator state and the identity of the cluster (the UID of the
namespace kube-system). A resume refuses a changed site file, a changed tree or another cluster. The commands of the
steps get HOOVER4_REVISION and HOOVER4_SETTINGS_REVISION, so every render, also a nested one, uses the pinned values.
A zone step records the scopes of its zone and its Hoover installations as applied with the pinned settings revision
after their workloads are ready. A finished complete up records the revision for every scope.
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
import hostroute  # noqa: E402
import records as records_module  # noqa: E402
import source as source_module  # noqa: E402

ARTIFACTS = json.loads((HERE / 'artifacts.json').read_text())
FAMILIES = {'arch': 'arch', 'cachyos': 'arch', 'endeavouros': 'arch', 'manjaro': 'arch',
            'rhel': 'rhel', 'rocky': 'rhel', 'almalinux': 'rhel', 'centos': 'rhel', 'fedora': 'rhel',
            'debian': 'debian', 'ubuntu': 'debian'}
SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=accept-new']
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
    """A step needs an operator action on a host."""


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
        self.private = Path(private) if private else SOURCE / 'private'
        self.state = site.operator_state()
        self.records = records_module.Records(self.state / 'deploy')
        self.kubeconfig = Path(os.environ.get('KUBECONFIG') or self.private / 'kubeconfig')
        self.revision = None
        self.settings_revision = None
        self.record = None
        self.shell = Shell()

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

    def bundle_name(self):
        """The bundle of the record: the first 12 characters of its revision, or 'current' without a record."""
        return ((self.record or {}).get('revision') or 'current')[:12]


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


def pinned_inputs(ctx, tree=None):
    """The inputs that a record pins at its start."""
    state = ctx.operator_state()
    return {'site_fingerprint': site_fingerprint(ctx.site_path), 'site_file': str(ctx.site_path),
            'settings_revision': state.revision() if state else 0, 'cluster_identity': cluster_identity(ctx),
            'tree': str(tree) if tree else '', 'tree_fingerprint': source_module.fingerprint(tree) if tree else ''}


def verify_inputs(ctx, record):
    """Refuse a resume whose site file, tree or cluster changed. Record the cluster identity once it exists."""
    inputs = record.get('inputs')
    if not inputs:
        return
    problems = []
    if site_fingerprint(ctx.site_path) != inputs['site_fingerprint']:
        problems.append(f'the site file {ctx.site_path} changed after the start of the record')
    if inputs.get('tree'):
        tree = Path(inputs['tree'])
        if source_module.is_export(tree) != record['revision']:
            problems.append(f'the exported tree {tree} of {record["revision"][:12]} is missing')
        elif source_module.fingerprint(tree) != inputs['tree_fingerprint']:
            problems.append(f'the exported tree {tree} changed after the start of the record')
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
    """The changed files of the checkout. The driver never resets them. An exported tree has no checkout and no changes."""
    if source_module.is_export(repo):
        return []
    r = subprocess.run(['git', '-C', str(repo), 'status', '--porcelain'], capture_output=True, text=True)
    return [line[3:] for line in r.stdout.splitlines()] if r.returncode == 0 else [f'git status failed: {r.stderr.strip()}']


# ----------------------------------------------------------------------------------------------------------------------
# Host adapters
# ----------------------------------------------------------------------------------------------------------------------

def os_family(release_text):
    values = dict(line.split('=', 1) for line in release_text.splitlines() if '=' in line)
    ids = [values.get('ID', '').strip('"')] + values.get('ID_LIKE', '').strip('"').split()
    for value in ids:
        if value in FAMILIES:
            return FAMILIES[value]
    return 'unknown'


class LocalArch:
    kind = 'local-arch'
    SCRIPT_STEPS = ('software', 'settings', 'storage')
    OS_RELEASE = Path('/etc/os-release')

    def __init__(self, ctx, node):
        self.ctx, self.node = ctx, node

    def problems(self):
        """The prerequisites of the host that are missing. Read-only."""
        found = []
        release = self.OS_RELEASE.read_text() if self.OS_RELEASE.exists() else ''
        if os_family(release) != 'arch':
            found.append(f'node {self.node.name}: the local adapter supports Arch-based hosts, and this host is not one.')
        code, out = read(['sudo', '-n', 'true'])
        if code:
            found.append(f'node {self.node.name}: sudo -n does not work for this user ({out}). '
                         f'Run the script of `deploy-k3s bootstrap --target {self.node.name}` once as root.')
        for device in self.node.lvm_physical_volumes:
            if not Path(device).exists():
                found.append(f'node {self.node.name}: the physical volume {device} does not exist.')
        return found

    def steps(self):
        name = self.node.name
        out = [f'host:{name}:prerequisites'] + [f'host:{name}:{s}' for s in self.SCRIPT_STEPS]
        out += [f'host:{name}:stage', f'host:{name}:k3s']
        if self.node.has('public'):
            out.append(f'host:{name}:dns')
        return out

    def root_script(self, step):
        local_bundle(self.ctx, self.node)
        self.ctx.run([*root_command('root-install-local.py'), '--bundle', self.ctx.bundle_name(),
                      '--node', self.node.name, '--only', step], sudo=True)

    def execute(self, step):
        kind = step.rsplit(':', 1)[1]
        if kind == 'prerequisites':
            found = self.problems()
            if found:
                raise StepFailed(' '.join(found))
            return {}
        if kind in self.SCRIPT_STEPS or kind == 'dns':
            self.root_script(kind)
            return {}
        if kind == 'stage':
            folder = staging(self.ctx, self.node.architecture)
            self.ctx.run(['bash', SOURCE / 'hosts/stage-k3s.sh', self.node.architecture, folder])
            tokens(folder)
            return {'staging': str(folder)}
        if kind == 'k3s':
            bundle = local_bundle(self.ctx, self.node, staged=True)
            self.ctx.run([*root_command('root-install-k3s.py'), '--bundle', self.ctx.bundle_name(),
                          '--node', self.node.name, '--kubeconfig'], sudo=True)
            # The root script copies the admin kubeconfig into the bundle. The driver keeps its own copy.
            self.ctx.kubeconfig.parent.mkdir(parents=True, exist_ok=True)
            private_write(self.ctx.kubeconfig, (bundle / 'kubeconfig').read_text())
            (bundle / 'kubeconfig').unlink()
            return {}
        raise StepFailed(f'the local adapter has no step {kind}')

    def service(self, action):
        """Start or stop the units of the site with root-install-local.py --service, the only root command of the rule."""
        local_bundle(self.ctx, self.node)
        self.ctx.run([*root_command('root-install-local.py'), '--bundle', self.ctx.bundle_name(), '--node',
                      self.node.name, '--service', action], sudo=True, capture=True)

    def stop(self):
        self.service('stop')

    def start(self):
        self.service('start')


class Remote:
    """A node with dnf or apt. The driver reaches it with its user shell and runs the root scripts through a root route."""
    kind = 'remote'
    STEPS = ('probe', 'bundle', 'stage', 'root', 'verify')

    def __init__(self, ctx, node):
        self.ctx, self.node = ctx, node
        self.shell = hostroute.Shell(node)

    def ssh(self, command, timeout=40):
        return self.shell.run(command, timeout=timeout)

    def probe(self):
        """The OS family of the node and its root routes. Raise StepFailed with the SSH error when the node does not answer."""
        code, out = self.ssh('cat /etc/os-release; echo ==; uname -m; echo ==; sudo -n true 2>/dev/null && echo sudo-ok; '
                             f'sudo -n -l {hostroute.LIBEXEC}/root-install-k3s.py >/dev/null 2>&1 && echo scoped-ok; '
                             'echo "home=$HOME"')
        if code:
            raise StepFailed(f'node {self.node.name}: SSH to {self.node.ssh_address} failed with exit code {code}: '
                             f'{(out.splitlines() or ["no output"])[-1]}')
        release, machine, rights = (out.split('==') + ['', ''])[:3]
        family = os_family(release)
        if family not in ('rhel', 'debian'):
            raise StepFailed(f'node {self.node.name}: the remote adapter supports dnf and apt hosts. '
                             f'This host has the family {family}.')
        expected = {'amd64': 'x86_64', 'arm64': 'aarch64'}[self.node.architecture]
        if machine.strip() != expected:
            raise StepFailed(f'node {self.node.name}: the site file names {self.node.architecture}, '
                             f'and the host is {machine.strip()}.')
        home = (re.search(r'(?m)^home=(\S+)', rights) or [None, ''])[1]
        return {'family': family, 'sudo': 'sudo-ok' in rights, 'scoped_sudo': 'scoped-ok' in rights,
                'ready': node_ready(self.ctx, self.node.name), 'home': home}

    def steps(self):
        return [f'host:{self.node.name}:{s}' for s in self.STEPS]

    def bundle_path(self):
        return f'k3s-install/{self.ctx.record["revision"][:12]}'

    def prune_bundles(self):
        """Remove the bundles of ~/k3s-install that kept_revisions does not name. Each bundle holds about 1.4 GB."""
        keep = ' '.join(sorted(r[:12] for r in kept_revisions(self.ctx)))
        script = (f'cd ~/k3s-install 2>/dev/null || exit 0; for d in *; do case " {keep} " in *" $d "*) continue;; esac; '
                  'if [ -d "$d" ] && echo "$d" | grep -qxE "[0-9a-f]{12}"; then rm -rf -- "$d" && echo "$d"; fi; done; true')
        code, out = self.ssh(script, timeout=300)
        if code:
            raise StepFailed(f'node {self.node.name}: the removal of earlier bundles failed: {out[-300:]}')
        return out.split()

    def route(self):
        """The root route of the node: sudo, scoped (the bootstrap rule), cluster, or none."""
        found = self.probe()
        if found['sudo']:
            return 'sudo'
        if found['scoped_sudo']:
            return 'scoped'
        if found['ready'] and self.ctx.kubeconfig.exists():
            return 'cluster'
        return 'none'

    def root_commands(self):
        """The root commands of the node, as argv lists that read the bundle in the home folder of the operator user."""
        names = ['--bundle', self.ctx.record['revision'][:12], '--node', self.node.name, '--operator',
                 self.ctx.site.operator_user or 'operator']
        out = [[f'{hostroute.LIBEXEC}/root-install.py', *names, '--only', step]
               for step in host_steps(self.node, self.ctx.site)]
        k3s = [f'{hostroute.LIBEXEC}/root-install-k3s.py', *names]
        if self.node.name == self.ctx.site.control_plane:
            # A server that still runs SQLite converts to etcd only after a verified copy outside its datastore.
            k3s += ['--convert-sqlite']
        return out + [k3s]

    def execute(self, step):
        kind = step.rsplit(':', 1)[1]
        if kind == 'probe':
            found = self.probe()
            self.ctx.record.setdefault('families', {})[self.node.name] = found['family']
            self.ctx.record.setdefault('homes', {})[self.node.name] = found['home']
            return found
        if kind == 'bundle':
            removed = self.prune_bundles()
            folder = write_remote_scripts(self.ctx, self.node, self.ctx.record['revision'])
            self.shell.send_tree(folder, self.bundle_path())
            return {'bundle': str(folder), 'node_folder': f'~/{self.bundle_path()}', 'files': bundle_digests(folder),
                    'removed_bundles': removed}
        if kind == 'stage':
            code, out = self.ssh(f'cd ~/{self.bundle_path()} && bash ./stage-k3s.sh {self.node.architecture} .', timeout=1800)
            if code:
                raise StepFailed(f'node {self.node.name}: stage-k3s.sh failed: {out[-300:]}')
            return {}
        if kind == 'root':
            return self.root_step()
        if kind == 'verify':
            return self.verify()
        raise StepFailed(f'the remote adapter has no step {kind}')

    def root_step(self):
        route = self.route()
        if self.node.name == self.ctx.site.control_plane and 'etcd_before' not in self.ctx.record:
            # verify() compares the etcd role after the step with this value, to find a conversion from SQLite.
            self.ctx.record['etcd_before'] = (node_label(self.ctx, self.node.name, 'node-role.kubernetes.io/etcd')
                                              if node_ready(self.ctx, self.node.name) else 'absent')
            self.ctx.records.save(self.ctx.record)
        folder = remote_folder(self.ctx, self.node, self.ctx.record['revision'])
        scripts = [(f'{hostroute.LIBEXEC}/{name}', (folder / name).read_bytes()) for name in REMOTE_SCRIPTS]
        commands = self.root_commands()
        if route in ('sudo', 'scoped'):
            if route == 'sudo':
                for path, _ in scripts:
                    code, out = self.ssh(f'sudo -n install -D -m 0755 -o root -g root ~/{self.bundle_path()}/'
                                         f'{Path(path).name} {path}')
                    if code:
                        raise StepFailed(f'node {self.node.name}: the install of {path} failed: {out[-300:]}')
            else:
                stale = self.stale_scripts(folder)
                if stale:
                    raise StepWaiting(f'node {self.node.name}: the installed root scripts {", ".join(stale)} differ from '
                                      f'the bundle. Run sudo sh ~/{self.bundle_path()}/bootstrap.sh on the node once, '
                                      f'then run deploy-k3s up --resume {self.ctx.record["id"]}.')
            for argv in commands:
                code, out = self.ssh('sudo -n ' + ' '.join(shlex.quote(a) for a in argv), timeout=7200)
                if code:
                    raise StepFailed(f'node {self.node.name}: {Path(argv[0]).name} failed: {out[-500:]}')
            return {'route': route}
        if route == 'cluster':
            root = hostroute.ClusterRoot(self.ctx.kubeconfig, self.shell)
            unit = f'hoover4-{self.ctx.record["id"].replace("T", "-")}-{self.node.name}'
            script = ' && '.join(' '.join(shlex.quote(a) for a in argv) for argv in commands)
            root.start(unit, scripts, ['/bin/sh', '-c', script])
            try:
                tail = root.wait(unit)
            except hostroute.RouteError as error:
                raise StepFailed(str(error))
            return {'route': route, 'unit': unit, 'log': tail.splitlines()[-3:]}
        raise StepWaiting(f'node {self.node.name}: no root route. Review ~/{self.bundle_path()}/bootstrap.sh on the node, '
                          f'run sudo sh ~/{self.bundle_path()}/bootstrap.sh once, then run deploy-k3s up --resume '
                          f'{self.ctx.record["id"]}.')

    def stale_scripts(self, folder):
        report = self.report(folder)
        installed = report.get('scripts', {})
        return [name for name in REMOTE_SCRIPTS
                if installed.get(name) != file_digest(folder / name)]

    def report(self, folder=None):
        """The installed state of the node from root-install-k3s.py --report of the bundle, as the operator user."""
        code, out = self.ssh(f'python3 ~/{self.bundle_path()}/root-install-k3s.py --report --bundle '
                             f'{shlex.quote(self.bundle_path().rsplit("/", 1)[1])} --node {shlex.quote(self.node.name)}',
                             timeout=120)
        if code:
            raise StepFailed(f'node {self.node.name}: the report failed: {out[-300:]}')
        return json.loads(out.strip().splitlines()[-1])

    def verify(self):
        folder = remote_folder(self.ctx, self.node, self.ctx.record['revision'])
        found = self.report(folder)
        problems = []
        for name in REMOTE_SCRIPTS:
            if found['scripts'].get(name) != file_digest(folder / name):
                problems.append(f'{hostroute.LIBEXEC}/{name} differs from the bundle')
        if K3S_VERSION not in found['k3s_version']:
            problems.append(f'k3s is {found["k3s_version"] or "missing"}, not {K3S_VERSION}')
        unit = 'k3s' if self.node.name == self.ctx.site.control_plane else 'k3s-agent'
        if found['units'].get(unit) != 'active':
            problems.append(f'{unit} is {found["units"].get(unit)}')
        # The k3s configuration is readable by root only. Without a sudo route the report has no configuration, and
        # the arguments that the running k3s recorded on its node show the interface and cluster-init instead.
        args = node_args(self.ctx, self.node.name) if not found.get('config_sha256') else []
        interface = found.get('flannel_iface') or arg_value(args, '--flannel-iface')
        if interface != expected_interface(self.ctx.site, self.node):
            problems.append(f'flannel-iface is {interface!r}, not {expected_interface(self.ctx.site, self.node)!r}')
        if not node_ready(self.ctx, self.node.name):
            problems.append('the node is not Ready')
        if self.node.name == self.ctx.site.control_plane:
            if not found['cluster_init'] and arg_value(args, '--cluster-init') != 'true':
                problems.append('the k3s configuration has no cluster-init')
            etcd = node_label(self.ctx, self.node.name, 'node-role.kubernetes.io/etcd')
            if found['datastore'] not in ('etcd', 'unreadable') or (found['datastore'] == 'unreadable' and etcd != 'true'):
                problems.append(f'the datastore is {found["datastore"]}, and the node has no etcd role')
        if problems:
            raise StepFailed(f'node {self.node.name}: ' + '; '.join(problems) + '.')
        out = {'report': found}
        if (self.node.name == self.ctx.site.control_plane and self.ctx.record.get('etcd_before') == ''
                and node_label(self.ctx, self.node.name, 'node-role.kubernetes.io/etcd') == 'true'):
            out['restarted'] = restart_watchers(self.ctx)
        return out

    def unit(self):
        return 'k3s' if self.node.name == self.ctx.site.control_plane else 'k3s-agent'

    def active(self):
        code, out = self.ssh(f'systemctl is-active {self.unit()}')
        return out.strip() == 'active'

    def service(self, route, action):
        """Start or stop k3s through a root route. The scoped route runs root-install-k3s.py --service of the bundle."""
        if route == 'sudo':
            command = (f'sudo -n systemctl stop {self.unit()} && sudo -n /usr/local/bin/k3s-killall.sh && '
                       f'{{ sudo -n pkill -KILL -f "^/opt/gvisor/"; sudo -n pkill -KILL -f "^runsc-"; true; }}'
                       if action == 'stop' else f'sudo -n systemctl start {self.unit()}')
        else:
            self.execute(f'host:{self.node.name}:bundle')
            command = (f'sudo -n {hostroute.LIBEXEC}/root-install-k3s.py --bundle {self.bundle_path().rsplit("/", 1)[1]} '
                       f'--node {shlex.quote(self.node.name)} --service {action}')
        code, out = self.ssh(command, timeout=600)
        if code:
            raise StepFailed(f'node {self.node.name}: the {action} failed: {out[-300:]}')
        return {'route': route}

    def stop(self):
        """Stop k3s on the node. A node without a root route waits, and a resume finds the stopped unit."""
        if not self.active():
            return {'observed': 'inactive'}
        route = self.route()
        if route in ('sudo', 'scoped'):
            return self.service(route, 'stop')
        if route == 'cluster':
            root = hostroute.ClusterRoot(self.ctx.kubeconfig, self.shell)
            unit = f'hoover4-stop-{self.ctx.record["id"].replace("T", "-")}-{self.node.name}'
            # The kill script ends the pods of the node, so it runs in a unit of the host.
            root.start(unit, (), ['/bin/sh', '-c', f'systemctl stop {self.unit()} && /usr/local/bin/k3s-killall.sh && '
                                  '{ pkill -KILL -f "^/opt/gvisor/"; pkill -KILL -f "^runsc-"; true; }'])
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline and self.active():
                time.sleep(3)
            if self.active():
                raise StepFailed(f'node {self.node.name}: {self.unit()} still runs after the stop.')
            return {'route': route}
        raise StepWaiting(f'node {self.node.name}: run sudo systemctl stop {self.unit()} and '
                          f'sudo /usr/local/bin/k3s-killall.sh on the node, then resume the record.')

    def start(self):
        """Start k3s on the node. A node without a sudo route waits, and a resume finds the active unit."""
        if self.active():
            return {'observed': 'active'}
        found = self.probe()
        if found['sudo'] or found['scoped_sudo']:
            return self.service('sudo' if found['sudo'] else 'scoped', 'start')
        raise StepWaiting(f'node {self.node.name}: run sudo systemctl start {self.unit()} on the node, then resume the record.')


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


LIBEXEC = Path('/usr/local/libexec/hoover4')
ROOT_SCRIPTS = ('root-install-local.py', 'root-install-k3s.py')


def kept_revisions(ctx):
    """The revisions whose exported tree and node bundles stay: the revision of the record, the applied and the previous
    revision, and the revision of each record that waits for a person, for example for the bootstrap of a node."""
    keep = {ctx.record['revision']}
    for record in (ctx.records.applied(), ctx.records.previous()):
        if record:
            keep.add(record['revision'])
    for rid in ctx.records.list():
        record = ctx.records.load(rid)
        if record.get('status') == 'waiting':
            keep.add(record['revision'])
    return keep


def prune_trees(ctx):
    """Remove the exported trees of <private>/build that kept_revisions does not name. Each tree holds about 0.5 GB.

    A new record supersedes the earlier records, so their trees go. A resume of an earlier record then needs a new run.
    """
    import re
    import shutil
    removed = []
    folder = ctx.private / 'build'
    keep = kept_revisions(ctx)
    for tree in sorted(folder.glob('*')) if folder.exists() else []:
        name = tree.name.removesuffix('.partial')
        if tree.is_dir() and re.fullmatch(r'[0-9a-f]{40}', name) and name not in keep:
            shutil.rmtree(tree)
            removed.append(tree.name)
    return removed


def local_bundle(ctx, node, staged=False):
    """Write ~/k3s-install/<bundle>/ of the local node: hosts.json with the private folder, and the staged files.

    The staged files are hard links of the staging folder, or copies on another file system. The root scripts read the
    bundle by its name, so no host path goes into a root command.
    """
    folder = Path.home() / 'k3s-install' / ctx.bundle_name()
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    records_module.write_json(folder / 'hosts.json', config.legacy_hosts(ctx.site, private=ctx.private))
    if staged:
        source = staging(ctx, node.architecture)
        tokens(source)
        for path in sorted(source.iterdir()):
            if not path.is_file():
                continue
            target = folder / path.name
            if target.exists() and target.stat().st_ino == path.stat().st_ino:
                continue
            target.unlink(missing_ok=True)
            try:
                os.link(path, target)
            except OSError:
                import shutil
                shutil.copy2(path, target)
    return folder


def root_command(script):
    """The command of a root script. The reviewed copy of the bootstrap applies when it equals the source."""
    import hashlib
    copy, source = LIBEXEC / script, SOURCE / 'hosts' / script
    if copy.exists() and hashlib.sha256(copy.read_bytes()).digest() == hashlib.sha256(source.read_bytes()).digest():
        return [copy]
    return ['/usr/bin/python3', source]


LOCAL_BOOTSTRAP = """#!/bin/sh
# The reviewed bootstrap of the local node {node}. Run it once as root: sudo sh {path}
# It installs the root scripts of this checkout into {libexec}, and lets the operator user {user} run only these
# scripts with sudo and no password. The scripts accept names only, also for the start and the stop of the site.
set -eu
install -d -m 0755 {libexec}
{installs}
cat > /etc/sudoers.d/90-hoover4 <<'SUDO'
{sudoers}
SUDO
chmod 0440 /etc/sudoers.d/90-hoover4
visudo -cf /etc/sudoers.d/90-hoover4
"""


def write_local_bootstrap(ctx, node):
    path = ctx.private / 'deploy' / 'bootstrap' / f'{node.name}.sh'
    path.parent.mkdir(parents=True, exist_ok=True)
    user = os.environ.get('USER') or ctx.site.operator_user
    installs = '\n'.join(f'install -m 0755 -o root -g root {SOURCE / "hosts" / s} {LIBEXEC / s}' for s in ROOT_SCRIPTS)
    # The rule names only the installed root scripts. The scripts accept names and refuse host paths.
    rules = [f'{user} ALL=(root) NOPASSWD: {LIBEXEC / s} *' for s in ROOT_SCRIPTS]
    path.write_text(LOCAL_BOOTSTRAP.format(node=node.name, path=path, libexec=LIBEXEC, user=user, installs=installs,
                                           sudoers='\n'.join(rules)))
    return path


def adapter(ctx, node):
    # The local adapter prepares the dummy link, the DNS server and the slice of a single-node workstation site. The
    # local node of a site with more nodes is a server host, so it uses the remote adapter with a local shell.
    return LocalArch(ctx, node) if node.local and ctx.site.single else Remote(ctx, node)


def staging(ctx, architecture):
    return ctx.private / 'staging' / architecture


def private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        f.write(text)


def tokens(folder):
    """Copy the server and agent tokens of the site into a staging folder.

    The tokens of a site live in <staging>/tokens/, so the staging folder of every architecture gets the same tokens.
    A token of an earlier staging folder becomes the site token. A new site gets random tokens once. The tokens of an
    existing cluster come from k3s/tools/adopt-cluster.py tokens.
    """
    import secrets
    folder = Path(folder)
    site_folder = folder.parent / 'tokens'
    for name in ('server-token', 'agent-token'):
        site_path, path = site_folder / name, folder / name
        if not site_path.exists():
            private_write(site_path, path.read_text() if path.exists() else secrets.token_hex(32) + '\n')
        if not path.exists() or path.read_text() != site_path.read_text():
            private_write(path, site_path.read_text())


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


# The root scripts of a node bundle, from the hosts folder of the pinned tree.
REMOTE_SCRIPTS = ('root-install.py', 'root-install-k3s.py')
K3S_VERSION = re.search(r'K3S_VERSION = "([^"]+)"', (SOURCE / 'hosts/root-install-k3s.py').read_text()).group(1)

BOOTSTRAP = """#!/bin/sh
# The reviewed bootstrap of node {node}. Run it once as root on the node, from the folder of the bundle:
#   sudo sh bootstrap.sh
# It installs the root scripts of revision {revision} from this folder into {libexec}, and lets the operator user
# {user} run only these scripts with sudo and no password. It adds no other privilege. The SHA-256 of each script
# must match the value below, which the driver wrote.
set -eu
cd "$(dirname "$0")"
install -d -m 0755 {libexec}
{installs}
cat > /etc/sudoers.d/90-hoover4 <<'SUDO'
{sudoers}
SUDO
chmod 0440 /etc/sudoers.d/90-hoover4
visudo -cf /etc/sudoers.d/90-hoover4
"""

README = """Node {node} of site {site}: {family} host, {architecture}, roles {roles}, revision {revision}.

deploy-k3s copies this bundle into ~/{bundle}/ on the node. It holds the root scripts of the revision, hosts.json,
project.json (the part of the site of this node), the stage script and the token file that the node needs.
The token files are private. Do not copy them elsewhere.
The driver runs the root scripts through sudo -n, or through the cluster when the node is Ready. A node without
either route needs this bootstrap once:
1. Review bootstrap.sh and compare the SHA-256 values with the scripts of this folder.
2. Run it once as root: sudo sh ~/{bundle}/bootstrap.sh
3. On the control plane, run: deploy-k3s up --resume <record>.
"""


def host_steps(node, site=None):
    """The steps of root-install.py for a node. A GPU node keeps its VPN as it is, so it gets no wireguard step."""
    steps = ['software', 'settings'] if node.has('gpu') else ['software', 'settings', 'storage']
    if node.vpn_address and not node.has('gpu'):
        steps = ['wireguard'] + steps
    if site and site.backup.get('node') == node.name:
        steps.append('backup')
    return steps


def expected_interface(site, node):
    return 'hoover4' if site.single and node.local else node.vpn_interface


def file_digest(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bundle_digests(folder):
    """{file: SHA-256} of the files of a bundle that hold no secret."""
    return {p.name: file_digest(p) for p in sorted(Path(folder).iterdir()) if p.is_file() and not p.name.endswith('-token')}


def remote_folder(ctx, node, revision):
    return ctx.private / 'deploy' / 'remote' / node.name / revision[:12]


def write_remote_scripts(ctx, node, revision):
    """Write the complete bundle of a node for one revision and return its folder."""
    folder = remote_folder(ctx, node, revision)
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    user = ctx.site.operator_user or 'operator'
    family = (ctx.record or {}).get('families', {}).get(node.name, 'unknown')
    for name in REMOTE_SCRIPTS:
        (folder / name).write_bytes((SOURCE / 'hosts' / name).read_bytes())
        (folder / name).chmod(0o755)
    (folder / 'stage-k3s.sh').write_bytes((SOURCE / 'hosts/stage-k3s.sh').read_bytes())
    installs = '\n'.join(f'echo "{file_digest(folder / s)}  {s}" | sha256sum -c -\n'
                         f'install -m 0755 -o root -g root {s} {hostroute.LIBEXEC}/{s}' for s in REMOTE_SCRIPTS)
    sudoers = '\n'.join(f'{user} ALL=(root) NOPASSWD: {hostroute.LIBEXEC}/{s} *' for s in REMOTE_SCRIPTS)
    files = {
        'bootstrap.sh': BOOTSTRAP.format(node=node.name, revision=revision, user=user, installs=installs,
                                         sudoers=sudoers, libexec=hostroute.LIBEXEC),
        'README.txt': README.format(node=node.name, site=ctx.site.name, family=family, architecture=node.architecture,
                                    roles=', '.join(node.roles), revision=revision, bundle=f'k3s-install/{revision[:12]}'),
        'project.json': json.dumps(config.project(ctx.site, node.name), indent=1, default=list) + '\n',
        'hosts.json': json.dumps(config.legacy_hosts(ctx.site), indent=1) + '\n',
    }
    for name, text in files.items():
        (folder / name).write_text(text)
    # The server gets both tokens. An agent gets only the agent token.
    staged = staging(ctx, node.architecture)
    tokens(staged)
    needed = ('server-token', 'agent-token') if node.name == ctx.site.control_plane else ('agent-token',)
    for name in ('server-token', 'agent-token'):
        if name in needed:
            private_write(folder / name, (staged / name).read_text())
        else:
            (folder / name).unlink(missing_ok=True)
    return folder


# ----------------------------------------------------------------------------------------------------------------------
# Cluster steps
# ----------------------------------------------------------------------------------------------------------------------

def tool_paths(ctx):
    return [ctx.private / item['install'][0].rstrip('/') for item in ARTIFACTS['tools']]


def step_tools(ctx):
    """Download the pinned operator tools once, verify their digests and install them into k3s/private."""
    import hashlib
    import shutil
    import tarfile
    arch = ctx.site.nodes[ctx.site.control_plane].architecture
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
    arch = ctx.site.nodes[ctx.site.control_plane].architecture
    ctx.record['images'] = image_references(ctx, architecture=arch)
    return {'images': len(ctx.record['images']), 'architecture': arch}


def gpu_image_names(ctx):
    sys.path.insert(0, str(SOURCE / 'hoover'))
    import compose
    return [f'hoover/hoover-{n}:{ctx.revision[:12]}' for n in compose.GPU_IMAGES]


def gpu_architecture(ctx):
    nodes = [ctx.site.nodes[n] for n in ctx.site.gpu_pool.get('nodes', ())]
    architectures = {n.architecture for n in nodes}
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
    public = ctx.site.with_role('public')[0]
    if not public.local:
        ctx.run(['bash', SOURCE / 'platform/frontend/install-frontend.sh'])
        return {}
    local = LocalArch(ctx, public)
    ctx.run(['bash', SOURCE / 'platform/frontend/install-local-frontend.sh'])
    local.root_script('frontend')
    ctx.run(['bash', SOURCE / 'platform/frontend/install-local-frontend.sh', '--ca'])
    local.root_script('trust')
    return {}


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
    zone = f'{hoover.zone}.{ctx.site.suffix}'
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': 'sign-in-check', 'namespace': hoover.namespace,
                         'labels': {'app.kubernetes.io/name': 'sign-in-check', 'hoover.dev/oidc': 'client'}},
            'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'enableServiceLinks': False,
                     'containers': [{'name': 'check', 'image': hostroute.POD_IMAGE,
                                     'command': ['python3', '-c', SIGN_IN_CHECK, f'https://id.{zone}/realms/opendesk',
                                                 f'https://hoover.{zone}/oauth2/callback'],
                                     'resources': {'limits': {'cpu': '200m', 'memory': '64Mi'}},
                                     'volumeMounts': [{'name': 'secrets', 'mountPath': '/secrets', 'readOnly': True},
                                                      {'name': 'local-ca', 'mountPath': '/ca', 'readOnly': True}]}],
                     'volumes': [{'name': 'secrets', 'secret': {'secretName': 'oauth2-proxy', 'items': [
                                     {'key': 'client-secret', 'path': 'client-secret'}]}},
                                 # Only a single-node site has the local CA of its frontend.
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


def _start_node(a):
    def run(ctx):
        fields = a.start() or {}
        if a.node.name == ctx.site.control_plane:
            wait_api(ctx)
        return fields
    return run


def _stop_node(a):
    def run(ctx):
        return a.stop() or {}
    return run


def _host_step(a, name):
    return lambda ctx: a.execute(name)


def plan(ctx, command, targets, start=False):
    """{step name: function} in order."""
    steps = {}
    nodes = ordered_nodes(ctx.site, targets)
    control = ctx.site.control_plane in targets
    if command == 'up' and start:
        for node in nodes:
            steps[f'start:k3s:{node.name}'] = _start_node(adapter(ctx, node))
        if control:
            for name in START_ORDER:
                steps[name] = start_tier(name.split(':')[1])
        return steps
    if command == 'up':
        for node in nodes:
            a = adapter(ctx, node)
            for name in a.steps():
                steps[name] = _host_step(a, name)
        if control:
            steps.update(cluster_steps(ctx))
        return steps
    if command == 'down':
        if control:
            for name in STOP_ORDER:
                steps[name] = stop_tier(name.split(':')[1])
        for node in reversed(nodes):
            steps[f'stop:k3s:{node.name}'] = _stop_node(adapter(ctx, node))
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
    for prefix in (('host',), ('start', 'k3s'), ('stop', 'k3s')):
        n = len(prefix)
        if tuple(a[:n]) == prefix and tuple(b[:n]) == prefix and len(a) > n and len(b) > n and a[n] != b[n]:
            return True
    return False


def execute(ctx, record, steps):
    """Run the unfinished steps of a record in order. Return the exit code.

    A failed step ends the run. A waiting step blocks every later step that depends on it, and the run continues with
    the independent steps, for example the host steps of the other nodes.
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
            except (StepFailed, hostroute.RouteError, config.SiteError, subprocess.SubprocessError, OSError) as error:
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
    out = {'site': ctx.site.name, 'site_file': str(ctx.site_path), 'revision': revision,
           'checkout_changes': dirty_files(ctx.repo), 'settings': config.legacy_settings(ctx.site),
           'nodes': {t: config.project(ctx.site, t) for t in targets},
           'adapters': {t: adapter(ctx, ctx.site.nodes[t]).kind for t in targets},
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
    """The problems of the selected targets, as messages, and their state, as a dict. Read-only."""
    problems, state = list(config.missing_files(ctx.site)), {}
    for name in targets:
        node = ctx.site.nodes[name]
        a = adapter(ctx, node)
        if isinstance(a, LocalArch):
            problems += a.problems()
            state[name] = {'adapter': a.kind, 'k3s': read(['systemctl', 'is-active', 'k3s.service'])[1],
                           'ready': node_ready(ctx, name)}
        else:
            try:
                state[name] = {'adapter': a.kind, **a.probe(), 'ready': node_ready(ctx, name)}
            except StepFailed as error:
                problems.append(str(error))
                state[name] = {'adapter': a.kind, 'reachable': False}
    if ctx.site.control_plane in targets:
        missing = [str(p) for p in tool_paths(ctx) if not p.exists()]
        if missing:
            problems.append('the operator tools are missing: ' + ', '.join(missing) + '. deploy-k3s up installs them.')
        state['checkout_changes'] = dirty_files(ctx.repo)
        state['applied'] = (ctx.records.applied() or {}).get('revision')
        state['stopped'] = ctx.records.stopped()
    return problems, state
