#!/usr/bin/env python3
"""Helm post-renderer of a zone. It reads the rendered manifests on stdin and writes the changed manifests on stdout.

Helm runs this file for each release of the zone, so an upgrade keeps every change. The same input gives the same
output, so a second install finds no difference. Helm does not pass hook objects through a post-renderer.
manifests/zone-pods.yaml therefore puts every pod of the zone in gVisor at admission.

- Stores: the chart StatefulSets and Deployments of STORES run in Kata. Their volumes become raw TopoLVM block volumes
  of the store tier of the site (zonestate.py), and the block mount wrapper of ../hoover/stores/podspec.py
  mounts them inside the guest. The chart Services select the same pods as before.
- Storage: every other volume claim uses the default tier of the zone.
- Priority: a Deployment or StatefulSet with a claim, or with pods that name a node, gets the PriorityClass
  hoover-node-bound (node_bound()). Its pods preempt pods of the default priority on a full node.
- Resources: cpu_policy.py sets the CPU request and limit of each controller and CronJob. cpu_requests.py then
  raises the CPU request of each measured workload to the value of cpu-requests.json, from its start peak and its idle
  baseline, and writes the annotations of that basis into its pod template. memory-limits.json sets the memory
  limits. memory_requests.py sets the memory request of each workload of memory-requests.json from its measured peak
  under load, so the scheduler places each pod by its real load. Jobs keep the chart values, because a Job template
  cannot change after its creation.
- Rollout: a single-replica Deployment that requests MAX_SURGE_MEMORY or more, or that NO_SURGE names, replaces its pod
  with maxSurge 0 and maxUnavailable 1 (rollout()), so an update does not need the memory of a second pod on a full site.
- Patches: Jitsi web uses the UDP TURN server for the bridge connection (jitsi_files()).
- Profile: a render that holds a controller of a retired application (applications.py RETIRED_WORKLOADS) stops. The
  openDesk secrets release loses the Secrets of the retired applications (applications.py retired_secret()), so an
  upgrade deletes them.
- Periodic tasks: each CronJob of the charts becomes a container that stays running and runs the same command at the
  same interval (PERIODIC, periodic()). A CronJob would start a new pod for each run. A CronJob without a rule stops
  the render.
- A disabled zone (zonestate.py) renders zero replicas and suspended Jobs.
- A Job that the chart names by the release revision gets a name from a hash of its content (REVISION_JOBS).
- The runtime exceptions of EXCEPTIONS run in Kata or with runc instead of gVisor.
- Probes: each exec probe starts one runtime command at each period (cpu_requests.py runtime_cost()). probes()
  removes the exec probes that always pass, replaces an exec probe with its equal TCP probe, and lengthens the
  periods of PROBE_PERIODS.
Usage: postrender.py <zone namespace>
The system Python runs this file, because the post-renderer needs PyYAML.
"""
import fnmatch
import hashlib
import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / 'hoover' / 'stores'))
import cpu_policy  # noqa: E402
import cpu_requests  # noqa: E402
import memory_requests  # noqa: E402
import podspec  # noqa: E402
import applications  # noqa: E402
import settings  # noqa: E402
import zonestate  # noqa: E402

MEMORY_FILE = json.loads((HERE / 'memory-limits.json').read_text())
MEMORY = MEMORY_FILE['zone']
# A single-replica Deployment whose pod requests this many MiB or more starts its new pod only after the old one
# stopped (rollout()).
MAX_SURGE_MEMORY = 512
# The smaller single-replica Deployments that also start their new pod only after the old one stopped. The second pod
# of the UDM REST API (448 MiB) found no node on the full test site (2026-11-16), and its rollout waited without end.
NO_SURGE = ('ums-udm-rest-api',)
# The workloads of each openDesk application of the profile (applications.py APPLICATIONS), by name pattern. A disabled
# application (operator setting app.<name>) renders zero replicas and keeps its claims, so an enable restores it with
# its data.
APP_WORKLOADS = {
    'nextcloud': ('opendesk-nextcloud-*',),
    'collabora': ('collabora', 'collabora-*'),
    'jitsi': ('jitsi-*',),
    'xwiki': ('xwiki*',),
}


