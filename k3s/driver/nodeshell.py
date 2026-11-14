"""The user shell of a node for the tools that read or copy files on a node. Standard library only.

A local node runs the commands in a local shell. A remote node runs them over SSH with the SSH configuration of the
current user, as `ssh <node name>` or `ssh <ssh_host>` (../config.py ssh_host()). A root command runs with sudo -n, so it needs sudo without a password for that user.
The host steps of a deployment use Ansible instead (../ansible).
"""
import shlex
import subprocess
import time
from pathlib import Path

SSH_OPTIONS = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '-o', 'StrictHostKeyChecking=accept-new']
# sshd drops new connections before authentication when it holds MaxStartups unauthenticated ones, for example while
# a public host gets login attempts from the internet. ssh then exits with 255 and one of these texts, and the remote
# command did not start, so the call starts again after a pause.
SSH_REFUSED = ('kex_exchange_identification', 'Connection closed by', 'Connection reset by')
SSH_ATTEMPTS = 5
SSH_PAUSE = 6
# The root script of the k3s datastore actions: snapshot, preserve and restore (../ansible/roles/hoover4_k3s).
DATASTORE_SCRIPT = Path(__file__).resolve().parents[1] / 'ansible/roles/hoover4_k3s/files/k3s-datastore.py'


class RouteError(RuntimeError):
    """A command on a node failed. The message names the node and the cause."""


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
            # A remote shell starts in the home folder, and the paths are relative to it. A local one does too.
            return ['sh', '-c', 'cd && ' + script]
        return ['ssh', *SSH_OPTIONS, self.node.ssh_host or self.node.name, '--', script]

    def run(self, script, input=None, timeout=600):
        for attempt in range(SSH_ATTEMPTS):
            code, out = run(self.command(script), input=input, timeout=timeout)
            if not refused_before_start(self.node, code, out) or attempt == SSH_ATTEMPTS - 1:
                return code, out
            time.sleep(SSH_PAUSE)

    def datastore(self, *args, timeout=3600):
        """Run the k3s datastore script as root with sudo -n. The script goes to Python on standard input."""
        command = 'sudo -n python3 - ' + ' '.join(shlex.quote(a) for a in args)
        return self.run(command, input=DATASTORE_SCRIPT.read_text(), timeout=timeout)

    def send_tree(self, folder, destination, timeout=600):
        """Copy a local folder into a private folder of the node, through tar on standard input."""
        script = f'umask 077 && mkdir -p {shlex.quote(destination)} && tar -C {shlex.quote(destination)} -xf -'
        for attempt in range(SSH_ATTEMPTS):
            pack = subprocess.Popen(['tar', '-C', str(folder), '-cf', '-', '.'], stdout=subprocess.PIPE)
            r = subprocess.run(self.command(script), stdin=pack.stdout, capture_output=True, timeout=timeout)
            # tar ends with an error when the node stopped reading, instead of waiting for a reader.
            pack.stdout.close()
            packed = pack.wait()
            out = (r.stderr or b'').decode(errors='replace')
            if not refused_before_start(self.node, r.returncode, out) or attempt == SSH_ATTEMPTS - 1:
                break
            time.sleep(SSH_PAUSE)
        if packed or r.returncode:
            raise RouteError(f'node {self.node.name}: the copy into {destination} failed: '
                             f'{(r.stderr or b"").decode(errors="replace").strip()[-300:]}')


def refused_before_start(node, code, out):
    """True when ssh to a remote node ended before the remote command started."""
    return not node.local and code == 255 and any(text in out for text in SSH_REFUSED)
