"""The memory requests from the load measurement, the Kata overhead, the rollout of the large Deployments and the
descheduler that runs only in a deployment."""
import json
import sys

import yaml

from conftest import K3S

sys.path.insert(0, str(K3S / 'zones'))
sys.path.insert(0, str(K3S / 'cluster'))
import cpu_requests  # noqa: E402
import deschedule  # noqa: E402
import memory_requests  # noqa: E402
import postrender  # noqa: E402

TABLE = {'margin': 1.2, 'measured': {'source': 'load of 2026-11-16'},
         'zone': {'deployment/web': {'peak': '900Mi', 'request': '1088Mi'},
                  'statefulset/db': {'peak': '700Mi', 'request': '864Mi'},
                  'deployment/cache': {'peak': '150Mi', 'request': '192Mi'}}}


def deployment(name, containers, runtime=None, replicas=1):
    spec = {'containers': containers}
    if runtime:
        spec['runtimeClassName'] = runtime
    return {'kind': 'Deployment', 'metadata': {'name': name},
            'spec': {'replicas': replicas, 'template': {'metadata': {}, 'spec': spec}}}


def box(name, request=None, limit=None):
    resources = {}
    if request:
        resources['requests'] = {'memory': request}
    if limit:
        resources['limits'] = {'memory': limit}
    return {'name': name, 'resources': resources}


def request_of(doc, name):
    return next(c for c in doc['spec']['template']['spec']['containers'] if c['name'] == name)['resources']['requests']['memory']


def test_the_request_is_the_peak_with_the_margin_rounded_up():
    assert memory_requests.request_of(900, 1.2) == 1088
    assert memory_requests.request_of(150, 1.2) == 192
    assert memory_requests.request_of(1, 1.2) == 32


def test_the_main_container_gets_the_table_value_minus_the_other_containers():
    doc = deployment('web', [box('web', '256Mi', '2Gi'), box('sidecar', '64Mi', '128Mi')])
    assert memory_requests.apply(doc, 'deployment/web', 'zone', main='web', table=TABLE)
    assert request_of(doc, 'web') == '1024Mi' and request_of(doc, 'sidecar') == '64Mi'
    annotations = doc['spec']['template']['metadata']['annotations']
    assert annotations[memory_requests.PEAK] == '900Mi'
    assert annotations[memory_requests.BASIS] == '1.2 x peak of the pod, load of 2026-11-16'
    # A second call gives the same result. A measured request also lowers a higher chart request.
    memory_requests.apply(doc, 'deployment/web', 'zone', main='web', table=TABLE)
    assert request_of(doc, 'web') == '1024Mi'
    high = deployment('web', [box('web', '3Gi', '4Gi')])
    memory_requests.apply(high, 'deployment/web', 'zone', table=TABLE)
    assert request_of(high, 'web') == '1088Mi'


def test_a_kata_pod_subtracts_the_fixed_overhead_that_the_scheduler_adds():
    fixed = memory_requests.kata_fixed()
    assert fixed == 640
    doc = deployment('db', [box('db', '128Mi', '1Gi')], runtime='kata')
    doc['kind'] = 'StatefulSet'
    memory_requests.apply(doc, 'statefulset/db', 'zone', table=TABLE)
    assert request_of(doc, 'db') == f'{864 - 640}Mi'
    # The pod request of a small Kata workload is the fixed overhead and the smallest container request.
    small = deployment('cache', [box('cache', '32Mi', '256Mi')], runtime='kata')
    memory_requests.apply(small, 'deployment/cache', 'zone', table=TABLE)
    assert request_of(small, 'cache') == f'{memory_requests.FLOOR}Mi'


def test_the_request_stays_at_most_the_limit_and_an_unmeasured_workload_keeps_its_request():
    doc = deployment('web', [box('web', '128Mi', '512Mi')])
    memory_requests.apply(doc, 'deployment/web', 'zone', table=TABLE)
    assert request_of(doc, 'web') == '512Mi'
    other = deployment('other', [box('other', '200Mi', '1Gi')])
    assert not memory_requests.apply(other, 'deployment/other', 'zone', table=TABLE)
    assert request_of(other, 'other') == '200Mi'


def test_the_measurement_takes_the_highest_peak_of_the_zones_and_names_a_low_limit(monkeypatch):
    owners = {'zone-a': {'web-1': 'deployment/web'}, 'zone-b': {'web-2': 'deployment/web'},
              'hoover-zone-a': {}, 'hoover-zone-b': {}}
    peaks = {'zone-a': {'web-1': 800.0}, 'zone-b': {'web-2': 1000.0}}
    limits = {'zone-a': {'web-1': 2048.0}, 'zone-b': {'web-2': 900.0}}
    monkeypatch.setattr(cpu_requests, 'owners', lambda ns, start, end: owners[ns])
    monkeypatch.setattr(memory_requests, 'peaks', lambda ns, start, end: peaks.get(ns, {}))
    monkeypatch.setattr(memory_requests, 'limits', lambda ns, end: limits.get(ns, {}))
    parts = [('zone', 'zone-a'), ('hoover', 'hoover-zone-a'), ('zone', 'zone-b'), ('hoover', 'hoover-zone-b')]
    table, low = memory_requests.measure(parts, 0, 600, 1.2)
    assert table['zone'] == {'deployment/web': {'peak': '1000Mi', 'request': '1216Mi'}}
    assert table['hoover'] == {}
    assert low == [{'part': 'zone', 'workload': 'deployment/web', 'peak': '1000Mi', 'limit': '900Mi'}]


