#!/usr/bin/env python3
"""Build and apply the Hoover stores of a zone in Kata: ClickHouse, the two Manticore daemons and Garage.

Each store gets a ConfigMap from config/<store>/ where it has one, a Service, and a one-replica StatefulSet in the zone
namespace. Its data is a raw TopoLVM block volume of the store tier on the home node of the zone (../../zones/zonestate.py).
The block mount wrapper of podspec.py makes the file system and mounts it inside the guest.
Credentials come from the hoover-stores Secret (creds.py). The ClickHouse users file has a user for each Hoover service
(service_users.py), and each password comes from that Secret. The memory limits come from ../../zones/memory-limits.json.
The StatefulSets use the OnDelete update strategy. zone.py replaces outdated pods after applying their templates.
A direct run of this tool keeps existing pods until an operator deletes them.
Usage: hoover.py apply|show <clickhouse|manticore|manticore-vectors|garage> <zone>
"""
import json, subprocess, sys
import common, podspec, service_users
import zonestate  # noqa: E402  (common puts ../../zones on the path)

SECRET = 'hoover-stores'
CONFIG = common.LAB / 'config'
LIMITS = json.loads((common.SOURCE / 'zones' / 'memory-limits.json').read_text())['hoover']
SIZES = {'clickhouse': '20Gi', 'manticore': '10Gi', 'manticore-vectors': '10Gi', 'garage': '20Gi'}
IMAGES = {
    'clickhouse': 'docker.io/clickhouse/clickhouse-server:25.8',
    'manticore': 'docker.io/manticoresearch/manticore:29.9.0',
    'garage': 'docker.io/dxflrs/garage:v2.3.0',
}
# Manticore reads searchd settings from searchd_* variables. Small caches, no pseudo sharding, memory-mapped attributes.
MANTICORE_ENV = {'TELEMETRY': '0', 'searchd_auth': '1', 'searchd_rt_flush_period': '900', 'searchd_qcache_max_bytes': '0',
                 'searchd_pseudo_sharding': '0', 'searchd_docstore_cache_size': '4m', 'searchd_threads': '2',
                 'searchd_access_plain_attrs': 'mmap', 'searchd_access_blob_attrs': 'mmap', 'searchd_access_doclists': 'file',
                 'searchd_access_hitlists': 'file'}


def resources(store):
    return {'requests': {'cpu': '50m', 'memory': '64Mi'}, 'limits': {'cpu': '2', 'memory': LIMITS[store]}}


def secret_env(name, key):
    return {'name': name, 'valueFrom': {'secretKeyRef': {'name': SECRET, 'key': key}}}


def prefix(zone):
    return zone.replace('-', '_')


def configmap(store, zone, name=None):
    # The ClickHouse users file names the zone user, which is the zone prefix, and the users of the services.
    files = {p.name: p.read_text().replace('ZONE_PREFIX', prefix(zone)).replace('<!-- SERVICE_USERS -->', service_users.clickhouse_users_xml(zone))
             for p in sorted((CONFIG / store).iterdir()) if p.is_file()}
    return {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': f'{name or store}-config', 'namespace': zone, 'labels': {common.LABEL: 'config'}},
            'data': files}


def service(store, zone, ports):
    return {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': store, 'namespace': zone, 'labels': {common.LABEL: 'service'}},
            'spec': {'selector': {'app.kubernetes.io/name': store},
                     'ports': [{'name': n, 'port': p, 'targetPort': p} for n, p in ports]}}


def statefulset(store, zone, container, entrypoint, directory, user=None, extra_volumes=()):
    spec = {'runtimeClassName': 'kata', 'terminationGracePeriodSeconds': 60, 'enableServiceLinks': False,
            'containers': [container], 'volumes': list(extra_volumes)}
    spec = podspec.blockmount(spec, container['name'], entrypoint, [('data', None, directory)], user)
    tier = zonestate.tier(zone, store, zonestate.node_tiers(zonestate.home(zone), common.settings.KUBECONFIG))
    labels = {'app.kubernetes.io/name': store, common.LABEL: 'store', 'hoover.dev/store': store}
    claim = {'metadata': {'name': 'data'}, 'spec': {'accessModes': ['ReadWriteOnce'], 'volumeMode': 'Block',
             'storageClassName': f'{tier}-block', 'resources': {'requests': {'storage': SIZES[store]}}}}
    return {'apiVersion': 'apps/v1', 'kind': 'StatefulSet',
            'metadata': {'name': f'{store}-kata', 'namespace': zone, 'labels': {common.LABEL: 'store', 'hoover.dev/store': store}},
            'spec': {'replicas': 1 if common.namespace_enabled(zone) else 0, 'serviceName': store,
                     'selector': {'matchLabels': {'hoover.dev/store': store}}, 'updateStrategy': {'type': 'OnDelete'},
                     'template': {'metadata': {'labels': labels}, 'spec': spec}, 'volumeClaimTemplates': [claim]}}


