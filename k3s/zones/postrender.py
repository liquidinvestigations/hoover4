#!/usr/bin/env python3
"""Helm post-renderer of a zone. It reads the rendered manifests on stdin and writes the changed manifests on stdout.

Helm runs this file for each release of the zone, so an upgrade keeps every change. The same input gives the same
output, so a second install finds no difference. Helm does not pass hook objects through a post-renderer.
manifests/zone-pods.yaml therefore puts every pod of the zone on its home node and in gVisor at admission.

- Stores: the chart StatefulSets and Deployments of STORES run in Kata. Their volumes become raw TopoLVM block volumes
  of the store tier on the home node (zonestate.py), and the block mount wrapper of ../hoover/stores/podspec.py
  mounts them inside the guest. The chart Services select the same pods as before.
- Storage: every other volume claim uses the default tier of the zone.
- Resources: cpu_policy.py sets the CPU request and limit of each controller and CronJob. memory-limits.json sets the
  memory limits. Jobs keep the chart values, because a Job template cannot change after its creation.
- Patches: Synapse loads synapse/hoover_e2ee.py, the user verification service logs at warn, Jitsi web uses the UDP
  TURN server for the bridge connection, the OpenProject worker loads openproject/zz-hoover-cron.rb, and the Element
  media cleanup has no starting deadline. The docstrings of the functions below give the reasons.
- A disabled zone (zonestate.py) renders zero replicas and suspended CronJobs and Jobs.
- A suspended CronJob stays suspended, so an update does not resume a CronJob that an operator suspended.
- A Job that the chart names by the release revision gets a name from a hash of its content (REVISION_JOBS).
- The runtime exceptions of EXCEPTIONS run in Kata or with runc instead of gVisor.
Usage: postrender.py <zone namespace>
The system Python runs this file, because the post-renderer needs PyYAML.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / 'hoover' / 'stores'))
import cpu_policy  # noqa: E402
import podspec  # noqa: E402
import settings  # noqa: E402
import zonestate  # noqa: E402

MEMORY = json.loads((HERE / 'memory-limits.json').read_text())['zone']
CONTROLLERS = {'Deployment': 'deployment', 'StatefulSet': 'statefulset', 'DaemonSet': 'daemonset', 'CronJob': 'cronjob'}
# The chart stores that run in Kata. volumes: the volume or claim template name and its mount directory in the store
# container. user: uid:gid of the store process, which also owns a new file system. The command of the container,
# or else the image entrypoint in entrypoint, followed by its arguments, starts the store. size replaces the chart size.
STORES = {
    'statefulset/redis-master': {'store': 'redis', 'container': 'redis', 'volumes': {'redis-data': '/data'}, 'user': '1001:1001'},
    'statefulset/ums-provisioning-nats': {'store': 'nats', 'container': 'main', 'volumes': {'nats-data': '/data'},
                                          'user': '1000:1000', 'entrypoint': ['/nats-server']},
    'statefulset/postgresql': {'store': 'postgresql', 'container': 'postgresql', 'volumes': {'data': '/mnt/postgresql'},
                               'user': '1001:1001', 'entrypoint': ['docker-entrypoint.sh'], 'size': '20Gi'},
    'deployment/seaweedfs-all-in-one': {'store': 'seaweedfs', 'container': 'seaweedfs', 'volumes': {'data': '/data'}, 'user': '1000:1000',
                                        'size': '30Gi'},
    'deployment/memcached': {'store': 'memcached', 'container': 'memcached', 'volumes': {}},
}
STORE_LABEL = 'hoover.dev/store'
# Workloads that do not run in gVisor, with the runtime that they get and the observed failure. The zone pod policy
# (manifests/zone-pods.yaml) keeps a RuntimeClass that a pod names.
EXCEPTIONS = {
    # runsc refuses to start the second init container prepare-config: "reading mounts file: error unmarshaling mounts:
    # unexpected end of JSON input". The container mounts two ConfigMap files with subPath into an emptyDir mount.
    # A new pod fails in the same way.
    'deployment/ums-umc-gateway': 'kata',
    # The SSSD sidecar creates its sockets in a shared emptyDir. gVisor gives each container its own mount of that
    # folder, so the main container does not see the sockets, finds no user, and refuses each portal sign-in with
    # "PAM OIDC Authentication failed while JWT verification succeeded". The gVisor mount hints for a pod-wide tmpfs need
    # containerd to pass pod annotations to runsc, which the nodes do not do. In Kata the sidecar ran once, and each
    # restart of it failed with "failed to create shim task: File exists (os error 17)".
    'statefulset/ums-umc-server': 'runc',
    # The LDAP notifier is a separate pod that shares two volumes with slapd. It learns of a new transaction through a
    # directory change signal (dnotify) on the listener folder, and it writes to slapd over the ldapi socket. Neither
    # crosses two gVisor sandboxes: the notifier stayed at transaction 0 while slapd reached 1017, so no directory change
    # reached the provisioning consumers. After a restart it failed with "ldap_sasl_interactive_bind_s(): Can't contact
    # LDAP server". Both pods therefore run with runc on the home node.
    'statefulset/ums-ldap-server-primary': 'runc',
    'statefulset/ums-ldap-notifier': 'runc',
}
# Jobs whose chart name ends with the Helm release revision. A diff renders another revision, so helmfile would upgrade
# these releases on each run. The post-renderer names each such Job by a hash of its content instead: an unchanged Job
# keeps its name, and a changed Job gets a new name and runs again.
REVISION_JOBS = ('openproject-seeder', 'opendesk-nextcloud-management', 'opendesk-migrations-pre', 'opendesk-migrations-post',
                 'opendesk-keycloak-bootstrap-bootstrap', 'opendesk-trust', 'opendesk-openproject-bootstrap-bootstrap',
                 'ums-keycloak-bootstrap-bootstrap', 'ums-provisioning-register-consumers', 'ums-stack-data-ums')
JITSI_MARK = '// hoover: the bridge connection uses the UDP TURN server of Prosody.'
JITSI_TURN = JITSI_MARK + '\nconfig.useTurnUdp = true;\n'


def kubectl_json(*args):
    result = subprocess.run(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), *args, '-o', 'json'], capture_output=True, text=True)
    if result.returncode:
        if 'NotFound' in result.stderr:
            return None
        raise RuntimeError(f'kubectl {" ".join(args)}: {result.stderr.strip()[:300]}')
    return json.loads(result.stdout)


class Zone:
    """The zone of a namespace with its home node, its tiers and its switch state."""

    def __init__(self, namespace):
        self.namespace = namespace
        self.state = zonestate.load()
        self.name = zonestate.zone_of(namespace, self.state)
        self.disabled = not zonestate.namespace_enabled(namespace, self.state)
        self.tiers = zonestate.node_tiers(zonestate.home(self.name, self.state), settings.KUBECONFIG)

    def storage_class(self, store, mode):
        return f"{zonestate.tier(self.name, store, self.tiers, self.state)}-{mode}"


def mebibytes(value):
    units = {'Ki': 1 / 1024, 'Mi': 1, 'Gi': 1024, 'K': 1 / 1048.576, 'M': 1 / 1.048576, 'G': 953.674}
    text = str(value)
    for unit, factor in units.items():
        if text.endswith(unit):
            return float(text[:-len(unit)]) * factor
    return float(text) / 1048576


def pod_spec(doc):
    if doc['kind'] == 'CronJob':
        return doc['spec']['jobTemplate']['spec']['template']['spec']
    return doc['spec']['template']['spec']


def ref(doc):
    return f"{CONTROLLERS.get(doc['kind'], doc['kind'].lower())}/{doc['metadata']['name']}"


def container(spec, name):
    return next(c for c in spec['containers'] if c['name'] == name)


def kata_store(doc, rule, zone, claims):
    """Move a chart store into Kata on raw block volumes of its tier."""
    spec = pod_spec(doc)
    store = rule['store']
    block = zone.storage_class(store, 'block')
    templates = {t['metadata']['name']: t for t in doc['spec'].get('volumeClaimTemplates', [])}
    mounts = []
    for volume, directory in rule['volumes'].items():
        if volume in templates:
            templates[volume]['spec'].update(volumeMode='Block', storageClassName=block)
            if rule.get('size'):
                templates[volume]['spec']['resources'] = {'requests': {'storage': rule['size']}}
            mounts.append((volume, None, directory))
        else:
            claim = next(v['persistentVolumeClaim']['claimName'] for v in spec['volumes'] if v['name'] == volume)
            claims[claim] = (block, rule.get('size'))
            mounts.append((volume, claim, directory))
    c = container(spec, rule['container'])
    if mounts:
        command = (c.get('command') or rule.get('entrypoint', [])) + (c.get('args') or [])
        spec = podspec.blockmount(spec, rule['container'], command, mounts, rule.get('user'))
        doc['spec']['template']['spec'] = spec
    spec['runtimeClassName'] = 'kata'
    spec['enableServiceLinks'] = False
    # A pod sysctl needs a runtime that applies it in the pod network namespace. The Kata guest has its own
    # network stack, and NATS listens on ports above 1024.
    spec.get('securityContext', {}).pop('sysctls', None)
    doc['spec']['template']['metadata'].setdefault('labels', {})[STORE_LABEL] = store


def memory(doc):
    for name, limit in MEMORY.get(ref(doc), {}).items():
        resources = container(pod_spec(doc), name).setdefault('resources', {})
        resources.setdefault('limits', {})['memory'] = limit
        # A request above the new limit is not valid.
        requested = (resources.get('requests') or {}).get('memory')
        if requested and mebibytes(requested) > mebibytes(limit):
            resources['requests']['memory'] = limit


def synapse(doc, extra, zone):
    """Encrypt each new room except the rooms of the meetings bot.

    An init container copies synapse/hoover_e2ee.py from a ConfigMap into /modules, and render-config reads its settings
    file. The meetings bot stays without encryption: its SDK sends device_keys null on each start after the first key
    upload, and Synapse 1.161 refuses that request, so the bot stops.
    """
    spec = pod_spec(doc)
    bot = f'@meetings-bot:{zone.name}.{settings.SUFFIX}'
    modules = f'modules:\n  - module: hoover_e2ee.EncryptNewRooms\n    config:\n      exempt_users: ["{bot}"]\n'
    source = (HERE / 'synapse/hoover_e2ee.py').read_text()
    if not any(o['metadata']['name'] == 'hoover-synapse-modules' for o in extra):
        extra.append({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'hoover-synapse-modules'},
                      'data': {'hoover_e2ee.py': source, 'hoover-modules.yaml': modules}})
    spec['volumes'].append({'name': 'hoover-modules', 'configMap': {'name': 'hoover-synapse-modules'}})
    main = spec['containers'][0]
    spec['initContainers'].insert(0, {
        'name': 'install-hoover-modules', 'image': main['image'], 'command': ['sh', '-c', 'cp /hoover/hoover_e2ee.py /modules/'],
        'resources': {'requests': {'cpu': '10m', 'memory': '16Mi'}, 'limits': {'cpu': '500m', 'memory': '64Mi'}},
        'securityContext': main.get('securityContext', {}),
        'volumeMounts': [{'name': 'synapse-modules', 'mountPath': '/modules'}, {'name': 'hoover-modules', 'mountPath': '/hoover', 'readOnly': True}]})
    render = next(c for c in spec['initContainers'] if c['name'] == 'render-config')
    args = render.get('args', [])
    # render-config merges the files in order and appends lists, so the module joins the openDesk modules.
    at = next((i for i, a in enumerate(args) if a.startswith('/config-templates/04-')), len(args))
    render['args'] = args[:at] + ['/hoover/hoover-modules.yaml'] + args[at:]
    render.setdefault('volumeMounts', []).append({'name': 'hoover-modules', 'mountPath': '/hoover', 'readOnly': True})
    digest = hashlib.sha256((source + modules).encode()).hexdigest()[:16]
    doc['spec']['template']['metadata'].setdefault('annotations', {})['hoover.dev/synapse-modules'] = digest


def jitsi_files(doc):
    """Make Jitsi web use the UDP TURN server that Prosody announces, also for the bridge connection.

    The shared JVB announces its pod address only, so a browser outside the host reaches it through coturn. Without TURN
    its ICE check fails, and the client starts its bridge session again about every 15 seconds. lib-jitsi-meet keeps a
    UDP TURN server for the bridge only with config.useTurnUdp, which the chart sets only for its own coturn.
    """
    current = doc['data'].get('custom-config.js', '')
    kept = [line for line in current.rstrip('\n').split('\n')
            if not line.startswith(('// hoover:', 'config.useStunTurn', 'config.p2p.useStunTurn', 'config.useTurnUdp'))]
    doc['data']['custom-config.js'] = '\n'.join(kept) + '\n' + JITSI_TURN


def openproject_worker(doc, extra):
    """Load openproject/zz-hoover-cron.rb in the OpenProject worker.

    The user sync with the admin flag then runs each minute, and the worker enqueues each missed cron time at start.
    """
    source = (HERE / 'openproject/zz-hoover-cron.rb').read_text()
    extra.append({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'hoover-openproject-cron'},
                  'data': {'zz-hoover-cron.rb': source}})
    spec = pod_spec(doc)
    spec['volumes'].append({'name': 'hoover-cron', 'configMap': {'name': 'hoover-openproject-cron'}})
    container(spec, 'openproject').setdefault('volumeMounts', []).append(
        {'name': 'hoover-cron', 'mountPath': '/app/config/initializers/zz-hoover-cron.rb', 'subPath': 'zz-hoover-cron.rb', 'readOnly': True})
    # A subPath mount does not follow a changed ConfigMap, so a changed file restarts the worker through this hash.
    doc['spec']['template']['metadata'].setdefault('annotations', {})['hoover.dev/cron'] = hashlib.sha256(source.encode()).hexdigest()[:16]


def overlay(documents, namespace):
    zone = Zone(namespace)
    extra, claims = [], {}
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        kind, name = doc.get('kind'), doc.get('metadata', {}).get('name')
        if kind == 'ConfigMap' and name == 'jitsi-meet-files':
            jitsi_files(doc)
        if kind == 'Job':
            base, _, number = name.rpartition('-')
            if base in REVISION_JOBS and number.isdigit():
                # Some charts also put the Job name into its labels, so every value equal to the name changes with it.
                spec = json.dumps(doc['spec'], sort_keys=True).replace(json.dumps(name), json.dumps(base))
                renamed = json.loads(json.dumps(doc).replace(json.dumps(name), json.dumps(f'{base}-{hashlib.sha256(spec.encode()).hexdigest()[:8]}')))
                doc.clear()
                doc.update(renamed)
                name = doc['metadata']['name']
        if kind in ('Job', 'CronJob') and zone.disabled:
            doc['spec']['suspend'] = True
        elif kind == 'CronJob':
            live = kubectl_json('-n', namespace, 'get', 'cronjob', name)
            # Only a suspended CronJob changes the render, so a second install of an unchanged zone finds no difference.
            if live is not None and live['spec'].get('suspend'):
                doc['spec']['suspend'] = True
            if name == 'opendesk-element-customization-media-cleanup':
                # The chart gives a starting deadline of 600 s. Without it, the CronJob starts one Job for its most
                # recent missed time when the zone starts again after a stop.
                doc['spec'].pop('startingDeadlineSeconds', None)
        if kind == 'DaemonSet' and zone.disabled:
            raise RuntimeError(f'the disabled namespace {namespace} renders the DaemonSet {name}, which has no replica count')
        if kind not in CONTROLLERS:
            continue
        key = ref(doc)
        if key in EXCEPTIONS and EXCEPTIONS[key] == 'runc':
            pod_spec(doc).pop('runtimeClassName', None)
            template = doc['spec']['jobTemplate']['spec']['template'] if kind == 'CronJob' else doc['spec']['template']
            template['metadata'].setdefault('labels', {})['hoover.dev/runtime'] = 'runc'
        elif key in EXCEPTIONS:
            pod_spec(doc)['runtimeClassName'] = EXCEPTIONS[key]
        if key in STORES:
            kata_store(doc, STORES[key], zone, claims)
        elif kind == 'StatefulSet':
            for template in doc['spec'].get('volumeClaimTemplates', []):
                template['spec']['storageClassName'] = zone.storage_class('default', 'ext4')
        if key in ('statefulset/element-synapse-main', 'statefulset/element-synapse-media-repo'):
            synapse(doc, extra, zone)
        if key == 'deployment/opendesk-matrix-user-verification-service':
            # The service logs each health probe over several lines.
            env = container(pod_spec(doc), 'uvs').setdefault('env', [])
            env[:] = [e for e in env if e['name'] != 'UVS_LOG_LEVEL'] + [{'name': 'UVS_LOG_LEVEL', 'value': 'warn'}]
        if key == 'deployment/openproject-worker-default':
            openproject_worker(doc, extra)
        if key == 'deployment/jitsi-web':
            # The web container writes config.js from custom-config.js at its start.
            doc['spec']['template']['metadata'].setdefault('annotations', {})['hoover.dev/jitsi-turn'] = \
                hashlib.sha256(JITSI_TURN.encode()).hexdigest()[:16]
        doc['metadata'].setdefault('namespace', namespace)
        cpu_policy.apply(doc)
        memory(doc)
        if zone.disabled and kind != 'CronJob':
            doc['spec']['replicas'] = 0
    for doc in documents:
        if isinstance(doc, dict) and doc.get('kind') == 'PersistentVolumeClaim':
            name = doc['metadata']['name']
            if name in claims:
                block, size = claims[name]
                doc['spec'].update(volumeMode='Block', storageClassName=block)
                if size:
                    doc['spec']['resources'] = {'requests': {'storage': size}}
            else:
                doc['spec']['storageClassName'] = zone.storage_class('default', 'ext4')
    return documents + extra


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    documents = overlay(list(yaml.safe_load_all(sys.stdin)), sys.argv[1])
    # helmfile joins the output of several releases, so every document starts with its own separator.
    yaml.safe_dump_all([d for d in documents if d is not None], sys.stdout, sort_keys=False, explicit_start=True)


if __name__ == '__main__':
    main()
