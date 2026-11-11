"""The deployment driver of ../deploy-k3s. Standard library only.

The driver reads the site file (../config.py) and runs the host scripts of ../hosts/, the cluster scripts of
../cluster/ and ../platform/, and the zone installer of ../zones/ in their order. records.py keeps the state of each
run on the control-plane host.

Host adapters:
  local-arch      the local node on an Arch-based distribution. The driver runs the root scripts with sudo -n.
  remote          a remote node with dnf or apt. The driver checks a remote node over SSH with read-only commands, and
                  writes its bootstrap script, its installation script and the instructions into
                  k3s/private/deploy/remote/<node>/. The operator runs them on the node. The step waits until the
                  node is Ready in the cluster.
The driver changes no remote host. render and check change no host and no cluster.
"""
import json
import os
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
        self.record = None
        self.shell = Shell()

    def env(self):
        env = {'KUBECONFIG': str(self.kubeconfig), 'HOOVER4_SITE': str(self.site_path), 'HELM': str(self.private / 'bin/helm'),
               'PATH': f"{self.private / 'bin'}:{os.environ.get('PATH', '')}"}
        if self.revision:
            env['HOOVER4_REVISION'] = self.revision
        return env

    def run(self, argv, **kw):
        kw['env'] = dict(self.env(), **(kw.get('env') or {}))
        return self.shell.run(argv, **kw)

    def kubectl(self, *args, check=True):
        return self.run(['kubectl', '--kubeconfig', self.kubeconfig, *args], capture=True, check=check)[1]

    def hosts_file(self):
        """The hosts.json form of the site, in a private file for the root scripts."""
        path = self.private / 'deploy' / 'hosts.json'
        records_module.write_json(path, config.legacy_hosts(self.site))
        return path


def resolve_revision(repo, ref):
    code, out = read(['git', '-C', repo, 'rev-parse', '--verify', f'{ref}^{{commit}}'])
    if code:
        raise StepFailed(f'{ref} is not a commit of {repo}: {out}')
    return out.strip()


def dirty_files(repo):
    """The changed files of the checkout. The driver never resets them."""
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
        self.ctx.run([*root_command('root-install-local.py'), '--hosts', self.ctx.hosts_file(),
                      '--node', self.node.name, '--private', self.ctx.private, '--operator', os.environ.get('USER', ''),
                      '--only', step], sudo=True)

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
            folder = staging(self.ctx, self.node.architecture)
            self.ctx.run([*root_command('root-install-k3s.py'), '--hosts', self.ctx.hosts_file(),
                          '--node', self.node.name, '--staged', folder, '--kubeconfig-out', self.ctx.kubeconfig], sudo=True)
            return {}
        raise StepFailed(f'the local adapter has no step {kind}')

    def stop(self):
        for unit in ('hoover4-frontend.service', 'k3s.service'):
            self.ctx.run(['/usr/bin/systemctl', 'stop', unit], sudo=True)
        # The containers of the pods keep running after the k3s unit stops. The kill script of k3s stops them.
        self.ctx.run(['/usr/local/bin/k3s-killall.sh'], sudo=True, capture=True)

    def start(self):
        # The pods reach the zone names through the frontend, so it starts with k3s.
        for unit in ('hoover4-address.service', 'hoover4-dns.service', 'k3s.service', 'hoover4-frontend.service'):
            self.ctx.run(['/usr/bin/systemctl', 'start', unit], sudo=True)


class Remote:
    """A remote node. The driver checks it over SSH with read-only commands and writes its scripts."""
    kind = 'remote'

    def __init__(self, ctx, node):
        self.ctx, self.node = ctx, node

    def ssh(self, command, timeout=40):
        return read(['ssh', *SSH_OPTIONS, self.node.ssh_address, '--', command], timeout=timeout)

    def probe(self):
        """The OS family of the node. Raise StepFailed with the SSH error when the node does not answer."""
        code, out = self.ssh('cat /etc/os-release; echo ==; uname -m; echo ==; sudo -n true && echo sudo-ok')
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
        return {'family': family, 'sudo': 'sudo-ok' in rights}

    def steps(self):
        return [f'host:{self.node.name}:probe', f'host:{self.node.name}:scripts']

    def execute(self, step):
        kind = step.rsplit(':', 1)[1]
        if kind == 'probe':
            found = self.probe()
            self.ctx.record.setdefault('families', {})[self.node.name] = found['family']
            return found
        if kind == 'scripts':
            folder = write_remote_scripts(self.ctx, self.node, self.ctx.record['revision'])
            if node_ready(self.ctx, self.node.name):
                return {'scripts': str(folder)}
            raise StepWaiting(f'node {self.node.name}: run the scripts in {folder} on the node as README.txt says, '
                              f'then run deploy-k3s up --resume {self.ctx.record["id"]}.')
        raise StepFailed(f'the remote adapter has no step {kind}')

    def stop(self):
        raise StepWaiting(f'node {self.node.name}: run sudo systemctl stop k3s-agent k3s and '
                          f'sudo /usr/local/bin/k3s-killall.sh on the node.')

    def start(self):
        raise StepWaiting(f'node {self.node.name}: run sudo systemctl start k3s-agent or k3s on the node.')


