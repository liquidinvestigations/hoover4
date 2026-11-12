#!/usr/bin/env python3
"""Preserve the state of the local single-node site and prepare the complete removal of its k3s installation.

  inventory DEST   Reads the host and the cluster and writes DEST/inventory.json: the units of the site, the mounts and
                   logical volumes, the dummy link, the DNS routing, the CA anchor, the k3s files and binaries, the
                   claims of each namespace, and the protected resources that the removal keeps (the Compose volumes,
                   the dataset folders, the kubeconfig link of another project, the runner of the remote cluster).
                   Root-only facts that the user cannot read are marked unreadable. It changes nothing.
  archive DEST     Closes the site with deploy-k3s down without the k3s step, so every writer, Temporal and the stores
                   stop and stopped.json keeps their replicas. It then copies each claim through a short pod into
                   DEST/claims/<namespace>/<claim>.tar (a Block claim through the Kata wrapper of the stores), exports
                   the objects of the namespaces of the claims into DEST/objects.json, copies k3s/private into
                   DEST/private.tar and writes DEST/archive-manifest.json with the size and SHA-256 of every file.
                   k3s keeps running. The k3s datastore and token need root: the command prints that step.
  verify DEST      Reads every file of the archive again against archive-manifest.json.
  manifest DEST    Writes archive-manifest.json again, for files that a root step added after archive, for example
                   the preserved k3s datastore. Run verify after it.
  removal DEST     Writes DEST/remove-local-k3s.sh from inventory.json: the commands that stop and remove the units,
                   the k3s files, the dummy link, the DNS routing, the CA anchor, the volumes of the site and the
                   sudo rule of the bootstrap. It names each protected resource in a comment and changes none of them.
                   A person reviews the script and runs it as root. The command itself removes nothing.
Every file that holds a secret gets mode 0600. Usage: local-retirement.py inventory|archive|verify|manifest|removal DEST
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parent
sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'hoover' / 'stores'))
import config  # noqa: E402
import settings as k3s_settings  # noqa: E402

UNITS = ('k3s.service', 'hoover4-address.service', 'hoover4-dns.service', 'hoover4-frontend.service')
USER_UNITS = ('hoover4-operator-runner.service',)
PATHS = ('/etc/rancher/k3s/config.yaml', '/etc/rancher/k3s/token', '/etc/rancher/k3s/agent-token',
         '/etc/rancher/k3s/hoover4-admin.yaml', '/etc/rancher/k3s/registries.yaml', '/usr/local/bin/k3s',
         '/usr/local/bin/k3s-killall.sh', '/usr/local/bin/k3s-uninstall.sh', '/usr/local/libexec/hoover4',
         '/etc/sudoers.d/90-hoover4', '/opt/gvisor', '/opt/kata', '/etc/kata-containers', '/etc/gvisor',
         '/etc/systemd/system/hoover4.slice', '/etc/systemd/resolved.conf.d/hoover4.conf',
         '/etc/ca-certificates/trust-source/anchors/hoover4-local-ca.crt', '/var/lib/rancher', '/var/lib/kubelet')
# Resources that the removal keeps. The kubeconfig link belongs to another project, and the user unit hoover-operator
# runs the operator of the remote cluster until its replacement.
PROTECTED = {'/etc/rancher/k3s/k3s.yaml': 'the kubeconfig link of another project',
             'hoover-operator.service': 'the runner of the remote cluster until its controlled replacement'}
SKIP_NAMESPACES = ('kube-system', 'kube-public', 'kube-node-lease', 'default')
# The registry holds images that a build of a commit makes again, and monitoring holds metrics and logs only.
REBUILT_NAMESPACES = ('registry', 'monitoring')
HELPER_IMAGE = 'docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'


def run(argv, timeout=120):
    try:
        r = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return r.returncode, (r.stdout + r.stderr).strip()


def kubectl(*args, check=True, **kw):
    r = subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, *args], capture_output=True, text=True, **kw)
    if check and r.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:5])} failed: {r.stderr.strip()[-300:]}')
    return r.stdout


def site():
    s = config.read(k3s_settings.SITE_FILE)
    local = [n for n in s.nodes.values() if n.local]
    if not s.single or not local:
        raise SystemExit('this tool retires the local node of a single-node site only.')
    return s, local[0]


def inventory(dest):
    s, node = site()
    out = {'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'node': node.name, 'units': {}, 'user_units': {},
           'paths': {}, 'protected': dict(PROTECTED)}
    for unit in UNITS:
        out['units'][unit] = {'active': run(['systemctl', 'is-active', unit])[1],
                              'enabled': run(['systemctl', 'is-enabled', unit])[1]}
    for unit in USER_UNITS + ('hoover-operator.service',):
        out['user_units'][unit] = {'active': run(['systemctl', '--user', 'is-active', unit])[1]}
    for path in PATHS + tuple(PROTECTED)[:1]:
        p = Path(path)
        try:
            out['paths'][path] = ('link -> ' + os.readlink(p)) if p.is_symlink() else ('folder' if p.is_dir() else
                                                                                       'file' if p.exists() else 'absent')
        except PermissionError:
            out['paths'][path] = 'unreadable'
    out['mounts'] = run(['findmnt', '-rn', '-o', 'TARGET,SOURCE,FSTYPE'])[1].splitlines()
    out['mounts'] = [m for m in out['mounts'] if m.split()[0].startswith(('/var/lib/rancher', '/var/lib/kubelet'))
                     or node.lvm_volume_group in m]
    code, lvs = run(['sudo', '-n', 'lvs', '--noheadings', '-o', 'lv_name,lv_size,lv_tags', node.lvm_volume_group])
    out['volume_group'] = {'name': node.lvm_volume_group, 'physical_volumes': list(node.lvm_physical_volumes),
                           'volumes': lvs.splitlines() if code == 0 else 'unreadable without root'}
    out['link'] = run(['ip', '-o', 'addr', 'show', 'hoover4'])[1]
    out['dns'] = run(['resolvectl', 'domain'])[1]
    out['claims'] = {}
    if Path(k3s_settings.KUBECONFIG).exists():
        claims = json.loads(kubectl('get', 'pvc', '-A', '-o', 'json', check=False) or '{"items": []}')['items']
        for c in claims:
            out['claims'].setdefault(c['metadata']['namespace'], {})[c['metadata']['name']] = {
                'uid': c['metadata']['uid'], 'volume': c['spec'].get('volumeName', ''),
                'size': c['spec']['resources']['requests']['storage'], 'mode': c['spec'].get('volumeMode', 'Filesystem'),
                'class': c['spec'].get('storageClassName')}
    source_inis = [h.source_ini for h in s.hoovers.values() if h.source_ini]
    for ini in source_inis:
        try:
            found = config.read_source_ini(ini, check_paths=False)
            out['protected'][found.volumes_path] = 'the stopped Compose volumes'
            for mount in found.dataset_mounts:
                out['protected'][mount['host_path']] = 'a dataset folder of the Compose install'
        except config.SiteError as error:
            out['protected'][ini] = f'unreadable source ini: {error}'
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'inventory.json').write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'inventory': str(dest / 'inventory.json'), 'claims': sum(len(v) for v in out['claims'].values())}))
    return out


def reader_pod(namespace, claim, mode):
    import podspec
    spec = {'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'enableServiceLinks': False,
            'containers': [{'name': 'read', 'image': HELPER_IMAGE, 'command': ['sleep', '86400'],
                            'resources': {'limits': {'cpu': '1', 'memory': '256Mi'}},
                            'volumeMounts': [{'name': 'data', 'mountPath': '/data', 'readOnly': True}]}],
            'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}}]}
    if mode == 'Block':
        spec['containers'][0]['volumeMounts'] = []
        spec = podspec.blockmount(spec, 'read', ['sleep', '86400'], [('data', claim, '/data')])
        spec['runtimeClassName'] = 'kata'
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'retirement-read', 'namespace': namespace}, 'spec': spec}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(4 << 20):
            h.update(chunk)
    return h.hexdigest()


def tar_complete(path):
    """True when the tar file at path reads to its end-of-archive marker."""
    import tarfile
    try:
        with tarfile.open(path) as tar:
            for _ in tar:
                pass
        return True
    except (tarfile.TarError, EOFError, OSError):
        return False


def write_manifest(dest):
    rows = []
    for root, _, files in os.walk(dest):
        for name in sorted(files):
            path = Path(root) / name
            rel = str(path.relative_to(dest))
            if rel in ('archive-manifest.json', 'inventory.json', 'remove-local-k3s.sh'):
                continue
            rows.append({'path': rel, 'bytes': path.stat().st_size, 'sha256': digest(path)})
    (dest / 'archive-manifest.json').write_text(json.dumps({'files': rows}, indent=1) + '\n')
    return rows


def verify(dest):
    dest = Path(dest)
    wanted = json.loads((dest / 'archive-manifest.json').read_text())['files']
    differences = [r['path'] for r in wanted
                   if not (dest / r['path']).exists() or (dest / r['path']).stat().st_size != r['bytes']
                   or digest(dest / r['path']) != r['sha256']]
    result = {'files': len(wanted), 'bytes': sum(r['bytes'] for r in wanted), 'differences': differences}
    print(json.dumps(result))
    return result


def archive(dest):
    s, node = site()
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    # The writers, Temporal and the stores stop in their tiers, and stopped.json keeps the replicas for a restart.
    subprocess.run([sys.executable, K3S / 'deploy-k3s', 'down', '--site', str(k3s_settings.SITE_FILE),
                    '--target', node.name, '--steps', 'stop:ingress',
                    'stop:applications', 'stop:temporal', 'stop:stores'], check=True)
    claims = json.loads(kubectl('get', 'pvc', '-A', '-o', 'json'))['items']
    namespaces, kept = set(), []
    for c in claims:
        ns, name = c['metadata']['namespace'], c['metadata']['name']
        if ns in SKIP_NAMESPACES + REBUILT_NAMESPACES or any(o['kind'] == 'Pod' for o in c['metadata'].get('ownerReferences', [])):
            continue
        volume = c['spec'].get('volumeName')
        pv = json.loads(kubectl('get', 'pv', volume, '-o', 'json')) if volume else {}
        if 'hostPath' in pv.get('spec', {}) or 'local' in pv.get('spec', {}):
            # A host folder of the node, for example a Compose dataset folder, stays in place and is protected.
            kept.append(f'{ns}/{name}')
            continue
        namespaces.add(ns)
        target = dest / 'claims' / ns / f'{name}.tar'
        if target.exists() and target.with_suffix('.done').exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        kubectl('-n', ns, 'delete', 'pod', 'retirement-read', '--ignore-not-found', '--wait=true')
        kubectl('apply', '-f', '-', input=json.dumps(reader_pod(ns, name, c['spec'].get('volumeMode', 'Filesystem'))))
        kubectl('-n', ns, 'wait', '--for=condition=Ready', 'pod/retirement-read', '--timeout=600s')
        with open(target, 'wb') as out:
            r = subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, '-n', ns, 'exec', 'retirement-read',
                                '--', 'sh', '-c', 'until grep -q " /data " /proc/mounts; do sleep 1; done; '
                                'tar -C /data -cf - .'], stdout=out)
        kubectl('-n', ns, 'delete', 'pod', 'retirement-read', '--wait=false')
        # kubectl exec can end with status 0 after a stream reset, so the tar file is read to its end.
        if r.returncode or not tar_complete(target):
            raise SystemExit(f'the copy of {ns}/{name} failed or is incomplete. The site stays stopped. Run archive again.')
        target.with_suffix('.done').write_text(json.dumps({'uid': c['metadata']['uid'], 'volume': c['spec'].get('volumeName')}))
    objects = {}
    for ns in sorted(namespaces):
        objects[ns] = json.loads(kubectl('-n', ns, 'get', 'secrets,configmaps,persistentvolumeclaims,services,'
                                         'deployments,statefulsets,cronjobs,ingresses,networkpolicies', '-o', 'json'))
    (dest / 'objects.json').write_text(json.dumps(objects))
    os.chmod(dest / 'objects.json', 0o600)
    (dest / 'persistent-volumes.json').write_text(kubectl('get', 'pv', '-o', 'json'))
    excluded = ['build', 'bin', 'browser-venv', 'checks', 'downloads', 'staging/amd64', 'staging/arm64']
    subprocess.run(['tar', '-C', str(k3s_settings.PRIVATE), '-cf', str(dest / 'private.tar'),
                    *[f'--exclude=./{e}' for e in excluded], '.'], check=True)
    os.chmod(dest / 'private.tar', 0o600)
    (dest / 'kept-in-place.json').write_text(json.dumps(kept, indent=1))
    rows = write_manifest(dest)
    print(json.dumps({'archive': str(dest), 'files': len(rows), 'bytes': sum(r['bytes'] for r in rows), 'kept': kept,
                      'next': 'Run with sudo: /usr/local/libexec/hoover4/root-install-k3s.py --bundle <bundle of the '
                              f'last up> --node {node.name} --preserve k3s-server. Move ~/k3s-install/snapshots/'
                              f'k3s-server into {dest}, then run local-retirement.py manifest and verify.'}))


REMOVAL = """#!/bin/sh
# Remove the local k3s installation of node {node}. Review every line, then run it as root.
# Generated from {inventory} at {time}. It keeps these protected resources unchanged:
{protected}
# Another project uses the k3s binary, kubectl, crictl and ctr, so the binaries, their links, k3s-killall.sh and
# k3s-uninstall.sh stay. The script removes only the services, units, data, network and DNS setup of this site.
set -eu
systemctl stop hoover4-frontend.service hoover4-dns.service || true
systemctl stop k3s.service || true
# k3s-killall.sh stops the pods of the site, unmounts their folders and removes the CNI links and rules of k3s.
[ -x /usr/local/bin/k3s-killall.sh ] && /usr/local/bin/k3s-killall.sh || true
# The kill script misses the gVisor shims and sandboxes, which keep the k3s volumes in their mount namespaces.
pkill -KILL -f '^/opt/gvisor/' || true
pkill -KILL -f '^runsc-' || true
systemctl disable hoover4-frontend.service hoover4-dns.service hoover4-address.service k3s.service || true
# The runner of the local site is a user unit of {user}. Run as {user}: systemctl --user disable --now hoover4-operator-runner
rm -rf /etc/systemd/system/k3s.service /etc/systemd/system/k3s.service.env /etc/systemd/system/k3s.service.d
# /etc/rancher/k3s/k3s.yaml and hoover4-admin.yaml, which it names, stay for the other project. The other files of the
# folder belong to this site.
rm -f /etc/rancher/k3s/config.yaml /etc/rancher/k3s/token /etc/rancher/k3s/agent-token \\
      /etc/rancher/k3s/registries.yaml