def probes(doc, key):
    """Remove the exec probes of NO_OP_COMMANDS, use the TCP probes of TCP_PROBES and the periods of PROBE_PERIODS."""
    for c in (pod_spec(doc).get('containers') or []) + (pod_spec(doc).get('initContainers') or []):
        for kind in ('livenessProbe', 'readinessProbe', 'startupProbe'):
            probe = c.get(kind)
            if not probe:
                continue
            command = (probe.get('exec') or {}).get('command')
            # The chart commands end with a line break.
            if command and [part.strip() for part in command] in [list(n) for n in NO_OP_COMMANDS]:
                del c[kind]
                continue
            if command and (key, c['name']) in TCP_PROBES:
                del probe['exec']
                probe['tcpSocket'] = {'port': TCP_PROBES[(key, c['name'])]}
            if (key, c['name'], kind) in PROBE_PERIODS:
                probe['periodSeconds'] = PROBE_PERIODS[(key, c['name'], kind)]


def operator_values(zone):
    """The effective operator settings of a zone: the saved revision in HOOVER4_SETTINGS_REVISION, else the newest.
    An installation without operator state gets the defaults of the registry."""
    import importlib.util
    path = HERE.parent / 'platform/operator/settings.py'
    spec = importlib.util.spec_from_file_location('operator_settings', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = settings.SITE.operator_state() if settings.SITE else None
    revision = os.environ.get('HOOVER4_SETTINGS_REVISION')
    overrides = {}
    if folder and (folder / 'desired.json').exists():
        overrides = module.State(folder).overrides(int(revision) if revision else None)
    return module.effective(f'zone:{zone}', overrides.get(f'zone:{zone}', {}))


def disabled_app(name, values):
    for app, patterns in APP_WORKLOADS.items():
        if values.get(f'app.{app}') == 'false' and any(fnmatch.fnmatchcase(name, p) for p in patterns):
            return app
    return None
# The probes whose period is shorter than needed: (key, container, probe): seconds. The probe of a pod at rest
# repeats at this period. A start waits for the first passed readiness probe, at most one period after the start.
PROBE_PERIODS = {
    # A Nextcloud status request every 3 s.
    ('deployment/opendesk-nextcloud-aio', 'aio', 'readinessProbe'): 10,
    # Redis pings every 1 s and every 5 s in Kata.
    ('statefulset/redis-master', 'redis', 'readinessProbe'): 10,
    ('statefulset/redis-master', 'redis', 'livenessProbe'): 10,
}
# The exec probes that have an equal TCP probe: (key, container): port. pgrep of memcached finds the process, and the
# TCP probe finds the listening port of the same process.
TCP_PROBES = {('deployment/memcached', 'memcached'): 11211}
# An exec probe with one of these commands always passes. Kubernetes counts a container without such a probe as
# alive and ready, so the probe has no effect apart from its cost.
NO_OP_COMMANDS = (['sh', '-c', 'exit 0'], ['/bin/sh', '-c', 'exit 0'], ['/bin/bash', '-c', 'exit 0'])
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
# The PriorityClass of the pods that can run on one node only (../cluster/priorityclasses.yaml).
NODE_BOUND = 'hoover-node-bound'
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
    # LDAP server". Both pods therefore run with runc. They share volumes, so they run on the node of those volumes.
    'statefulset/ums-ldap-server-primary': 'runc',
    'statefulset/ums-ldap-notifier': 'runc',
}
# Jobs whose chart name ends with the Helm release revision. A diff renders another revision, so helmfile would upgrade
# these releases on each run. The post-renderer names each such Job by a hash of its content instead: an unchanged Job
# keeps its name, and a changed Job gets a new name and runs again.
REVISION_JOBS = ('opendesk-nextcloud-management', 'opendesk-migrations-pre', 'opendesk-migrations-post',
                 'opendesk-keycloak-bootstrap-bootstrap', 'opendesk-trust',
                 'ums-keycloak-bootstrap-bootstrap', 'ums-provisioning-register-consumers', 'ums-stack-data-ums')
