"""Pod template changes that put a store on Kata with TopoLVM block volumes."""
import copy

# ../../images/blockmount builds this image. Each node pulls it from the cluster registry.
TOOLS_IMAGE = 'registry.hoover.internal/hoover/blockmount:8'


def blockmount(spec, container, entrypoint, mounts, user=None, nofile=None):
    """Mount block volumes inside the guest before the store starts.

    spec is a pod spec. container names the store container. Calls for several containers of one pod share the volumes. entrypoint is the full original command, because the
    wrapper replaces the image ENTRYPOINT. mounts is a list of (volume name, PVC name, directory). The PVC name is None
    for a volume claim template of a StatefulSet, which needs no pod volume. user is "uid:gid" for a store that does not
    drop its own rights. The container runs as root inside the guest with SYS_ADMIN for the mount and SYS_RESOURCE for the
    online growth of a file system. The wrapper makes the first ext4 file system on a new volume.
    """
    spec = copy.deepcopy(spec)
    names = {m[0] for m in mounts}
    spec['volumes'] = [v for v in spec.get('volumes', []) if v['name'] not in names or 'persistentVolumeClaim' in v and
                       any(v['persistentVolumeClaim']['claimName'] == c for n2, c, _ in mounts if n2 == v['name'])]
    spec['volumes'] += [{'name': n, 'persistentVolumeClaim': {'claimName': c}} for n, c, _ in mounts
                        if c and not any(v['name'] == n for v in spec['volumes'])]
    if any(v['name'] == 'blockmount-tools' for v in spec['volumes']):
        spec['initContainers'] = [i for i in spec.get('initContainers', []) if i['name'] != 'blockmount-tools']
    else:
        spec['volumes'].append({'name': 'blockmount-tools', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '16Mi'}})
    spec.setdefault('initContainers', []).insert(0, {
        'name': 'blockmount-tools', 'image': TOOLS_IMAGE, 'imagePullPolicy': 'IfNotPresent',
        'command': ['/busybox', 'cp', '-r', '/busybox', '/run.sh', '/musl', '/tools/'],
        'volumeMounts': [{'name': 'blockmount-tools', 'mountPath': '/tools'}],
        'resources': {'limits': {'cpu': '100m', 'memory': '16Mi'}}})
    c = next(c for c in spec['containers'] if c['name'] == container)
    c['volumeMounts'] = [m for m in c.get('volumeMounts', []) if m['name'] not in names]
    c['volumeMounts'].append({'name': 'blockmount-tools', 'mountPath': '/tools', 'readOnly': True})
    # A small memory emptyDir at each mount path makes the runtime create the directory, also on a read-only root file
    # system. The wrapper mounts the block device over it.
    for n, _, d in mounts:
        point = f'blockmount-point-{n}'
        if not any(v['name'] == point for v in spec['volumes']):
            spec['volumes'].append({'name': point, 'emptyDir': {'medium': 'Memory', 'sizeLimit': '1Mi'}})
        c['volumeMounts'].append({'name': point, 'mountPath': d})
    c['volumeDevices'] = [{'name': n, 'devicePath': f'/dev/block-{n}'} for n, _, _ in mounts]
    c['command'] = ['/tools/busybox', 'sh', '/tools/run.sh']
    c['args'] = list(entrypoint)
    env = [e for e in c.get('env', []) if e['name'] not in ('BLOCK_MOUNTS', 'BLOCK_USER', 'BLOCK_NOFILE')]
    if nofile:
        env.append({'name': 'BLOCK_NOFILE', 'value': str(nofile)})
    env.append({'name': 'BLOCK_MOUNTS', 'value': ' '.join(f'/dev/block-{n}:{d}' for n, _, d in mounts)})
    if user:
        env.append({'name': 'BLOCK_USER', 'value': user})
    c['env'] = env
    sc = c.setdefault('securityContext', {})
    sc.update(runAsUser=0, runAsGroup=0, runAsNonRoot=False, allowPrivilegeEscalation=True)
    caps = sc.setdefault('capabilities', {})
    caps['add'] = sorted(set(caps.get('add', [])) | {'SYS_ADMIN', 'SYS_RESOURCE'})
    if 'drop' in caps:
        caps['drop'] = [d for d in caps['drop'] if d not in ('ALL', 'SYS_ADMIN', 'SYS_RESOURCE')]
        if not caps['drop']:
            del caps['drop']
    psc = spec.setdefault('securityContext', {})
    psc.pop('runAsNonRoot', None)
    if psc.get('runAsUser') not in (None, 0):
        psc.pop('runAsUser')
    return spec