rm -rf /run/k3s /run/flannel
{volume_lines}
rm -rf /var/lib/rancher/k3s /var/lib/kubelet
rm -f /etc/systemd/system/hoover4-address.service /etc/systemd/system/hoover4-dns.service \\
      /etc/systemd/system/hoover4-frontend.service /etc/systemd/system/hoover4.slice
rm -f /etc/systemd/resolved.conf.d/hoover4.conf
rm -f /etc/ca-certificates/trust-source/anchors/hoover4-local-ca.crt && (update-ca-trust || trust extract-compat || true)
ip link delete hoover4 2>/dev/null || true
rm -rf /opt/gvisor /opt/kata /etc/kata-containers /etc/gvisor /usr/local/libexec/hoover4
rm -f /etc/sudoers.d/90-hoover4
systemctl daemon-reload
systemctl reset-failed k3s.service 2>/dev/null || true
systemctl restart systemd-resolved
echo "removed. Check: systemctl status k3s; findmnt /var/lib/rancher; ip link show hoover4; resolvectl query example.org"
"""


def removal(dest):
    dest = Path(dest)
    data = json.loads((dest / 'inventory.json').read_text())
    if not (dest / 'archive-manifest.json').exists():
        raise SystemExit(f'{dest} holds no archive. Run archive and verify before the removal script.')
    vg = data['volume_group']['name']
    lines = []
    for mount in ('/var/lib/kubelet', '/var/lib/rancher'):
        lines.append(f'umount -R {mount} 2>/dev/null || true')
        lines.append(f"sed -i '\\# {mount} #d' /etc/fstab")
    lines.append(f'# The volume group {vg} holds the k3s volumes and the TopoLVM volumes of the site. lvs lists them:')
    lines.append(f'lvs {vg}')
    lines.append(f'lvremove -y {vg}')
    lines.append(f'# Remove the group only when lvs shows no other volume: vgremove {vg} && pvremove '
                 + ' '.join(data['volume_group']['physical_volumes']))
    protected = '\n'.join(f'#   {k}: {v}' for k, v in sorted(data['protected'].items()))
    text = REMOVAL.format(node=data['node'], inventory=dest / 'inventory.json', time=data['time'], protected=protected,
                          user=os.environ.get('USER', ''), volume_lines='\n'.join(lines))
    path = dest / 'remove-local-k3s.sh'
    path.write_text(text)
    os.chmod(path, 0o700)
    print(json.dumps({'script': str(path)}))


def main(argv):
    if len(argv) != 2 or argv[0] not in ('inventory', 'archive', 'verify', 'manifest', 'removal'):
        raise SystemExit(__doc__)
    if argv[0] == 'manifest':
        rows = write_manifest(Path(argv[1]))
        print(json.dumps({'archive': argv[1], 'files': len(rows), 'bytes': sum(r['bytes'] for r in rows)}))
        return
    {'inventory': inventory, 'archive': archive, 'verify': verify, 'removal': removal}[argv[0]](argv[1])


if __name__ == '__main__':
    main(sys.argv[1:])
