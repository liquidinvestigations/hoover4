"""The routes of the driver to a node: a user shell, and root through sudo or through the cluster. Standard library only.

User shell. A local node runs the commands in a local shell. A remote node runs them over SSH as the operator user.
Root through sudo. A node whose operator user may run sudo -n, for every command or for the root scripts that the
reviewed bootstrap installed into /usr/local/libexec/hoover4, runs the root scripts with sudo -n.
Root through the cluster. A node that is Ready in the cluster runs a root command as a transient systemd unit of the
host, which a privileged pod with the host PID namespace starts with nsenter, as ../platform/registry/node-registries.py
does. The admin kubeconfig gives that right. The unit keeps running when k3s or the pod stops, so a restart of k3s
does not end the command. The unit writes its output into /var/log/hoover4/<unit>.log, and the driver reads its state
with systemctl show over the user shell. A second call with the same unit name reads the result of the earlier run and
starts nothing.
The pod receives each file that it installs as base64 in an environment value, with its SHA-256. No secret value goes
into a command argument, a pod or a log: a token reaches a node only in the private bundle of the user shell.
"""
import base64
import hashlib
import json
import shlex
import subprocess
import time

SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=accept-new']
POD_IMAGE = 'docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'
LOG_DIR = '/var/log/hoover4'
LIBEXEC = '/usr/local/libexec/hoover4'


class RouteError(RuntimeError):
    """A route failed. The message names the node and the cause."""


def run(argv, input=None, timeout=None):
    try:
        r = subprocess.run([str(a) for a in argv], input=input, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL if input is None else None)
    except FileNotFoundError:
        return 127, f'{argv[0]} is not installed'
    except subprocess.TimeoutExpired:
        return 124, f'{argv[0]} did not answer in {timeout} s'
    return r.returncode, (r.stdout + r.stderr).strip()


class Shell:
    """The user shell of a node: local for the local node, SSH for the others."""

    def __init__(self, node):
        self.node = node

    def command(self, script):
        if self.node.local:
            return ['sh', '-c', script]
        return ['ssh', *SSH_OPTIONS, self.node.ssh_address, '--', script]

    def run(self, script, input=None, timeout=600):
        return run(self.command(script), input=input, timeout=timeout)

    def send_tree(self, folder, destination, timeout=600):
        """Copy a local folder into a private folder of the node, through tar on standard input."""
        pack = subprocess.Popen(['tar', '-C', str(folder), '-cf', '-', '.'], stdout=subprocess.PIPE)
        script = f'umask 077 && mkdir -p {shlex.quote(destination)} && tar -C {shlex.quote(destination)} -xf -'
        r = subprocess.run(self.command(script), stdin=pack.stdout, capture_output=True, timeout=timeout)
        # tar ends with an error when the node stopped reading, instead of waiting for a reader.
        pack.stdout.close()
        if pack.wait() or r.returncode:
            raise RouteError(f'node {self.node.name}: the copy into {destination} failed: '
                             f'{(r.stderr or b"").decode(errors="replace").strip()[-300:]}')


def unit_state(shell, unit):
    """(state, result, status) of a transient unit, from systemctl show. state is missing for an unknown unit."""
    code, out = shell.run(f'systemctl show {shlex.quote(unit)} -p LoadState -p ActiveState -p Result -p ExecMainStatus',
                          timeout=60)
    if code:
        raise RouteError(f'node {shell.node.name}: systemctl show {unit} failed: {out[-300:]}')
    values = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
    if values.get('LoadState') == 'not-found':
        return 'missing', '', ''
    return values.get('ActiveState', ''), values.get('Result', ''), values.get('ExecMainStatus', '')


def log_tail(shell, unit, lines=20):
    return shell.run(f'tail -n {lines} {LOG_DIR}/{shlex.quote(unit)}.log 2>/dev/null', timeout=60)[1]