def test_the_outside_peak_is_the_pod_minus_its_guest_containers(tmp_path):
    path = tmp_path / 'guest.jsonl'
    rows = [{'t': 10, 'kata': {'u': {'name': 'zone-a/db-0', 'pod': 900 << 20, 'c': {'db': [500 << 20, 0, 0]}}}},
            {'t': 20, 'kata': {'u': {'name': 'zone-a/db-0', 'pod': 1000 << 20, 'c': {'db': [700 << 20, 0, 0]}}}},
            {'t': 99, 'kata': {'u': {'name': 'zone-a/db-0', 'pod': 5000 << 20, 'c': {'db': [0, 0, 0]}}}}]
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    assert memory_requests.outside(path, 0, 50) == {'zone-a/db-0': 400.0}


def test_the_measured_table_covers_the_running_workloads_with_requests_above_their_peaks():
    table = memory_requests.load()
    assert table['margin'] >= 1.0
    for part in ('zone', 'hoover', 'site'):
        assert table[part], part
        for key, entry in table[part].items():
            peak, request = memory_requests.mebibytes(entry['peak']), memory_requests.mebibytes(entry['request'])
            assert request >= peak * table['margin'] - 1e-6, key
    # Every Kata workload of the measurement has its overhead under load.
    kata = [key for part in ('zone', 'hoover', 'site') for key, e in table[part].items() if 'outsidePeak' in e]
    assert "statefulset/clickhouse" in kata and "deployment/hoover-workers" in kata


def test_a_large_single_replica_deployment_rolls_without_a_second_pod():
    big = deployment('web', [box('web', '512Mi', '2Gi')])
    postrender.rollout(big)
    assert big['spec']['strategy'] == {'type': 'RollingUpdate', 'rollingUpdate': {'maxSurge': 0, 'maxUnavailable': 1}}
    small = deployment('web', [box('web', '511Mi', '2Gi')])
    postrender.rollout(small)
    assert 'strategy' not in small['spec']
    two = deployment('web', [box('web', '2Gi', '4Gi')], replicas=2)
    postrender.rollout(two)
    assert 'strategy' not in two['spec']
    recreate = deployment('web', [box('web', '2Gi', '4Gi')])
    recreate['spec']['strategy'] = {'type': 'Recreate'}
    postrender.rollout(recreate)
    assert recreate['spec']['strategy'] == {'type': 'Recreate'}


def test_the_measured_large_opendesk_deployments_roll_with_max_surge_0():
    """The openDesk Deployments whose measured request is 512 MiB or more, and the Deployments of NO_SURGE. The list
    names them."""
    table = memory_requests.load()
    large = []
    for key, entry in sorted(table['zone'].items()):
        if not key.startswith('deployment/'):
            continue
        name = key.split('/', 1)[1]
        doc = deployment(name, [box(name, '16Mi', '64Gi')])
        memory_requests.apply(doc, key, 'zone', table=table)
        postrender.rollout(doc)
        if memory_requests.mebibytes(request_of(doc, name)) >= postrender.MAX_SURGE_MEMORY or name in postrender.NO_SURGE:
            large.append(name)
            assert doc['spec']['strategy']['rollingUpdate'] == {'maxSurge': 0, 'maxUnavailable': 1}, name
        else:
            assert 'strategy' not in doc['spec'], name
    print('maxSurge 0:', ', '.join(large))
    assert 'openproject-web' in large and 'collabora' in large


def test_the_descheduler_runs_once_in_a_deployment_and_never_between_deployments():
    docs = [d for d in yaml.safe_load_all((K3S / 'cluster/descheduler.yaml').read_text()) if d]
    assert {d['kind'] for d in docs} == {'ServiceAccount', 'ClusterRole', 'ClusterRoleBinding', 'ConfigMap'}
    job = deschedule.job('descheduler-1', 300)
    spec = job['spec']['template']['spec']
    assert job['kind'] == 'Job' and job['spec']['activeDeadlineSeconds'] == 300 and job['spec']['backoffLimit'] == 0
    assert spec['restartPolicy'] == 'Never'
    assert not any(a.startswith('--descheduling-interval') for a in spec['containers'][0]['args'])
    setup = (K3S / 'cluster/setup.sh').read_text()
    assert 'kubectl -n kube-system delete deployment descheduler --ignore-not-found' in setup
    assert 'SOURCE_HASH' not in setup


def test_no_job_or_cronjob_gets_the_node_bound_priority():
    """A pod of hoover-node-bound preempts other pods, so only the deployment steps create one."""
    import postrender as pr
    cron = {'kind': 'CronJob', 'metadata': {'name': 'c'}, 'spec': {'jobTemplate': {'spec': {'template': {'spec': {
        'nodeSelector': {'kubernetes.io/hostname': 'n'}, 'containers': [box('c')],
        'volumes': [{'name': 'v', 'persistentVolumeClaim': {'claimName': 'x'}}]}}}}}}
    pr.node_bound(cron)
    assert 'priorityClassName' not in cron['spec']['jobTemplate']['spec']['template']['spec']