LIBEXEC = Path('/usr/local/libexec/hoover4')
ROOT_SCRIPTS = ('root-install-local.py', 'root-install-k3s.py')
LOCAL_UNITS = 'hoover4-address.service hoover4-dns.service hoover4-frontend.service k3s.service'


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
# scripts, the start and stop of the units of the site and the kill script of k3s with sudo and no password.
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
    rules = [f'{user} ALL=(root) NOPASSWD: {LIBEXEC / s} *' for s in ROOT_SCRIPTS]
    rules += [f'{user} ALL=(root) NOPASSWD: /usr/bin/systemctl {verb} {unit}' for verb in ('start', 'stop')
              for unit in LOCAL_UNITS.split()]
    rules.append(f'{user} ALL=(root) NOPASSWD: /usr/local/bin/k3s-killall.sh')
    path.write_text(LOCAL_BOOTSTRAP.format(node=node.name, path=path, libexec=LIBEXEC, user=user, installs=installs,
                                           sudoers='\n'.join(rules)))
    return path


def adapter(ctx, node):
    return LocalArch(ctx, node) if node.local else Remote(ctx, node)


def staging(ctx, architecture):
    return ctx.private / 'staging' / architecture


def tokens(folder):
    """The server and agent tokens of the cluster, made once."""
    import secrets
    for name in ('server-token', 'agent-token'):
        path = Path(folder) / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600), 'w') as f:
                f.write(secrets.token_hex(32) + '\n')


def node_ready(ctx, name):
    if not ctx.kubeconfig.exists():
        return False
    code, out = read(['kubectl', '--kubeconfig', ctx.kubeconfig, 'get', 'node', name, '--no-headers'])
    return code == 0 and ' Ready ' in f' {out} '


BOOTSTRAP = """#!/bin/sh
# The reviewed bootstrap of node {node}. Run it once as root on the node: sh bootstrap.sh <checkout>
# It installs the root scripts of revision {revision} from the checkout into /usr/local/libexec/hoover4, and lets the
# operator user {user} run only these scripts with sudo and no password. It adds no other privilege.
set -eu
checkout=${{1:?the path of the hoover4 checkout}}
install -d -m 0755 /usr/local/libexec/hoover4
{installs}
cat > /etc/sudoers.d/90-hoover4 <<'SUDO'
{sudoers}
SUDO
chmod 0440 /etc/sudoers.d/90-hoover4
visudo -cf /etc/sudoers.d/90-hoover4
"""

INSTALL = """#!/bin/sh
# Install or update node {node} ({family}, {architecture}) at revision {revision}. Run it as the operator user {user}.
set -eu
checkout=${{HOOVER4_CHECKOUT:-$HOME/hoover4}}
[ -d "$checkout/.git" ] || git clone {remote} "$checkout"
cd "$checkout"
# A checkout with local changes stays unchanged. The script stops and names the changed files.
if [ -n "$(git status --porcelain)" ]; then
  echo "the checkout $checkout has local changes. Commit or move them, then run this script again:" >&2
  git status --porcelain >&2
  exit 3
fi
git fetch --quiet origin
git -c advice.detachedHead=false checkout --quiet {revision}
bash k3s/hosts/stage-k3s.sh {architecture} "$HOME/k3s-install"
for step in {host_steps}; do
  sudo -n /usr/local/libexec/hoover4/root-install.py --hosts "$HOME/k3s-install/hosts.json" --node {node} --only "$step"
done
sudo -n /usr/local/libexec/hoover4/root-install-k3s.py --hosts "$HOME/k3s-install/hosts.json" --node {node} --staged "$HOME/k3s-install"
"""

README = """Node {node} of site {site}: {family} host, {architecture}, roles {roles}, revision {revision}.

1. Review bootstrap.sh. Clone the repository on the node, then run the script once as root:
   sudo sh bootstrap.sh <checkout>
2. Copy hosts.json, server-token and agent-token from k3s/private/staging/{architecture}/ of the control plane to
   ~/k3s-install/ on the node. project.json in this folder shows the part of the site that the node receives.
3. Run install.sh on the node as {user}. It stops and names the files when the checkout has local changes.
4. On the control plane, run: deploy-k3s up --resume <record>. The step finishes when the node is Ready.
"""