def clickhouse(zone):
    container = {
        'name': 'clickhouse', 'image': IMAGES['clickhouse'],
        'env': [secret_env('CH_ADMIN_PASSWORD', 'clickhouse-admin'), secret_env('CH_ZONE_PASSWORD', 'clickhouse-zone')] +
               [secret_env(service_users.env_name(s), f'clickhouse-{s}') for s in service_users.using('clickhouse')],
        'ports': [{'name': 'http', 'containerPort': 8123}, {'name': 'native', 'containerPort': 9000}],
        'volumeMounts': [{'name': 'config', 'mountPath': '/etc/clickhouse-server/config.d/hoover.xml', 'subPath': 'server.xml', 'readOnly': True},
                         {'name': 'config', 'mountPath': '/etc/clickhouse-server/users.d/hoover.xml', 'subPath': 'users.xml', 'readOnly': True}],
        'readinessProbe': {'httpGet': {'path': '/ping', 'port': 8123}, 'periodSeconds': 2, 'failureThreshold': 3},
        'resources': resources('clickhouse')}
    return [configmap('clickhouse', zone), service('clickhouse', zone, [('http', 8123), ('native', 9000)]),
            statefulset('clickhouse', zone, container, ['/entrypoint.sh'], '/var/lib/clickhouse',
                        extra_volumes=[{'name': 'config', 'configMap': {'name': 'clickhouse-config'}}])]


def manticore(zone, name='manticore'):
    """A Manticore daemon. Hoover refuses one host for text and vectors, so a zone has two of them."""
    container = {
        'name': 'manticore', 'image': IMAGES['manticore'],
        'env': [{'name': k, 'value': v} for k, v in MANTICORE_ENV.items()] + [
            secret_env('MT_ADMIN_PASSWORD', 'manticore-admin'), secret_env('MT_ZONE_PASSWORD', 'manticore-zone')],
        'ports': [{'name': 'sql', 'containerPort': 9306}, {'name': 'http', 'containerPort': 9308}],
        'readinessProbe': {'tcpSocket': {'port': 9306}, 'periodSeconds': 2, 'failureThreshold': 3},
        'resources': resources(name)}
    container['volumeMounts'] = [{'name': 'seed', 'mountPath': '/seed', 'readOnly': True}]
    # With authentication on, searchd starts with the users of auth.json in its data folder. A new daemon gets the
    # seed of creds.py with the user hoover_admin, and ../setup.py adds the zone user and the service users.
    # searchd writes an auth.json without users when none exists, so that file also gets the seed.
    start = ('grep -q username /var/lib/manticore/auth.json 2>/dev/null || '
             '{ cp /seed/auth.json /var/lib/manticore/auth.json && chmod 600 /var/lib/manticore/auth.json; }; '
             'exec /usr/local/bin/docker-entrypoint.sh searchd -c /etc/manticoresearch/manticore.conf.sh --nodetach')
    seed = {'name': 'seed', 'secret': {'secretName': SECRET, 'items': [{'key': 'manticore-seed', 'path': 'auth.json'}]}}
    return [service(name, zone, [('sql', 9306), ('http', 9308)]),
            statefulset(name, zone, container, ['sh', '-c', start], '/var/lib/manticore', user='999:999', extra_volumes=[seed])]


def garage(zone):
    container = {
        'name': 'garage', 'image': IMAGES['garage'],
        'env': [secret_env('GARAGE_RPC_SECRET', 'garage-rpc-secret'), secret_env('GARAGE_ADMIN_TOKEN', 'garage-admin-token')],
        'ports': [{'name': 's3', 'containerPort': 3900}, {'name': 'rpc', 'containerPort': 3901}, {'name': 'admin', 'containerPort': 3903}],
        'volumeMounts': [{'name': 'config', 'mountPath': '/etc/garage.toml', 'subPath': 'garage.toml', 'readOnly': True}],
        'readinessProbe': {'tcpSocket': {'port': 3900}, 'periodSeconds': 2, 'failureThreshold': 3},
        'resources': resources('garage')}
    return [configmap('garage', zone), service('garage', zone, [('s3', 3900), ('admin', 3903)]),
            statefulset('garage', zone, container, ['/garage', 'server'], '/var/lib/garage',
                        extra_volumes=[{'name': 'config', 'configMap': {'name': 'garage-config'}}])]


BUILDERS = {'clickhouse': clickhouse, 'manticore': manticore, 'manticore-vectors': lambda z: manticore(z, 'manticore-vectors'), 'garage': garage}


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ('apply', 'show') or sys.argv[2] not in BUILDERS:
        sys.exit(__doc__)
    command, store, zone = sys.argv[1:]
    objects = BUILDERS[store](zone)
    if command == 'show':
        print(json.dumps(objects, indent=1))
        return
    for o in objects:
        if o['kind'] == 'StatefulSet':
            # An existing store keeps its replica count, so an apply does not start a store that an operator stopped.
            current = common.kubectl('-n', zone, 'get', 'statefulset', o['metadata']['name'], '--ignore-not-found', '-o', 'json').strip()
            if current and o['spec']['replicas']:
                o['spec']['replicas'] = json.loads(current)['spec'].get('replicas', 1)
        # kubectl apply reports some unchanged StatefulSets as configured, so only a difference in kubectl diff applies.
        diff = subprocess.run(common.K + ['diff', '-f', '-'], input=json.dumps(o), capture_output=True, text=True)
        if diff.returncode == 0:
            continue
        if diff.returncode != 1:
            raise SystemExit(f'kubectl diff failed: {diff.stderr.strip()[-500:]}')
        result = common.kubectl('apply', '-f', '-', input=json.dumps(o)).strip()
        common.log('stores.jsonl', step='applied', object=result, zone=zone)


if __name__ == '__main__':
    main()