# The CronJobs of the openDesk charts. periodic() replaces each with a container that stays running. The container
# runs the command of the CronJob with its image, environment, volumes and service account, at the times of its
# schedule, and also once at its start.
#   pod        the workload whose pod gets the container (a sidecar). None: the container runs in its own Deployment.
#              A sidecar needs the service account of that pod. A sidecar restarts the pod of its workload at each
#              change of the task, so a task of a service that other pods need runs in its own Deployment.
#   deployment the name of that Deployment, when pod is None. The default is the name of the CronJob. The tasks of one
#              Deployment need the same service account and pod security context.
#   container  the name of the container.
#   command    the command of the run when the CronJob container names none: the entrypoint and the command of the
#              image.
#   memory     the memory request: the highest working set of the pod cgroup in one run of the CronJob pod, of both zones
#              (load of 2026-11-16), rounded up to 32 MiB. It holds the gVisor sentry of that pod, so it is the upper
#              value for a sidecar.
UDM_PERIODIC = 'ums-udm-rest-api-periodic'
PERIODIC = {
    # cron.php runs the Nextcloud background jobs. Peaks 126 and 91 MiB.
    'opendesk-nextcloud-aio-cron': {'pod': 'deployment/opendesk-nextcloud-aio', 'container': 'cron', 'memory': '128Mi',
                                    'command': ['/docker-entrypoint.sh', '/usr/bin/php',
                                                '/usr/local/bin/entrypoint/entrypoint.php']},
    # Counts the users, servers and clients, and writes the counts into the license object of the directory, where UMC
    # and the UDM REST API read them. Peaks 86 and 74 MiB. The two UDM tasks share one Deployment. As sidecars, a
    # change of a task restarted the UDM REST API, and the provisioning transformer then lost its connection.
    'ums-udm-rest-api-license-cache': {'pod': None, 'deployment': UDM_PERIODIC, 'container': 'license-cache',
                                       'memory': '96Mi'},
    # Removes the expired entries of the UDM blocklist. Peaks 61 and 47 MiB.
    'ums-udm-rest-api-blocklist-cleanup': {'pod': None, 'deployment': UDM_PERIODIC, 'container': 'blocklist-cleanup',
                                           'memory': '64Mi', 'command': ['/bin/blocklist_clean_expired.py']},
}
PERIODIC_LABEL = 'hoover.dev/periodic'
# The loop of a periodic task. Arguments: the task name, then the interval, the offset and the retry wait in seconds,
# then the command.
# A run that fails does not stop the loop. As the backoffLimit 6 of a Job, a failed run repeats after RETRY seconds, at
# most 5 times, unless the next time of the schedule comes first. The first run at the start of a sidecar can fail
# while its own pod is not ready, for example the blocklist cleanup, which calls the Service of the UDM REST API.
# The sleep runs in the background, so a stop signal ends the wait at once.
PERIODIC_RETRY = 60
PERIODIC_LOOP = '''trap 'kill $! 2>/dev/null; exit 0' TERM INT
name=$0 every=$1 offset=$2 retry=$3
shift 3
failed=0
while :; do
  start=$(date +%s)
  "$@"
  code=$?
  end=$(date +%s)
  echo "periodic task $name: exit $code after $((end - start)) s"
  wait=$(( (end - offset) / every * every + every + offset - end ))
  if [ $code -eq 0 ]; then failed=0; else failed=$((failed + 1)); fi
  if [ $failed -gt 0 ] && [ $failed -le 5 ] && [ $retry -lt $wait ]; then wait=$retry; fi
  sleep $wait &
  wait $!
done
'''
JITSI_MARK = '// hoover: the bridge connection uses the UDP TURN server of Prosody.'
JITSI_TURN = JITSI_MARK + '\nconfig.useTurnUdp = true;\n'


class Zone:
    """The zone of a namespace with the storage tiers of the site and its switch state."""

    def __init__(self, namespace):
        self.namespace = namespace
        self.state = zonestate.load()
        self.name = zonestate.zone_of(namespace, self.state)
        self.disabled = not zonestate.namespace_enabled(namespace, self.state)
        self.tiers = zonestate.site_tiers(settings.KUBECONFIG)

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


def node_bound(doc):
    """Give the PriorityClass NODE_BOUND to a Deployment or StatefulSet whose pods can run on one node only: a pod with a
    claim, which stays on the node of its local volume, or a pod that names a node. A chart value stays."""
    spec = pod_spec(doc)
    if doc['kind'] not in ('Deployment', 'StatefulSet'):
        return
    if (doc['spec'].get('volumeClaimTemplates') or (spec.get('nodeSelector') or {}).get('kubernetes.io/hostname')
            or any('persistentVolumeClaim' in v for v in spec.get('volumes') or [])):
        spec.setdefault('priorityClassName', NODE_BOUND)


def memory(doc):
    for name, limit in MEMORY.get(ref(doc), {}).items():
        resources = container(pod_spec(doc), name).setdefault('resources', {})
        resources.setdefault('limits', {})['memory'] = limit
        # A request above the new limit is not valid.
        requested = (resources.get('requests') or {}).get('memory')
        if requested and mebibytes(requested) > mebibytes(limit):
            resources['requests']['memory'] = limit


