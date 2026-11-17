#!/usr/bin/env python3
"""The datastore actions of a k3s server of a hoover4 site. Run it as root on the server.

The role hoover4_k3s runs it with the script module. The steps that ../../../../tools/local-retirement.py and
../../../../platform/backups/backups.py print run it on the server with `sudo python3 - <command> < k3s-datastore.py`.
Arguments are names. No argument holds a host path. The snapshot folders are ~<user>/hoover4-snapshots/<name> of the
user that runs sudo (SUDO_USER). The script refuses a name with '/', a name that starts with '.', and a symbolic link
in that path.

Commands:
  datastore            Print the datastore of the server folder: etcd, sqlite or none.
  verify-etcd          Verify that the running server uses etcd: the member folder exists and a snapshot save succeeds.
  preserve-sqlite      Stop k3s and copy the SQLite datastore, the token and the configuration into a new folder below
                       /var/lib/hoover4-recovery with SHA256SUMS. The copy is read again. k3s stays stopped.
  preserve NAME        Stop k3s and copy the datastore (SQLite or etcd), the token and the configuration into a new
                       folder below the snapshot folder NAME, for the retirement of a server. k3s stays stopped.
  restore NAME         On a stopped server, restore the etcd snapshot of the snapshot folder NAME (k3s --cluster-reset)
                       with its token, then start k3s. Use it on an isolated server. The folder holds the folder etcd/
                       of a platform copy: host.json names the snapshot file, and token is the token of the server.
The script runs with Python 3.9, the version of RHEL 9.
"""
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import time

K3S_DIR = '/etc/rancher/k3s'
SERVER_DIR = '/var/lib/rancher/k3s/server'
DB_DIR = SERVER_DIR + '/db'
RECOVERY_DIR = '/var/lib/hoover4-recovery'
SNAPSHOTS = 'hoover4-snapshots'
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')


def say(text=''):
    print(text, flush=True)


def fail(text):
    say(f'ERROR: {text}')
    sys.exit(1)