def write_remote_scripts(ctx, node, revision):
    folder = ctx.private / 'deploy' / 'remote' / node.name
    folder.mkdir(parents=True, exist_ok=True)
    user = ctx.site.operator_user or 'operator'
    family = (ctx.record or {}).get('families', {}).get(node.name, 'unknown')
    scripts = ['root-install.py', 'root-install-k3s.py']
    installs = '\n'.join(f'install -m 0755 -o root -g root "$checkout/k3s/hosts/{s}" /usr/local/libexec/hoover4/{s}'
                         for s in scripts)
    sudoers = '\n'.join(f'{user} ALL=(root) NOPASSWD: /usr/local/libexec/hoover4/{s} *' for s in scripts)
    host_steps = 'software settings' if node.has('gpu') else 'software settings storage'
    if node.vpn_address and not node.has('gpu'):
        host_steps = 'wireguard ' + host_steps
    remote_url = read(['git', '-C', ctx.repo, 'remote', 'get-url', 'origin'])[1] or \
        'https://github.com/liquidinvestigations/hoover4'
    files = {
        'bootstrap.sh': BOOTSTRAP.format(node=node.name, revision=revision, user=user, installs=installs, sudoers=sudoers),
        'install.sh': INSTALL.format(node=node.name, family=family, architecture=node.architecture, revision=revision,
                                     user=user, remote=remote_url, host_steps=host_steps),
        'README.txt': README.format(node=node.name, site=ctx.site.name, family=family, architecture=node.architecture,
                                    roles=', '.join(node.roles), revision=revision, user=user),
        'project.json': json.dumps(config.project(ctx.site, node.name), indent=1, default=list) + '\n',
    }
    for name, text in files.items():
        (folder / name).write_text(text)
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


def image_references(ctx):
    """The images that the deployment uses, with the digest of each image in the registry."""
    endpoint = config.legacy_settings(ctx.site)['registry_endpoint']
    out = {}
    for name in image_names(ctx):
        repo, image_tag = name.rsplit(':', 1)
        request = urllib.request.Request(f'http://{endpoint}/v2/{repo}/manifests/{image_tag}', method='HEAD', headers={
            'Accept': 'application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,'
                      'application/vnd.docker.distribution.manifest.v2+json'})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                out[f'registry.hoover.internal/{name}'] = response.headers.get('Docker-Content-Digest', '')
        except OSError as error:
            raise StepFailed(f'the registry {endpoint} has no image {name}: {error}')
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
    ctx.record['images'] = image_references(ctx)
    return {'images': len(ctx.record['images'])}


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


def step_zone(zone, home):
    def run(ctx):
        ctx.run([sys.executable, SOURCE / 'zones/zone.py', 'apply', zone, '--home', home])
        return {}
    return run


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
        'ingress': step_script('bash', '@platform/ingress/install-ingress.sh'),
        'frontend': step_frontend,
        'monitoring': step_script('bash', '@platform/monitoring/install-dashboards.sh'),
        'operator': step_operator,
        'hoover-data': step_script(sys.executable, '@platform/hoover-data/install-hoover-data.py'),
        'gpu-proxy': step_script(sys.executable, '@hoover/gpu.py', 'install'),
    }
    if ctx.site.single:
        # The Hoover pods of a single-node site share one node, so their dataset folders are claims and need no NFS.
        del steps['hoover-data']
    for hoover in ctx.site.hoovers.values():
        steps[f'zone:{hoover.zone}'] = step_zone(hoover.zone, hoover.home_node)
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
            if tier(namespace, name) == group:
                ctx.kubectl('-n', namespace, 'scale', kind, name, f'--replicas={replicas}')
                started.append((namespace, kind, name))
        for namespace, kind, name in started:
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
        a.start()
        if a.node.name == ctx.site.control_plane:
            wait_api(ctx)
        return {}
    return run


def _stop_node(a):
    def run(ctx):
        a.stop()
        return {}
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

def execute(ctx, record, steps):
    """Run the unfinished steps of a record in order. Return the exit code."""
    ctx.record = record
    ctx.revision = record['revision']
    ctx.shell = Shell(ctx.records.folder / 'logs' / f'{record["id"]}.log')

    def on_signal(number, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, on_signal)
    waiting = []
    record['status'] = 'running'
    record['error'] = ''
    ctx.records.save(record)
    try:
        for entry in record['steps']:
            name = entry['name']
            if entry['state'] == 'done':
                continue
            ctx.records.mark(record, name, 'running')
            print(json.dumps({'at': time.strftime('%H:%M:%S'), 'record': record['id'], 'step': name}), flush=True)
            try:
                fields = steps[name](ctx) or {}
            except StepWaiting as wait:
                ctx.records.mark(record, name, 'waiting', message=str(wait))
                waiting.append(str(wait))
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
            ctx.records.mark(record, name, 'done', **fields)
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
        record['status'] = 'waiting'
        record['error'] = ' '.join(waiting)
        ctx.records.save(record)
        print('deploy-k3s: the deployment is not complete. ' + ' '.join(waiting), file=sys.stderr)
        return 3
    if record['command'] == 'up' and record.get('complete'):
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


def render(ctx, targets, revision, manifests=False):
    """The configuration of the selected targets, as a dict. It reads files and the cluster, and changes nothing."""
    out = {'site': ctx.site.name, 'site_file': str(ctx.site_path), 'revision': revision,
           'checkout_changes': dirty_files(ctx.repo), 'settings': config.legacy_settings(ctx.site),
           'nodes': {t: config.project(ctx.site, t) for t in targets},
           'adapters': {t: adapter(ctx, ctx.site.nodes[t]).kind for t in targets},
           'up': list(plan(ctx, 'up', targets)), 'start': list(plan(ctx, 'up', targets, start=True)),
           'down': list(plan(ctx, 'down', targets)),
           'applied': (ctx.records.applied() or {}).get('revision'), 'operator_settings': {}}
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
