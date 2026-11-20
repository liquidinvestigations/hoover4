"""deploy-k3s reset: erase every zone of a site, its data and its accounts, and the images of the retired applications.

The command keeps the intended zones in zone-definitions.json (../zones/zonestate.py), so the next deploy-k3s up
creates them again with new data and new credentials. It keeps the site services, the site credentials that the
deployment needs, the shared stores with their other tenants, the read-only dataset folders and the backups of other
workloads. A later reset erases the zones of that deployment in the same way.

The reset runs as a record of deploy.py (records.py), with these steps in order:
  reset:inventory  verifies the cluster identity of the record, keeps the zone definitions, and records the zones, the
                   namespaces, the persistent volumes and the TopoLVM logical volumes of the zones, the data folders,
                   the managed backups, the etcd snapshots and the images of each node (../images/reclaim.py). The
                   record holds names and identifiers only, no credential and no data.
  reset:suspend    stops the operator portal, whose runner starts the backups, the settings Apply and the zone
                   operations. It removes the Ingresses of the zone namespaces, scales every workload of the zone
                   namespaces and of the processing pools to zero, suspends their CronJobs and waits until no pod of
                   them runs. The end of the reset starts the operator portal again.
  reset:zone:<z>   deletes the zone with zone.py delete: its tenant in the shared stores (ClickHouse, Garage,
                   Manticore, Temporal, PostgreSQL), its namespaces with their claims, its secrets and its zone state
                   entry. A zone that the zone state lacks gets the same removal of each part that remains.
  reset:storage    removes each recorded volume that remains: a Released volume with the reclaim policy Retain gets
                   Delete, and a logical volume without a volume goes through its TopoLVM object. lvs on each node
                   checks the volume groups.
  reset:data       empties the upload folder of each zone on its data node. The testdata folder and the extra datasets
                   are read-only sources and stay.
  reset:backups    removes the zone, platform and staging copies of the backup destination, clears their state, and
                   replaces the etcd snapshots of the control plane with one new snapshot without zone objects.
  reset:state      removes the zone user passwords (site/zone-users) and the local copies of zone files, so the next
                   deployment makes new credentials.
  reset:images     removes the retired images of the inventory from each node and from the site registry.
  reset:verify     checks each backend again and fails with the names of the objects that remain.
While the reset is incomplete, the site lock refuses every other operation (../oplock.py reset marker), so no
deployment, Apply, zone operation, backup or restore creates zone data. A failed or stopped reset keeps its record and
the marker. deploy-k3s reset --resume RECORD runs the steps that are not done. A step checks the current state of each
recorded object first, so a step that ran in part runs again. The end of the reset removes the marker and raises the
installation generation of operator/installation.json. A resume of a reset record or of an up record of an earlier
generation is refused, because a new installation follows the reset.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
sys.path.insert(0, str(SOURCE / 'images'))
sys.path.insert(0, str(SOURCE / 'zones'))
import deploy  # noqa: E402
import nodepod  # noqa: E402

STEPS = ('reset:inventory', 'reset:suspend', 'reset:storage', 'reset:data', 'reset:backups', 'reset:state',
         'reset:images', 'reset:verify')
INSTALLATION = 'installation.json'
POOLS_NAMESPACE = 'hoover-pools'
# The Deployment of the operator portal with the runner (../platform/operator/).
PORTAL = ('operator-portal', 'portal')
SNAPSHOTS = '/var/lib/rancher/k3s/server/db/snapshots'


class Incomplete(deploy.StepFailed):
    """A backend still holds an object of the reset, or a node did not answer."""


def deploy_module():
    return deploy


def checked(function):
    """The step function, with the errors of a node command or a backend as a failed step, so the record keeps the
    message and a resume runs the step again."""
    def run(ctx):
        try:
            return function(ctx)
        except deploy.StepFailed:
            raise
        except (nodepod.Unreachable, nodepod.Failed, RuntimeError, ValueError, KeyError) as error:
            raise Incomplete(f'{type(error).__name__}: {error}') from None
    run.__doc__ = function.__doc__
    return run


def kjson(ctx, *args):
    """The JSON answer of kubectl, from its standard output only."""
    r = subprocess.run(['kubectl', '--kubeconfig', str(ctx.kubeconfig), *args, '-o', 'json'], capture_output=True, text=True)
    if r.returncode:
        if 'NotFound' in r.stderr or 'not found' in r.stderr:
            return None
        raise deploy_module().StepFailed(f'kubectl {" ".join(args[:3])} failed: {r.stderr.strip()[-300:]}')
    return json.loads(r.stdout)


def installation(ctx):
    """{'generation': n, 'resets': [...]} of the operator state of the site. The first installation has generation 1."""
    path = ctx.state / INSTALLATION
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {'generation': 1, 'resets': []}


def save_installation(ctx, data):
    import records
    records.write_json(ctx.state / INSTALLATION, data)


def zone_namespaces(zones):
    return [n for z in zones for n in (z, f'hoover-{z}')]


def planned_zones(ctx):
    """The zones of the reset: the zones of the zone state and every namespace of the zone form in the cluster."""
    import re
    zones = [h.zone for h in ctx.hoovers().values()]
    found = kjson(ctx, 'get', 'namespaces') or {'items': []}
    for item in found['items']:
        match = re.fullmatch(r'(?:hoover-)?(zone-[a-z0-9]{1,12})', item['metadata']['name'])
        if match and match.group(1) not in zones:
            zones.append(match.group(1))
    return zones


def plan(ctx, zones):
    """{step name: function} of a reset of the zones."""
    steps = {'reset:inventory': step_inventory, 'reset:suspend': step_suspend}
    for zone in zones:
        steps[f'reset:zone:{zone}'] = step_zone(zone)
    for name in STEPS[2:]:
        steps[name] = globals()['step_' + name.split(':', 1)[1]]
    return {name: checked(function) for name, function in steps.items()}


def site_nodes(ctx):
    """The nodes of the cluster that are nodes of the site file."""
    found = kjson(ctx, 'get', 'nodes') or {'items': []}
    return [n['metadata']['name'] for n in found['items'] if n['metadata']['name'] in ctx.site.nodes]


def inventory(ctx):
    return ctx.record.setdefault('inventory', {})


# ----------------------------------------------------------------------------------------------------------------------
# Steps
# ----------------------------------------------------------------------------------------------------------------------

def step_inventory(ctx):
    """Keep the zone definitions, then record the objects of the zones before any removal."""
    deploy = deploy_module()
    record = ctx.record
    if (record.get('inputs') or {}).get('cluster_identity') != deploy.cluster_identity(ctx):
        raise deploy.StepFailed('the kubeconfig names another cluster than the record. Start a new reset.')
    zones = record['zones']
    namespaces = zone_namespaces(zones)
    defined = keep_definitions(ctx)
    volumes = []
    for pv in (kjson(ctx, 'get', 'pv') or {'items': []})['items']:
        claim = pv['spec'].get('claimRef') or {}
        labels = pv['metadata'].get('labels') or {}
        kept = labels.get('hoover.dev/seaweedfs-of') in zones or labels.get('hoover.dev/postgresql-of') in zones
        if claim.get('namespace') in namespaces or kept:
            volumes.append({'name': pv['metadata']['name'], 'claim': f"{claim.get('namespace')}/{claim.get('name')}",
                            'class': pv['spec'].get('storageClassName'), 'reclaim': pv['spec'].get('persistentVolumeReclaimPolicy'),
                            'handle': (pv['spec'].get('csi') or {}).get('volumeHandle'),
                            'driver': (pv['spec'].get('csi') or {}).get('driver')})
    handles = {v['handle'] for v in volumes if v['handle']} | {v['name'] for v in volumes}
    logical = []
    for lv in (kjson(ctx, 'get', 'logicalvolumes.topolvm.io') or {'items': []})['items']:
        if lv['metadata']['name'] in handles or (lv.get('status') or {}).get('volumeID') in handles:
            logical.append({'name': lv['metadata']['name'], 'node': lv['spec'].get('nodeName'),
                            'volume_id': (lv.get('status') or {}).get('volumeID'), 'device_class': lv['spec'].get('deviceClass')})
    pods = []
    for ns in namespaces + ['calls']:
        pods += (kjson(ctx, 'get', 'pods', '-n', ns) or {'items': []})['items']
    import reclaim
    nodes = site_nodes(ctx)
    opendesk = sorted((ctx.private / 'downloads').glob('opendesk-*/src'))
    images = reclaim.inventory(ctx.kubeconfig, nodes, opendesk[-1] if opendesk else None, pods)
    out = {'zones': zones, 'definitions': sorted(defined), 'namespaces': namespaces, 'volumes': volumes,
           'logical_volumes': logical, 'nodes': nodes, 'data': data_folders(ctx, zones), 'backups': backup_inventory(ctx),
           'images': images}
    record['inventory'] = out
    ctx.records.save(record)
    return {'zones': zones, 'volumes': len(volumes), 'logical_volumes': len(logical),
            'retired_images': {n: len(v['remove']) + len(v['aliases']) for n, v in images['nodes'].items()},
            'unreachable': images['unreachable']}


# The values of a zone state entry that define the zone (../zones/zonestate.py DEFINED).
DEFINED = ('enabled', 'stores', 'extra_datasets', 'tiers')


def keep_definitions(ctx):
    """Add each zone of the zone state to zone-definitions.json, without its state values. Return the defined zones."""
    import records
    path = ctx.private / 'zone-definitions.json'
    data = json.loads(path.read_text()) if path.exists() else {'schemaVersion': 1, 'zones': {}}
    state_path = ctx.private / 'zone-state.json'
    state = (json.loads(state_path.read_text()).get('zones') or {}) if state_path.exists() else {}
    changed = False
    for zone, entry in state.items():
        if zone not in data['zones']:
            data['zones'][zone] = {k: entry[k] for k in DEFINED if k in entry and entry[k] not in (None, '', [], {})}
            changed = True
    if changed or not path.exists():
        records.write_json(path, data)
    return data['zones']


def data_folders(ctx, zones):
    """[{zone, node, path}] of the upload folder of each zone on its data node."""
    import config
    out = []
    state = {}
    path = ctx.private / 'zone-state.json'
    if path.exists():
        state = json.loads(path.read_text()).get('zones') or {}
    data_nodes = [n.name for n in ctx.site.with_role('data')]
    if ctx.site.single or not data_nodes:
        return out
    for zone in zones:
        entry = state.get(zone)
        node = config.zone_hoover(zone, entry).data_node(ctx.site) if entry else data_nodes[0]
        root = ctx.site.nodes[node].data_root
        out.append({'zone': zone, 'node': node, 'path': f'{root.rstrip("/")}/{zone}/uploads'})
    return out


def backup_inventory(ctx):
    backup = getattr(ctx.site, 'backup', None) or {}
    if not backup.get('node') or not backup.get('path'):
        return {}
    return {'node': backup['node'], 'path': backup['path'].rstrip('/'), 'folders': ['zones', 'platform', 'staging']}


def step_suspend(ctx):
    """Stop the runner of the operator portal, the ingress to the zones and every writer of the zones, then wait until
    no pod of them runs."""
    deploy = deploy_module()
    portal = kjson(ctx, 'get', 'deployment', PORTAL[1], '-n', PORTAL[0])
    if portal is not None:
        replicas = portal['spec'].get('replicas', 1)
        if replicas:
            ctx.record['portal_replicas'] = replicas
            ctx.records.save(ctx.record)
            ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', PORTAL[0], 'scale', 'deployment', PORTAL[1], '--replicas=0'])
        ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', PORTAL[0], 'rollout', 'status', 'deployment', PORTAL[1],
                 '--timeout=300s'])
    namespaces = [ns for ns in inventory(ctx)['namespaces'] if kjson(ctx, 'get', 'namespace', ns)] + [POOLS_NAMESPACE]
    for ns in namespaces:
        if not kjson(ctx, 'get', 'namespace', ns):
            continue
        ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', ns, 'delete', 'ingress', '--all', '--ignore-not-found'])
        for cron in (kjson(ctx, 'get', 'cronjobs', '-n', ns) or {'items': []})['items']:
            ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', ns, 'patch', 'cronjob', cron['metadata']['name'],
                     '--type', 'merge', '-p', '{"spec":{"suspend":true}}'])
        for kind in ('deployment', 'statefulset'):
            if (kjson(ctx, 'get', kind, '-n', ns) or {'items': []})['items']:
                ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', ns, 'scale', kind, '--all', '--replicas=0'])
        ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', ns, 'delete', 'jobs', '--all', '--ignore-not-found',
                 '--wait=false'])
    deadline = time.monotonic() + 900
    while True:
        running = [f"{ns}/{p['metadata']['name']}" for ns in namespaces
                   for p in (kjson(ctx, 'get', 'pods', '-n', ns) or {'items': []})['items']
                   if p['status'].get('phase') in ('Pending', 'Running', 'Unknown')]
        if not running:
            break
        if time.monotonic() > deadline:
            raise deploy.StepFailed(f'{len(running)} pods of the zones still run after 900 s: {", ".join(running[:8])}')
        time.sleep(5)
    return {'namespaces': namespaces, 'writers': 'stopped'}


def step_zone(zone):
    def run(ctx):
        """Delete one zone with zone.py delete, or remove each part of a zone that the zone state lacks."""
        env = {'HOOVER4_RESET': ctx.record['id'], 'HOOVER4_POOLS_STEP': ''}
        state = ctx.private / 'zone-state.json'
        listed = state.exists() and zone in (json.loads(state.read_text()).get('zones') or {})
        if listed:
            ctx.run([sys.executable, SOURCE / 'zones/zone.py', 'delete', zone], env=env)
            return {'deleted': 'zone.py delete'}
        parts = []
        out = subprocess.run([sys.executable, '-c', LEFTOVERS, str(SOURCE), zone], capture_output=True, text=True,
                             env=dict(ctx.env(), **env))
        if out.returncode:
            raise deploy_module().StepFailed(f'the shared stores did not answer for {zone}: {out.stderr.strip()[-300:]}')
        if json.loads(out.stdout.strip().splitlines()[-1]):
            ctx.run([sys.executable, SOURCE / 'hoover/stores/shared.py', 'remove', zone], env=env)
            parts.append('shared stores')
        namespaces = [ns for ns in (zone, f'hoover-{zone}') if kjson(ctx, 'get', 'namespace', ns)]
        if namespaces:
            ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, 'delete', 'namespace', *namespaces, '--wait=true',
                     '--timeout=900s'])
            parts.append('namespaces')
        ctx.run([sys.executable, SOURCE / 'secretstore.py', 'remove', f'zones/{zone}'], env=env)
        folder = ctx.private / 'zones' / zone
        if folder.exists():
            import shutil
            shutil.rmtree(folder)
            parts.append('files')
        return {'deleted': parts or ['nothing remained']}
    return run


# The leftovers of a zone in the shared stores, as JSON on the last line: {store: [names]}. A site without shared
# stores has none.
LEFTOVERS = r'''
import json, sys
sys.path[:0] = [sys.argv[1], sys.argv[1] + '/hoover/stores', sys.argv[1] + '/hoover', sys.argv[1] + '/zones']
import subprocess
import common
if not common.kubectl('get', 'namespace', 'hoover-stores', '--ignore-not-found', '-o', 'name').strip():
    print('{}')
else:
    import shared
    print(json.dumps(shared.leftovers(sys.argv[2])))
'''


def step_storage(ctx):
    """Remove each recorded volume and logical volume that remains, and check the volume groups of the nodes."""
    deploy = deploy_module()
    record = inventory(ctx)
    changed = []
    for volume in record['volumes']:
        pv = kjson(ctx, 'get', 'pv', volume['name'])
        if pv is None:
            continue
        claim = pv['spec'].get('claimRef') or {}
        if claim.get('namespace') and kjson(ctx, 'get', 'pvc', claim.get('name', ''), '-n', claim['namespace']):
            raise deploy.StepFailed(f'the claim {claim["namespace"]}/{claim["name"]} of {volume["name"]} still exists')
        if pv['spec'].get('persistentVolumeReclaimPolicy') != 'Delete':
            # A Released volume with Delete goes back to its provisioner, which removes the backing volume.
            ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, 'patch', 'pv', volume['name'], '-p',
                     '{"spec":{"persistentVolumeReclaimPolicy":"Delete"}}'])
            changed.append(f"pv/{volume['name']} reclaim Delete")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and any(kjson(ctx, 'get', 'pv', v['name']) for v in record['volumes']):
        time.sleep(5)
    for volume in record['volumes']:
        if kjson(ctx, 'get', 'pv', volume['name']):
            # A volume without a provisioner answer: the object goes, and the logical volume below follows.
            ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, 'delete', 'pv', volume['name'], '--wait=true', '--timeout=120s'])
            changed.append(f"pv/{volume['name']} deleted")
    for lv in record['logical_volumes']:
        if kjson(ctx, 'get', 'logicalvolumes.topolvm.io', lv['name']):
            ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, 'delete', 'logicalvolumes.topolvm.io', lv['name'],
                     '--wait=true', '--timeout=300s'])
            changed.append(f"logicalvolume/{lv['name']} deleted")
    left = volume_groups(ctx, record)
    if left:
        raise Incomplete('the volume groups still hold ' + '; '.join(f'{n}: {", ".join(v)}' for n, v in left.items()))
    return {'changed': changed, 'volumes_checked': len(record['volumes']), 'logical_volumes_checked': len(record['logical_volumes'])}


def volume_groups(ctx, record):
    """{node: [volume ids]} of the recorded logical volumes that lvs still lists on their node."""
    wanted = {}
    for lv in record['logical_volumes']:
        if lv.get('node') and lv.get('volume_id'):
            wanted.setdefault(lv['node'], set()).add(lv['volume_id'])
    left = {}
    for node, ids in wanted.items():
        try:
            listed = set(nodepod.run(ctx.kubeconfig, node, 'lvs --noheadings -o lv_name').split())
        except nodepod.Unreachable as error:
            raise Incomplete(str(error)) from None
        if listed & ids:
            left[node] = sorted(listed & ids)
    return left


def step_data(ctx):
    """Empty the upload folder of each zone. The testdata folder and the extra datasets stay."""
    done = []
    for folder in inventory(ctx)['data']:
        path = folder['path']
        if not path.endswith('/uploads') or '/zone-' not in path:
            raise deploy_module().StepFailed(f'{path} is no upload folder of a zone')
        out = nodepod.run(ctx.kubeconfig, folder['node'],
                          f'if [ -d {path} ]; then du -sb {path} | cut -f1; find {path} -mindepth 1 -delete; '
                          f'find {path} -mindepth 1 | wc -l; else echo 0; echo 0; fi')
        numbers = out.split()
        if len(numbers) >= 2 and numbers[1] != '0':
            raise Incomplete(f'{folder["node"]}:{path} still holds {numbers[1]} entries')
        done.append({'zone': folder['zone'], 'node': folder['node'], 'bytes_removed': int(numbers[0]) if numbers else 0})
    return {'folders': done}


def step_backups(ctx):
    """Remove the managed copies of the zones and of the platform, clear their state, and keep one new etcd snapshot."""
    import records
    backup = inventory(ctx)['backups']
    result = {}
    if backup:
        base = backup['path']
        script = ''.join(f'if [ -d {base}/{f} ]; then du -sb {base}/{f} | cut -f1; find {base}/{f} -mindepth 1 -delete; '
                         f'find {base}/{f} -mindepth 1 | wc -l; else echo 0; echo 0; fi; ' for f in backup['folders'])
        numbers = [int(x) for x in nodepod.run(ctx.kubeconfig, backup['node'], script).split()]
        result['copies'] = {f: {'bytes_removed': numbers[2 * i], 'left': numbers[2 * i + 1]} for i, f in enumerate(backup['folders'])}
        left = {f: v['left'] for f, v in result['copies'].items() if v['left']}
        if left:
            raise Incomplete(f'the backup destination still holds {left}')
    state_path = ctx.state / 'backups' / 'state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
        jobs = state.get('jobs') or {}
        removed = sorted(k for k in jobs if k == 'platform' or k.startswith(('zone:', 'hoover:', 'opendesk:')))
        for key in removed:
            del jobs[key]
        state['blocked'] = []
        records.write_json(state_path, state)
        result['state_jobs_removed'] = removed
    for path in sorted((ctx.state / 'backups').glob('restore-*.json')):
        path.unlink()
    result['etcd'] = replace_snapshots(ctx)
    return result


def replace_snapshots(ctx):
    """Save one etcd snapshot of the control plane without zone objects, then delete the older snapshots."""
    node = ctx.site.control_plane
    name = f'reset-{ctx.record["id"][:15].lower()}'
    saved = nodepod.run(ctx.kubeconfig, node, f'k3s etcd-snapshot save --name {name} 2>&1 | tail -1', check=False)
    files = nodepod.run(ctx.kubeconfig, node, f'ls {SNAPSHOTS}').split()
    keep = [f for f in files if f.startswith(f'{name}-')]
    if not keep:
        raise Incomplete(f'the etcd snapshot {name} of {node} is missing: {saved.strip()[-300:]}')
    older = [f for f in files if f not in keep]
    if older:
        nodepod.run(ctx.kubeconfig, node, f'k3s etcd-snapshot delete {" ".join(older)} >/dev/null 2>&1; true')
    left = [f for f in nodepod.run(ctx.kubeconfig, node, f'ls {SNAPSHOTS}').split() if f not in keep]
    if left:
        raise Incomplete(f'the older etcd snapshots {", ".join(left)} of {node} remain')
    return {'kept': keep, 'deleted': older}


def step_state(ctx):
    """Remove the zone user passwords and the local copies of the zone files. The site credentials stay."""
    import shutil
    ctx.run([sys.executable, SOURCE / 'secretstore.py', 'remove', 'site/zone-users'])
    removed = []
    for path in [ctx.private / 'zones' / 'fixture-user-passwords.json', ctx.private / 'stores' / 'zones-replicas.json']:
        if path.exists():
            path.unlink()
            removed.append(str(path.relative_to(ctx.private)))
    for zone in inventory(ctx)['zones']:
        for path in [ctx.private / 'zones' / zone, ctx.private / 'render' / f'{zone}-disabled.yaml',
                     ctx.private / 'placement' / f'render-{zone}.json']:
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(str(path.relative_to(ctx.private)))
            elif path.exists():
                path.unlink()
                removed.append(str(path.relative_to(ctx.private)))
    return {'removed': removed}


def step_images(ctx):
    """Remove the retired images of each node and of the site registry (../images/reclaim.py)."""
    import reclaim
    images = inventory(ctx)['images']
    nodes = inventory(ctx)['nodes']
    result = reclaim.reclaim(ctx.kubeconfig, nodes, images['retired_repositories'], images['retained_repositories'])
    result['registry'] = registry_cleanup(ctx, images['retained_repositories'])
    ctx.record.setdefault('image_results', []).append(result)
    ctx.records.save(ctx.record)
    if result['unreachable']:
        raise Incomplete('these nodes did not answer: ' + '; '.join(f'{n}: {m}' for n, m in result['unreachable'].items()))
    return result


def registry_cleanup(ctx, retained):
    """Remove the repositories of the site registry that name a retired image, then collect the unused blobs."""
    import reclaim
    base = '/var/lib/registry/docker/registry/v2/repositories'
    r = subprocess.run(['kubectl', '--kubeconfig', str(ctx.kubeconfig), '-n', reclaim.REGISTRY_NAMESPACE, 'exec',
                        'deploy/registry', '-c', 'registry', '--', 'sh', '-c',
                        f'cd {base} && find . -name _manifests -type d | sed "s#^./##; s#/_manifests\\$##"'],
                       capture_output=True, text=True)
    if r.returncode:
        return {'error': r.stderr.strip()[-300:]}
    catalog = r.stdout.split()
    retired = reclaim.registry_repositories(catalog, set(retained))
    if retired:
        paths = ' '.join(f'{base}/{name}' for name in retired)
        ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', reclaim.REGISTRY_NAMESPACE, 'exec', 'deploy/registry',
                 '-c', 'registry', '--', 'sh', '-c',
                 f'rm -rf {paths} && registry garbage-collect --delete-untagged {reclaim.REGISTRY_CONFIG}'])
    return {'repositories': len(catalog), 'removed': retired}


def step_verify(ctx):
    """Check each backend for an object of the reset zones and for a retired image. Fail with the names."""
    import reclaim
    record = inventory(ctx)
    zones = record['zones']
    problems = []
    for ns in record['namespaces']:
        if kjson(ctx, 'get', 'namespace', ns):
            problems.append(f'namespace {ns}')
    for v in record['volumes']:
        if kjson(ctx, 'get', 'pv', v['name']):
            problems.append(f"pv {v['name']}")
    for lv in record['logical_volumes']:
        if kjson(ctx, 'get', 'logicalvolumes.topolvm.io', lv['name']):
            problems.append(f"logicalvolume {lv['name']}")
    for zone in zones:
        out = subprocess.run([sys.executable, '-c', LEFTOVERS, str(SOURCE), zone], capture_output=True, text=True, env=ctx.env())
        if out.returncode:
            problems.append(f'the shared stores did not answer for {zone}')
        elif json.loads(out.stdout.strip().splitlines()[-1]):
            problems.append(f'shared stores of {zone}: {out.stdout.strip().splitlines()[-1][:300]}')
    status = subprocess.run([sys.executable, SOURCE / 'secretstore.py', 'status'], capture_output=True, text=True, env=ctx.env())
    paths = json.loads(status.stdout.strip().splitlines()[-1]) if status.returncode == 0 else None
    if paths is None:
        problems.append('the secret store did not answer')
    else:
        problems += [f'secret path zones/{p}' for p in paths['zones'] if p.rstrip('/') in zones]
        if 'zone-users' in paths['sites']:
            problems.append('secret path site/zone-users')
    state = ctx.private / 'zone-state.json'
    listed = json.loads(state.read_text()).get('zones') or {} if state.exists() else {}
    problems += [f'zone state entry {z}' for z in zones if z in listed]
    images = record['images']
    left = reclaim.remaining(ctx.kubeconfig, record['nodes'], images['retired_repositories'], images['retained_repositories'])
    problems += [f'retired images on {n}: {len(ids)}' for n, ids in left.items()]
    if problems:
        raise Incomplete('the reset is incomplete: ' + '; '.join(problems[:30]))
    defined = json.loads((ctx.private / 'zone-definitions.json').read_text())['zones'] \
        if (ctx.private / 'zone-definitions.json').exists() else {}
    return {'zones_removed': zones, 'zones_defined': sorted(defined), 'checked': ['namespaces', 'volumes', 'logical volumes',
            'shared stores', 'secret store', 'zone state', 'node images']}


# ----------------------------------------------------------------------------------------------------------------------
# Start and end
# ----------------------------------------------------------------------------------------------------------------------

def begin(ctx, record, lock):
    """Keep the reset marker on the site lock and record the marker of a reset that it replaces."""
    current = lock.reset_marker()
    if current and current.get('record') != record['id']:
        record['replaces'] = current.get('record')
    lock.set_reset({'record': record['id'], 'started': record['created'], 'generation': record['generation']})


def finish(ctx, record, lock):
    """Remove the marker and raise the installation generation after a complete reset."""
    data = installation(ctx)
    data['generation'] = record['generation'] + 1
    data['resets'] = (data.get('resets') or [])[-9:] + [{'record': record['id'], 'finished': record.get('updated'),
                                                          'zones': (record.get('inventory') or {}).get('zones')}]
    save_installation(ctx, data)
    lock.set_reset(None)
    replicas = record.get('portal_replicas')
    if replicas and kjson(ctx, 'get', 'deployment', PORTAL[1], '-n', PORTAL[0]) is not None:
        ctx.run(['kubectl', '--kubeconfig', ctx.kubeconfig, '-n', PORTAL[0], 'scale', 'deployment', PORTAL[1],
                 f'--replicas={replicas}'], check=False)


def refuse_resume(ctx, record, lock):
    """The reason to refuse the resume of a reset record, or None."""
    if record.get('status') == 'done':
        return f'the reset {record["id"]} is complete. Start a new reset.'
    if installation(ctx)['generation'] != record.get('generation'):
        return (f'the reset {record["id"]} belongs to the installation generation {record.get("generation")}, and the '
                f'site has generation {installation(ctx)["generation"]}. Start a new reset.')
    marker = lock.reset_marker()
    if marker and marker.get('record') != record['id']:
        return f'the reset {marker.get("record")} replaced the reset {record["id"]}. Resume {marker.get("record")}.'
    return None