def rollout(doc):
    """Give a single-replica Deployment that requests MAX_SURGE_MEMORY or more, or that NO_SURGE names, the rolling
    update maxSurge 0 and maxUnavailable 1. The old pod stops before the new pod starts, so an update needs no free memory for a second pod.
    A Recreate strategy of the chart stays, because it also starts no second pod."""
    if doc['kind'] != 'Deployment' or doc['spec'].get('replicas', 1) != 1:
        return
    if (doc['spec'].get('strategy') or {}).get('type') == 'Recreate':
        return
    spec = pod_spec(doc)
    requested = sum(mebibytes(((c.get('resources') or {}).get('requests') or {}).get('memory', '0'))
                    for c in spec.get('containers') or [])
    if requested >= MAX_SURGE_MEMORY or doc['metadata']['name'] in NO_SURGE:
        doc['spec']['strategy'] = {'type': 'RollingUpdate', 'rollingUpdate': {'maxSurge': 0, 'maxUnavailable': 1}}


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


def interval(schedule):
    """(seconds, offset) of a CronJob schedule of the form '*/N * * * *', 'M * * * *' or 'M H * * *', in UTC. The loop
    runs at each time t with (t - offset) a multiple of seconds, as the CronJob did."""
    fields = schedule.split()
    if len(fields) == 5 and fields[2:] == ['*', '*', '*']:
        minute, hour = fields[:2]
        if minute.startswith('*/') and minute[2:].isdigit() and hour == '*':
            return int(minute[2:]) * 60, 0
        if minute.isdigit() and hour == '*':
            return 3600, int(minute) * 60
        if minute.isdigit() and hour.isdigit():
            return 86400, int(hour) * 3600 + int(minute) * 60
    raise RuntimeError(f'the CronJob schedule {schedule!r} has no interval form in postrender.py interval()')


def periodic_container(doc, rule):
    """The container that runs the task of a CronJob in a loop, and its volumes. The volumes get the container name as
    a prefix, so a sidecar shares no emptyDir with the containers of its pod."""
    spec = pod_spec(doc)
    name = doc['metadata']['name']
    if len(spec['containers']) != 1 or spec.get('initContainers'):
        raise RuntimeError(f'the CronJob {name} has more than one container, which periodic() does not support')
    c = json.loads(json.dumps(spec['containers'][0]))
    command = (c.pop('command', None) or rule.get('command')) + c.pop('args', [])
    if not command:
        raise RuntimeError(f'the CronJob {name} names no command, and PERIODIC gives none')
    every, offset = interval(doc['spec']['schedule'])
    prefix = rule['container']
    c['name'] = prefix
    c['command'] = ['/bin/sh', '-c', PERIODIC_LOOP, name, str(every), str(offset), str(PERIODIC_RETRY), *command]
    c['resources'].setdefault('requests', {})['memory'] = rule['memory']
    volumes = []
    for volume in spec.get('volumes') or []:
        volumes.append(dict(volume, name=f"{prefix}-{volume['name']}"))
    for mount in c.get('volumeMounts') or []:
        mount['name'] = f"{prefix}-{mount['name']}"
    return c, volumes


def own_labels(labels, selectors):
    """The labels of a CronJob pod without the labels that make a selector of the render match it. A CronJob of a
    chart has the labels of its service, so without this a selector of that Service or Deployment, or kubectl exec
    deploy/<name>, would also find the pod of the task."""
    out = dict(labels)
    for selector in selectors:
        while selector and all(out.get(k) == v for k, v in selector.items()):
            out.pop(next(k for k in selector if k in out))
    return out