def host_script(files, unit, command):
    """The shell script of the pod: install the files, then start the command as a transient unit of the host."""
    lines = ['set -eu', f'install -d -m 0755 {LIBEXEC} {LOG_DIR}']
    for i, (path, _) in enumerate(files):
        lines += [f'printf %s "$F{i}" | base64 -d > {path}.new',
                  f'echo "$S{i}  {path}.new" | sha256sum -c - >/dev/null',
                  f'chmod 0755 {path}.new && chown root:root {path}.new && mv {path}.new {path}']
    if command:
        wrapped = f'exec >{LOG_DIR}/{unit}.log 2>&1; ' + ' '.join(shlex.quote(a) for a in command)
        lines.append(f'systemctl reset-failed {unit} 2>/dev/null || true')
        lines.append('systemd-run --quiet --unit=' + unit + ' --property=RemainAfterExit=yes --property=Type=oneshot '
                     '/bin/sh -c ' + shlex.quote(wrapped))
    return '\n'.join(lines)


def cluster_pod(node, unit, files, command):
    """The privileged pod that installs files on a node and starts a command there."""
    env = []
    for i, (path, content) in enumerate(files):
        env += [{'name': f'F{i}', 'value': base64.b64encode(content).decode()},
                {'name': f'S{i}', 'value': hashlib.sha256(content).hexdigest()}]
    name = ('hoover4-root-' + hashlib.sha256(unit.encode()).hexdigest()[:10])
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': 'kube-system',
                                                            'labels': {'app.kubernetes.io/name': 'hoover4-root'}},
            'spec': {'nodeName': node, 'hostPID': True, 'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                     'tolerations': [{'operator': 'Exists'}],
                     'containers': [{'name': 'host', 'image': POD_IMAGE, 'securityContext': {'privileged': True},
                                     'env': env, 'resources': {'limits': {'memory': '64Mi'}},
                                     'command': ['nsenter', '-t', '1', '-m', '-u', '-i', '-n', '-p', '--', 'sh', '-c',
                                                 host_script(files, unit, command)]}]}}


class ClusterRoot:
    """Root on a Ready node through a privileged pod and a transient unit of the host."""

    def __init__(self, kubeconfig, shell):
        self.kubeconfig, self.shell = kubeconfig, shell

    def kubectl(self, *args, input=None):
        return run(['kubectl', '--kubeconfig', self.kubeconfig, *args], input=input, timeout=120)

    def start(self, unit, files=(), command=None, timeout=300):
        """Install files and start the command as a unit. A unit that exists already starts nothing."""
        if command and unit_state(self.shell, unit)[0] != 'missing':
            return
        pod = cluster_pod(self.shell.node.name, unit, list(files), command)
        name = pod['metadata']['name']
        self.kubectl('-n', 'kube-system', 'delete', 'pod', name, '--ignore-not-found', '--wait=true')
        code, out = self.kubectl('apply', '-f', '-', input=json.dumps(pod))
        if code:
            raise RouteError(f'node {self.shell.node.name}: the root pod was refused: {out[-300:]}')
        deadline = time.monotonic() + timeout
        phase = ''
        while time.monotonic() < deadline:
            phase = self.kubectl('-n', 'kube-system', 'get', 'pod', name, '-o', 'jsonpath={.status.phase}')[1]
            if phase in ('Succeeded', 'Failed'):
                break
            time.sleep(2)
        logs = self.kubectl('-n', 'kube-system', 'logs', name)[1]
        self.kubectl('-n', 'kube-system', 'delete', 'pod', name, '--wait=false')
        if phase != 'Succeeded':
            raise RouteError(f'node {self.shell.node.name}: the root pod ended in phase {phase or "unknown"}: {logs[-300:]}')

    def wait(self, unit, timeout=3600, poll=5):
        """Wait for a unit to end. Return its log tail. Raise RouteError when it failed."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                state, result, status = unit_state(self.shell, unit)
            except RouteError:
                # The node can be busy while k3s restarts. The unit runs on.
                time.sleep(poll)
                continue
            if state == 'failed' or (state in ('active', 'inactive') and result not in ('', 'success')):
                raise RouteError(f'node {self.shell.node.name}: {unit} failed ({result}, exit {status}): '
                                 + log_tail(self.shell, unit)[-500:])
            if state == 'active' and result == 'success' and status == '0':
                return log_tail(self.shell, unit)
            if state == 'missing':
                raise RouteError(f'node {self.shell.node.name}: {unit} does not exist')
            time.sleep(poll)
        raise RouteError(f'node {self.shell.node.name}: {unit} did not end in {timeout} s')