def run(cmd, check=True):
    say('  $ ' + ' '.join(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout.splitlines():
        say('    ' + line)
    if check and proc.returncode != 0:
        fail(f'{cmd[0]} exited with code {proc.returncode}')
    return proc.stdout


def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def name_arg(value, what='name'):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        fail(f"the {what} {value!r} is not a name. A name has letters, digits, '.', '_' and '-', and no '/'.")
    return value


def operator():
    name = os.environ.get('SUDO_USER', '')
    if not name or name == 'root':
        fail('run the command with sudo as the operator user, so the snapshot folder belongs to that user')
    try:
        return pwd.getpwnam(name_arg(name, 'operator user'))
    except KeyError:
        fail(f'the user {name} does not exist')


def snapshot_folder(user, name):
    """~<user>/hoover4-snapshots/<name>. The script refuses a symbolic link in the path."""
    base = os.path.join(user.pw_dir, SNAPSHOTS)
    for path in (user.pw_dir, base):
        if os.path.islink(path):
            fail(f'{path} is a symbolic link')
    if not os.path.isdir(base):
        os.makedirs(base, mode=0o700)
        os.chown(base, user.pw_uid, user.pw_gid)
    folder = os.path.join(base, name_arg(name, 'snapshot'))
    if os.path.islink(folder):
        fail(f'{folder} is a symbolic link')
    return folder


def owned_by(folder, user):
    for root, dirs, names in os.walk(folder):
        for entry in [root] + [os.path.join(root, n) for n in dirs + names]:
            os.lchown(entry, user.pw_uid, user.pw_gid)


def datastore():
    if os.path.isdir(os.path.join(DB_DIR, 'etcd', 'member')):
        return 'etcd'
    if os.path.exists(os.path.join(DB_DIR, 'state.db')):
        return 'sqlite'
    return 'none'


def require_server():
    if not os.path.exists('/etc/systemd/system/k3s.service'):
        fail('this host runs no k3s server')


def file_rows(folder):
    rows = []
    for root, _, files in os.walk(folder):
        for name in sorted(files):
            path = os.path.join(root, name)
            if os.path.islink(path) or name == 'SHA256SUMS':
                continue
            rows.append(f'{sha(path)}  {os.path.relpath(path, folder)}')
    return sorted(rows)


def preserve(folder, include_etcd=False):
    """Stop k3s and copy the datastore, the token and the configuration into a new folder below folder.

    The copy gets SHA256SUMS and is read again. A failed check stops the script, and k3s stays stopped, so no write
    changes the datastore before a person looks at it.
    """
    target = os.path.join(os.path.abspath(folder), 'k3s-sqlite-' + time.strftime('%Y%m%dT%H%M%S'))
    say(f'  stop k3s and copy its datastore, token and configuration to {target}')
    run(['systemctl', 'stop', 'k3s'])
    os.makedirs(target, mode=0o700)
    os.chmod(target, 0o700)
    for name in ('state.db', 'state.db-wal', 'state.db-shm'):
        path = os.path.join(DB_DIR, name)
        if os.path.exists(path):
            os.makedirs(os.path.join(target, 'db'), mode=0o700, exist_ok=True)
            shutil.copy2(path, os.path.join(target, 'db', name))
    if include_etcd and os.path.isdir(os.path.join(DB_DIR, 'etcd')):
        shutil.copytree(os.path.join(DB_DIR, 'etcd'), os.path.join(target, 'db', 'etcd'), symlinks=True)
    for name in ('token', 'cred', 'tls'):
        path = os.path.join(SERVER_DIR, name)
        if os.path.isdir(path):
            shutil.copytree(path, os.path.join(target, 'server', name), symlinks=True)
        elif os.path.exists(path):
            os.makedirs(os.path.join(target, 'server'), mode=0o700, exist_ok=True)
            shutil.copy2(path, os.path.join(target, 'server', name))
    for name in ('config.yaml', 'token', 'agent-token', 'registries.yaml'):
        path = os.path.join(K3S_DIR, name)
        if os.path.exists(path):
            os.makedirs(os.path.join(target, 'etc'), mode=0o700, exist_ok=True)
            shutil.copy2(path, os.path.join(target, 'etc', name))
    for unit in ('k3s.service', 'k3s.service.env'):
        path = os.path.join('/etc/systemd/system', unit)
        if os.path.exists(path):
            os.makedirs(os.path.join(target, 'systemd'), mode=0o700, exist_ok=True)
            shutil.copy2(path, os.path.join(target, 'systemd', unit))
    rows = file_rows(target)
    with open(os.path.join(target, 'SHA256SUMS'), 'w') as f:
        f.write('\n'.join(rows) + '\n')
    stored = any(r.split('  ', 1)[1] == 'db/state.db' or r.split('  ', 1)[1].startswith('db/etcd/') for r in rows)
    if file_rows(target) != rows or not stored:
        fail(f'the copy {target} does not verify. k3s stays stopped. Inspect the copy, then start k3s or run again.')
    say(f'  the copy {target} holds {len(rows)} verified files')
    return target


def verify_etcd():
    if datastore() != 'etcd':
        fail(f'the server does not use etcd: {DB_DIR}/etcd/member is missing. See journalctl -u k3s.')
    folder = os.path.join(DB_DIR, 'hoover4-verify-' + time.strftime('%Y%m%dT%H%M%S'))
    os.makedirs(folder, mode=0o700)
    try:
        out = subprocess.run(['/usr/local/bin/k3s', 'etcd-snapshot', 'save', '--name', 'hoover4-verify', '--dir', folder],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        files = os.listdir(folder)
        if out.returncode or not files:
            fail('the etcd snapshot of the verification failed: ' + (out.stdout.strip().splitlines() or ['no output'])[-1])
        say(f'  etcd answers, and a snapshot of {os.path.getsize(os.path.join(folder, files[0]))} bytes was saved and removed')
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def restore(name):
    require_server()
    folder = snapshot_folder(operator(), name)
    info = os.path.join(folder, 'host.json')
    if not os.path.isfile(info) or os.path.islink(info):
        fail(f'{info} does not exist. Copy the files of the folder etcd/ of a platform copy into this folder first.')
    data = json.load(open(info))
    path = os.path.join(folder, name_arg(data['snapshot'], 'snapshot file'))
    token = os.path.join(folder, 'token')
    for f in (path, token):
        if not os.path.isfile(f) or os.path.islink(f):
            fail(f'{f} does not exist')
    run(['systemctl', 'stop', 'k3s'])
    if subprocess.run(['systemctl', 'is-active', '-q', 'k3s']).returncode == 0:
        fail('k3s still runs. Stop it first.')
    # k3s ends a reset with a shutdown request and an error line, also after a successful restore. The start and the
    # etcd check below decide whether the restore worked.
    run(['/usr/local/bin/k3s', 'server', '--cluster-reset', '--cluster-reset-restore-path', path, '--token-file', token],
        check=False)
    run(['systemctl', 'start', 'k3s'])
    deadline = time.time() + 300
    while time.time() < deadline:
        out = subprocess.run(['/usr/local/bin/k3s', 'kubectl', 'get', 'nodes', '--no-headers'], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True).stdout
        if ' Ready ' in out:
            break
        time.sleep(5)
    else:
        fail('the server is not Ready after 300 s. See journalctl -u k3s.')
    verify_etcd()


def main(argv):
    if os.geteuid() != 0:
        fail('run the script as root')
    if not argv:
        fail('name a command: datastore, verify-etcd, preserve-sqlite, preserve or restore')
    command, rest = argv[0], argv[1:]
    if command == 'datastore':
        print(datastore())
    elif command == 'verify-etcd':
        verify_etcd()
    elif command == 'preserve-sqlite':
        require_server()
        print(json.dumps({'copy': preserve(RECOVERY_DIR)}))
    elif command in ('preserve', 'restore') and len(rest) == 1:
        if command == 'restore':
            restore(rest[0])
        else:
            require_server()
            user = operator()
            folder = snapshot_folder(user, rest[0])
            os.makedirs(folder, mode=0o700, exist_ok=True)
            target = preserve(folder, include_etcd=True)
            owned_by(folder, user)
            say(f'  the copy {target} belongs to {user.pw_name}')
    else:
        fail(f'unknown command {" ".join(argv)}')


if __name__ == '__main__':
    main(sys.argv[1:])