def periodic(documents, disabled=False, values=None):
    """Replace each CronJob with the container of its PERIODIC rule: a sidecar in the pod of rule['pod'], or a
    container of the Deployment rule['deployment'] (default: the name of the CronJob). A CronJob without a rule stops
    the render. The containers keep the CPU
    values that overlay() gave the CronJob. A pod that gets a sidecar gets rollout() again, because its request grew."""
    out, targets, groups, selectors = [], {}, {}, []
    for doc in documents:
        if isinstance(doc, dict) and doc.get('kind') in ('Deployment', 'StatefulSet'):
            targets[ref(doc)] = doc
        if isinstance(doc, dict) and doc.get('kind') in ('Deployment', 'StatefulSet', 'DaemonSet', 'Service'):
            spec = doc.get('spec') or {}
            found = spec.get('selector') if doc['kind'] == 'Service' else (spec.get('selector') or {}).get('matchLabels')
            if found:
                selectors.append(found)
    for doc in documents:
        if not isinstance(doc, dict) or doc.get('kind') != 'CronJob':
            out.append(doc)
            continue
        name = doc['metadata']['name']
        rule = PERIODIC.get(name)
        if rule is None:
            raise RuntimeError(f'the chart renders the CronJob {name}, which has no rule in postrender.py PERIODIC. '
                               'A CronJob starts a new pod for each run.')
        c, volumes = periodic_container(doc, rule)
        template = doc['spec']['jobTemplate']['spec']['template']
        spec = template['spec']
        if rule['pod']:
            target = targets.get(rule['pod'])
            if target is None:
                raise RuntimeError(f'the CronJob {name} needs {rule["pod"]}, which this render does not have')
            pod = pod_spec(target)
            for field in ('serviceAccountName', 'securityContext'):
                if spec.get(field) != pod.get(field):
                    raise RuntimeError(f'the CronJob {name} and {rule["pod"]} differ in {field}')
            pod['containers'] = [x for x in pod['containers'] if x['name'] != c['name']] + [c]
            kept = {v['name'] for v in volumes}
            pod['volumes'] = [v for v in pod.get('volumes') or [] if v['name'] not in kept] + volumes
            rollout(target)
            continue
        deployment = rule.get('deployment') or name
        own = groups.get(deployment)
        if own is not None:
            pod = own['spec']['template']['spec']
            for field in ('serviceAccountName', 'securityContext'):
                if spec.get(field) != pod.get(field):
                    raise RuntimeError(f'the CronJob {name} and the other tasks of {deployment} differ in {field}')
            pod['containers'].append(c)
            pod['volumes'].extend(volumes)
            continue
        labels = own_labels(template['metadata'].get('labels') or {}, selectors)
        labels[PERIODIC_LABEL] = deployment
        spec = dict(spec, containers=[c], volumes=volumes, restartPolicy='Always')
        replicas = 0 if disabled or disabled_app(name, values or {}) else 1
        groups[deployment] = {'apiVersion': 'apps/v1', 'kind': 'Deployment',
                              'metadata': {'name': deployment, 'namespace': doc['metadata'].get('namespace'),
                                           'labels': doc['metadata'].get('labels') or {}},
                              'spec': {'replicas': replicas, 'strategy': {'type': 'Recreate'},
                                       'selector': {'matchLabels': {PERIODIC_LABEL: deployment}},
                                       'template': {'metadata': dict(template['metadata'], labels=labels), 'spec': spec}}}
        out.append(groups[deployment])
    return out


def retired_secret(doc):
    if not isinstance(doc, dict) or doc.get('kind') != 'Secret':
        return False
    labels = doc.get('metadata', {}).get('labels') or {}
    return (labels.get('app.kubernetes.io/instance') == applications.SECRETS_RELEASE and
            applications.retired_secret(doc['metadata'].get('name', '')))


def overlay(documents, namespace):
    zone = Zone(namespace)
    values = operator_values(namespace)
    for key, value in values.items():
        if key.startswith('memory.'):
            workload, name = key[len('memory.'):].rsplit('.', 1)
            MEMORY.setdefault(workload, {})[name] = value
    extra, claims = [], {}
    documents = [d for d in documents if not retired_secret(d)]
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
        if kind == 'Job' and zone.disabled:
            doc['spec']['suspend'] = True
        if kind == 'DaemonSet' and zone.disabled:
            raise RuntimeError(f'the disabled namespace {namespace} renders the DaemonSet {name}, which has no replica count')
        if kind not in CONTROLLERS and kind != 'Job':
            continue
        if applications.retired_workload(name):
            raise RuntimeError(f'the render of {namespace} holds the {kind} {name} of a retired application '
                               '(zones/applications.py). Check the apps values of zones.py for this openDesk release.')
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
        if key == 'deployment/jitsi-web':
            # The web container writes config.js from custom-config.js at its start.
            doc['spec']['template']['metadata'].setdefault('annotations', {})['hoover.dev/jitsi-turn'] = \
                hashlib.sha256(JITSI_TURN.encode()).hexdigest()[:16]
        doc['metadata'].setdefault('namespace', namespace)
        node_bound(doc)
        probes(doc, key)
        cpu_policy.apply(doc)
        memory(doc)
        main = next(iter(MEMORY.get(key) or {}), None)
        memory_requests.apply(doc, key, 'zone', main=main)
        cpu_requests.apply(doc, key, 'zone', main=main)
        rollout(doc)
        if zone.disabled and kind != 'CronJob':
            doc['spec']['replicas'] = 0
        elif kind in ('Deployment', 'StatefulSet') and disabled_app(name, values):
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
    return periodic(documents, zone.disabled, values) + extra


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    documents = overlay(list(yaml.safe_load_all(sys.stdin)), sys.argv[1])
    # helmfile joins the output of several releases, so every document starts with its own separator.
    yaml.safe_dump_all([d for d in documents if d is not None], sys.stdout, sort_keys=False, explicit_start=True)


if __name__ == '__main__':
    main()
