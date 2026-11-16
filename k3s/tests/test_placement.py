"""The placement of every pod of the site (k3s/placement.py) with its CPU scale factor, the admission policy and the
in-place resize that apply it, the PriorityClass of the pods that can run on one node only, and the replica count of
the stateless processing services."""
import json
import random
import sys

import pytest
import yaml

from conftest import K3S, site_text, write_site

import config  # noqa: E402
import placement  # noqa: E402
import shared  # noqa: E402

sys.path.insert(0, str(K3S / 'zones'))

Pod, Node = placement.Pod, placement.Node


def remote(extra=''):
    return config.parse(site_text('remote.yml').replace('    gpu_pool:\n', f'{extra}    gpu_pool:\n'))


def site_nodes():
    """The three nodes of the test site of 2026-11-16: one slow node with 2 threads of allocatable CPU and two fast
    nodes, about 29 GiB each."""
    return [Node('slow', 29583, 2000), Node('fast-1', 29867, 11800), Node('fast-2', 28875, 11700)]


def running(memory, cpu, node, name):
    return Pod(((f'zone-a/deployment/{name}', 0),), memory, cpu, current=node, step='zone:zone-a')


def new(memory, cpu, name, **kw):
    return Pod(((f'zone-b/deployment/{name}', 0),), memory, cpu, step='zone:zone-b', **kw)


def full_site(extra):
    """The requests of the test site after the zone steps of 2026-11-16 (memory MiB, CPU millicores), as one running
    pod on each node, and the pods of extra."""
    return [running(20514, 1767, 'slow', 'on-slow'), running(29125, 5199, 'fast-1', 'on-fast-1'),
            running(28660, 5161, 'fast-2', 'on-fast-2')] + extra


# Solver ---------------------------------------------------------------------------------------------------------------

def test_a_site_that_fits_keeps_the_factor_1_and_the_running_pods_on_their_nodes():
    plan = placement.solve(site_nodes(), full_site([new(2592, 200, 'openproject-web')]))
    assert plan.factor == 1.0
    assert plan.where[:3] == ['slow', 'fast-1', 'fast-2']
    # Only the slow node has the memory, and 200m fits its free CPU.
    assert plan.where[3] == 'slow'


def test_the_numbers_of_the_test_site_need_the_factor_095():
    # The pod that stayed Pending: 2592 MiB and 277m. The slow node has the memory and 233m of CPU, the fast nodes
    # have the CPU and less than 1 GiB of memory.
    pods = full_site([new(2592, 277, 'openproject-web')])
    assert placement.pack(site_nodes(), pods, 1.0) is None
    plan = placement.solve(site_nodes(), pods)
    # 0.95 x (1767m + 277m) = 1942m fits the 2000m of the slow node. The factor stops at the first step that fits.
    assert plan.factor == 0.95 and plan.where[3] == 'slow'
    report = placement.report(plan)
    assert report['nodes']['slow']['cpu']['requested'] <= 2000
    assert report['new_pods'] == ['zone-b/deployment/openproject-web']


def test_memory_that_does_not_fit_fails_with_the_free_memory_of_each_node():
    with pytest.raises(placement.NoFit) as found:
        placement.solve(site_nodes(), full_site([new(10000, 10, 'large')]))
    text = str(found.value)
    assert 'Free memory per node' in text and 'slow 9069Mi' in text and 'fast-1 742Mi' in text
    assert 'zone-b/deployment/large 10000Mi' in text


def test_a_plan_never_moves_a_running_pod_and_says_when_a_move_would_fit():
    # Two nodes. A running pod fills most of node a, and the new pod fits only on a, where a move of the running pod
    # to b would make room.
    nodes = [Node('a', 1000, 1000), Node('b', 600, 1000)]
    pods = [Pod((('zone-a/deployment/x', 0),), 500, 10, current='a'), Pod((('zone-b/deployment/y', 0),), 700, 10)]
    with pytest.raises(placement.NoFit, match='A plan that moves running pods fits at the factor 1.00'):
        placement.solve(nodes, pods)


def test_a_joined_node_takes_the_new_pods_and_the_running_pods_stay():
    nodes = site_nodes() + [Node('fast-3', 30000, 11800)]
    plan = placement.solve(nodes, full_site([new(2592, 277, 'openproject-web'), new(1000, 300, 'other')]))
    assert plan.factor == 1.0
    assert plan.where == ['slow', 'fast-1', 'fast-2', 'fast-3', 'fast-3']


def test_the_new_pods_spread_their_cpu_evenly_over_the_capacity_of_the_nodes():
    nodes = [Node('small', 64000, 4000), Node('large', 64000, 12000)]
    pods = [Pod(((f'zone-a/deployment/p{i}', 0),), 1000, 500) for i in range(16)]
    plan = placement.solve(nodes, pods)
    report = placement.report(plan)
    # 8000m over 16000m: both nodes at 50 %.
    assert report['nodes']['small']['cpu']['share'] == report['nodes']['large']['cpu']['share'] == 0.5
    assert report['cpu_spread_points'] == 0


def test_improve_moves_new_pods_to_a_more_even_spread():
    nodes = [Node('a', 10000, 1000), Node('b', 10000, 1000)]
    pods = [Pod((('n/deployment/big', 0),), 100, 600), Pod((('n/deployment/s1', 0),), 100, 300),
            Pod((('n/deployment/s2', 0),), 100, 300)]
    where = placement.improve(nodes, pods, ['a', 'a', 'b'], 1.0, [0, 1, 2])
    assert sorted(where[1:]) == ['b', 'b'] and where[0] == 'a'


def test_the_same_inputs_give_the_same_plan_in_any_order():
    rng = random.Random(7)
    nodes = [Node(f'n{i}', rng.choice([16000, 32000]), rng.choice([4000, 12000])) for i in range(4)]
    pods = [Pod(((f'z/deployment/w{i}', 0),), rng.randint(100, 3000), rng.randint(10, 800),
                current=rng.choice(['', 'n0', 'n1'])) for i in range(40)]
    first = placement.solve(nodes, pods)
    shuffled = pods[:]
    rng.shuffle(shuffled)
    second = placement.solve(nodes, shuffled)
    assert first.factor == second.factor
    assert first.workloads() == second.workloads()
    assert placement.report(first) == placement.report(placement.solve(nodes, pods))


def test_clickhouse_and_manticore_take_different_nodes_when_the_cpu_spread_allows_it():
    nodes = [Node('a', 32000, 8000), Node('b', 32000, 8000)]
    pods = [Pod((('hoover-stores/statefulset/clickhouse', 0),), 2000, 100),
            Pod((('hoover-stores/statefulset/manticore', 0),), 2000, 100)]
    plan = placement.solve(nodes, pods)
    assert plan.where[0] != plan.where[1] and placement.pairs(plan.pods, plan.where) == 0


def test_a_site_of_10_nodes_and_400_pods_takes_a_few_seconds():
    import time
    rng = random.Random(3)
    nodes = [Node(f'n{i}', rng.choice([32768, 65536]), rng.choice([4000, 12000, 24000])) for i in range(10)]
    pods = [Pod(((f'z{i % 8}/deployment/w{i}', 0),), rng.randint(64, 1000), rng.randint(10, 300),
                current=f'n{rng.randint(0, 9)}' if i % 2 else '') for i in range(400)]
    started = time.monotonic()
    placement.solve(nodes, pods)
    assert time.monotonic() - started < 20


# Inputs ---------------------------------------------------------------------------------------------------------------

def workload(ns, kind, name, memory, cpu, replicas=1, labels=None, spec=None, claims=()):
    pod = {'containers': [{'name': 'c', 'resources': {'requests': {'memory': memory, 'cpu': cpu}}}], **(spec or {})}
    body = {'replicas': replicas, 'template': {'metadata': {'labels': labels or {'app': name}}, 'spec': pod}}
    if claims:
        body['volumeClaimTemplates'] = [{'metadata': {'name': c}} for c in claims]
    return {'kind': kind, 'metadata': {'name': name, 'namespace': ns}, 'spec': body}


def live_pod(ns, name, node, memory, cpu, owner=None, phase='Running'):
    meta = {'namespace': ns, 'name': name}
    if owner:
        meta['ownerReferences'] = [{'kind': owner[0], 'name': owner[1]}]
    spec = {'containers': [{'name': 'c', 'resources': {'requests': {'memory': memory, 'cpu': cpu}}}]}
    if node:
        spec['nodeName'] = node
    return {'metadata': meta, 'spec': spec, 'status': {'phase': phase}}


def cluster_nodes(*names, unschedulable=()):
    return {'items': [{'metadata': {'name': n}, 'spec': {'unschedulable': n in unschedulable},
                       'status': {'allocatable': {'memory': '32000Mi', 'cpu': '8'}}} for n in names]}


def test_the_inputs_pin_claims_and_named_nodes_and_count_the_other_pods_where_they_run():
    rendered = [
        workload('zone-a', 'StatefulSet', 'postgresql', '1000Mi', '50m', claims=('data',)),
        workload('zone-a', 'Deployment', 'web', '500Mi', '100m', replicas=2),
        workload('hoover-zone-a', 'Deployment', 'clamav', '2048Mi', '50m',
                 spec={'nodeSelector': {'kubernetes.io/hostname': 'edge'}}),
        workload('hoover-stores', 'StatefulSet', 'garage', '600Mi', '20m', replicas=2, labels={'s': 'garage'},
                 spec={'affinity': {'podAntiAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': [
                     {'labelSelector': {'matchLabels': {'s': 'garage'}}, 'topologyKey': 'kubernetes.io/hostname'}]},
                     'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [
                         {'matchExpressions': [{'key': 'kubernetes.io/hostname', 'operator': 'In',
                                                'values': ['a', 'b', 'gpu']}]}]}}}}),
        workload('zone-a', 'Deployment', 'idle', '100Mi', '10m', replicas=0),
    ]
    pods = {'items': [
        live_pod('monitoring', 'alloy-1', 'a', '100Mi', '20m', owner=('DaemonSet', 'alloy')),
        live_pod('zone-a', 'postgresql-0', 'b', '900Mi', '50m', owner=('StatefulSet', 'postgresql')),
        live_pod('zone-a', 'web-5f9c-x1', 'a', '500Mi', '100m', owner=('ReplicaSet', 'web-5f9c')),
        live_pod('zone-a', 'job-x', 'edge', '5000Mi', '10m', phase='Succeeded'),
        live_pod('zone-a', 'check', 'edge', '64Mi', '10m'),
    ]}
    claims = {'items': [{'metadata': {'namespace': 'zone-a', 'name': 'data-postgresql-0',
                                      'annotations': {'volume.kubernetes.io/selected-node': 'b'}}}]}
    nodes, found, live = placement.inputs(cluster_nodes('a', 'b', 'edge', 'gpu'), pods, claims, rendered,
                                          {'a', 'b', 'edge'}, zones=['zone-a'])
    by = {n.name: n for n in nodes}
    assert set(by) == {'a', 'b', 'edge'}
    # Pods of other installers stay where they run. A finished Job pod counts nothing.
    assert by['a'].fixed_memory == 100 and by['edge'].fixed_memory == 64 and by['b'].fixed_memory == 0
    pod = {p.keys[0]: p for p in found}
    assert pod[('zone-a/statefulset/postgresql', 0)].fixed == 'b'
    # A zone pod without a RuntimeClass runs in gVisor (the zone pod policy), so it counts the gVisor overhead. A store
    # pod of hoover-stores without a RuntimeClass runs with runc.
    gvisor = placement.runtime_overhead()['gvisor']
    assert pod[('zone-a/statefulset/postgresql', 0)].memory == 1000 + gvisor['memory']
    assert pod[('zone-a/statefulset/postgresql', 0)].cpu_fixed == gvisor['cpu']
    assert pod[('hoover-stores/statefulset/garage', 0)].memory == 600
    assert pod[('hoover-zone-a/deployment/clamav', 0)].fixed == 'edge'
    assert pod[('zone-a/deployment/web', 0)].current == 'a' and pod[('zone-a/deployment/web', 1)].current == ''
    garage = pod[('hoover-stores/statefulset/garage', 0)]
    assert garage.apart == 'hoover-stores/statefulset/garage' and garage.allowed == ('a', 'b')
    assert not any(k[0].endswith('/idle') for k in pod)
    assert sorted(s for s, *_ in live) == ['zone:zone-a', 'zone:zone-a']


def test_a_required_pod_affinity_joins_two_workloads_and_planned_zones_are_counted_only():
    rendered = [workload('hoover-zone-a', 'Deployment', 'operations', '1000Mi', '100m', labels={'n': 'ops'}),
                workload('hoover-zone-a', 'Deployment', 'schema', '200Mi', '20m', labels={'n': 'schema'},
                         spec={'affinity': {'podAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': [
                             {'labelSelector': {'matchLabels': {'n': 'ops'}}, 'topologyKey': 'kubernetes.io/hostname'}]}}})]
    nodes, found, _ = placement.inputs(cluster_nodes('a', 'b'), {'items': []}, {'items': []}, rendered, {'a', 'b'},
                                       zones=['zone-a'], planned=2)
    steered = [p for p in found if p.steer]
    # Two gVisor pods of the zone: their requests and two gVisor overheads.
    assert len(steered) == 1 and steered[0].memory == 1200 + 2 * placement.runtime_overhead()['gvisor']['memory']
    assert {k for k, _ in steered[0].keys} == {'hoover-zone-a/deployment/operations', 'hoover-zone-a/deployment/schema'}
    copies = [p for p in found if not p.steer]
    assert len(copies) == 1 and copies[0].key.startswith('planned-2:')
    plan = placement.solve(nodes, found)
    assert set(plan.workloads()) == {'hoover-zone-a/deployment/operations', 'hoover-zone-a/deployment/schema'}


def test_the_pod_request_splits_the_runtime_overhead_from_the_container_cpu():
    overhead = placement.runtime_overhead()
    assert overhead['kata']['memory'] == 640 and overhead['gvisor']['memory'] == 32
    spec = {'runtimeClassName': 'kata', 'containers': [{'name': 'c', 'resources': {'requests': {'memory': '1Gi', 'cpu': '100m'}}}],
            'initContainers': [{'name': 'i', 'resources': {'requests': {'memory': '2Gi', 'cpu': '10m'}}},
                               {'name': 's', 'restartPolicy': 'Always', 'resources': {'requests': {'memory': '64Mi', 'cpu': '20m'}}}]}
    memory, cpu, fixed = placement.pod_request(spec, overhead)
    # The plain init container is larger than the containers and the sidecar together.
    assert memory == 2048 + 640 and cpu == 120 and fixed == overhead['kata']['cpu']


# Order of the steps ---------------------------------------------------------------------------------------------------

def test_stores_that_fit_only_after_the_zones_shrink_run_after_the_zones():
    nodes = [Node('a', 4000, 4000)]
    # The zone pod shrinks from 3000 to 1000 MiB in its step. The new store pod needs 1500 MiB.
    pods = [Pod((('zone-a/deployment/web', 0),), 1000, 10, current='a', step='zone:zone-a'),
            Pod((('hoover-stores/deployment/temporal', 0),), 1500, 10, current='a', step='stores')]
    live = [('zone:zone-a', 'a', 3000, 10, 0), ('stores', 'a', 500, 10, 0)]
    plan = placement.Plan(1.0, ['a', 'a'], nodes, pods)
    assert placement.order(plan, live, ['zone-a']) == ('zones-first', [])
    live[0] = ('zone:zone-a', 'a', 1000, 10, 0)
    assert placement.order(plan, live, ['zone-a']) == ('stores-first', [])


# Application ----------------------------------------------------------------------------------------------------------

def plan_dict(factor, workloads):
    return {'factor': factor, 'workloads': workloads}


def test_the_configmap_holds_the_factor_and_the_planned_nodes_by_workload():
    cm = placement.configmap(plan_dict(0.85, {'zone-a/deployment/web': ['b', 'a', 'b'],
                                               'hoover-stores/statefulset/garage': ['a', 'b']}))
    assert cm['metadata'] == {'name': 'hoover-placement', 'namespace': 'kube-system',
                              'labels': {'app.kubernetes.io/name': 'hoover-placement'}}
    assert cm['data'] == {'factor': '0.85', 'zone-a.deployment.web': 'a,b', 'hoover-stores.statefulset.garage': 'a,b'}
    assert placement.store_nodes(plan_dict(1.0, {'hoover-stores/statefulset/garage': ['b', 'a']})) == {'garage': ['a', 'b']}


def test_the_resize_follows_the_template_times_the_factor_and_a_second_pass_changes_nothing():
    templates = placement.template_requests({'items': [
        {'kind': 'ReplicaSet', 'metadata': {'namespace': 'zone-a', 'name': 'web-5f9c'},
         'spec': {'template': {'spec': {'containers': [{'name': 'c', 'resources': {'requests': {'cpu': '100m'}}}],
                                        'initContainers': [{'name': 's', 'restartPolicy': 'Always',
                                                            'resources': {'requests': {'cpu': '33m'}}}]}}}}]})
    pod = live_pod('zone-a', 'web-5f9c-x1', 'a', '500Mi', '100m', owner=('ReplicaSet', 'web-5f9c'))
    pod['spec']['initContainers'] = [{'name': 's', 'restartPolicy': 'Always', 'resources': {'requests': {'cpu': '33m'}}}]
    other = live_pod('monitoring', 'x-1', 'a', '1Mi', '100m', owner=('ReplicaSet', 'x'))
    found = placement.resizes({'items': [pod, other]}, templates, 0.85)
    assert found == [('zone-a', 'web-5f9c-x1', {'containers': [{'name': 'c', 'resources': {'requests': {'cpu': '85m'}}}],
                                                 'initContainers': [{'name': 's', 'resources': {'requests': {'cpu': '29m'}}}]},
                      True)]
    pod['spec']['containers'][0]['resources']['requests']['cpu'] = '85m'
    pod['spec']['initContainers'][0]['resources']['requests']['cpu'] = '29m'
    pod['metadata']['annotations'] = {'hoover.dev/cpu-scale': '0.85'}
    assert placement.resizes({'items': [pod]}, templates, 0.85) == []
    # The admission policy rounds up to 1m in the same way.
    assert placement.scaled('33m', 0.85) == 29 and placement.scaled('1', 0.85) == 850


def test_the_admission_policy_reads_the_configmap_of_the_plan():
    docs = [d for d in yaml.safe_load_all((K3S / 'cluster/placement-policy.yaml').read_text()) if d]
    policy, binding = docs
    assert policy['kind'] == 'MutatingAdmissionPolicy' and policy['spec']['paramKind'] == {'apiVersion': 'v1', 'kind': 'ConfigMap'}
    assert binding['spec']['paramRef'] == {'name': 'hoover-placement', 'namespace': 'kube-system',
                                           'parameterNotFoundAction': 'Allow'}
    assert policy['spec']['matchConstraints']['resourceRules'][0]['operations'] == ['CREATE']
    assert 'kubectl apply -f placement-policy.yaml' in (K3S / 'cluster/setup.sh').read_text()


def test_the_plan_file_is_part_of_the_cluster_copy_of_the_state():
    import clusterstate
    assert 'placement/plan.json' in clusterstate.KINDS['configmap'][1]


# Placement in the render ----------------------------------------------------------------------------------------------

def by(items, kind, name):
    return next(i for i in items if i['kind'] == kind and i['metadata']['name'] == name)


def node_values(item):
    terms = item['spec']['template']['spec']['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']
    return terms['nodeSelectorTerms'][0]['matchExpressions'][0]['values']


def test_the_plan_becomes_the_node_affinity_and_every_store_pod_is_node_bound():
    import temporal
    s = remote('    stores: {nodes: [server-a, worker-b]}\n')
    plan = config.store_plan(s)
    placed = {'clickhouse': ['worker-b'], 'manticore': ['server-a'], 'manticore-vectors': ['worker-b'],
              'garage': ['server-a', 'worker-b'], 'temporal-cassandra': ['server-a'], 'temporal-opensearch': ['worker-b']}
    items = shared.objects(s, plan, 1, {}, placed) + temporal.objects(s, plan, 1, '{"keys": []}', placed)
    for store, nodes in placed.items():
        workload = by(items, 'StatefulSet', store)
        assert node_values(workload) == nodes
        assert workload['spec']['template']['spec']['priorityClassName'] == 'hoover-node-bound'
    # Temporal holds no data, so it keeps the default priority.
    assert 'priorityClassName' not in by(items, 'Deployment', 'temporal')['spec']['template']['spec']
    # Without a plan each store may use every store node with its tier: only worker-b has a fast tier.
    assert node_values(by(shared.objects(s, plan, 1, {}), 'StatefulSet', 'clickhouse')) == ['worker-b']
    assert node_values(by(shared.objects(s, plan, 1, {}), 'StatefulSet', 'garage')) == ['server-a', 'worker-b']


def test_the_zones_key_of_the_stores_and_the_replica_keys_are_read_and_checked():
    s = remote('    stores: {zones: 3}\n    replicas: {tika: 2, clamav: 1}\n')
    assert config.store_plan(s)['zones'] == 3 and config.store_plan(remote())['zones'] == 0
    assert s.replicas == {'tika': 2, 'clamav': 1}
    assert config.parse(config.dump(s)).replicas == {'tika': 2, 'clamav': 1}
    for text, message in (('{website: 2}', 'vars.replicas website is not a known key'),
                          ('{tika: 0}', 'vars.replicas tika = 0 must be a whole number of at least 1')):
        with pytest.raises(config.SiteError, match=message):
            remote(f'    replicas: {text}\n')


def render(tmp_path, replicas=None):
    import manifests
    path = write_site(tmp_path, 'remote.yml')
    t = manifests.target_from_site(path, 'zone-a', revision='0' * 40, state=tmp_path / 'no-state',
                                   nfs={'server-a': '10.43.0.10', 'worker-b': '10.43.0.11'})
    t.site.replicas = replicas or {}
    return json.loads(manifests.render(t))['items']


def test_the_stateless_services_run_their_replica_count_and_the_node_bound_pods_get_the_priority(tmp_path):
    items = render(tmp_path, {'tika': 3, 'clamav': 2})
    deployments = {i['metadata']['name']: i for i in items if i['kind'] == 'Deployment'}
    assert deployments['hoover4-tika']['spec']['replicas'] == 3
    assert deployments['hoover4-clamav']['spec']['replicas'] == 2
    assert deployments['hoover4-tesseract-cpu']['spec']['replicas'] == 1
    # The workers keep their own count (budget.worker_pods), and the website runs one pod.
    assert deployments['hoover-workers']['spec']['replicas'] == 1 and deployments['hoover-website']['spec']['replicas'] == 1
    bound = {n for n, d in deployments.items() if d['spec']['template']['spec'].get('priorityClassName') == 'hoover-node-bound'}
    # ClamAV names the public node. The operations worker mounts the backup claim.
    assert 'hoover4-clamav' in bound and 'hoover-operations' in bound
    assert 'hoover4-tika' not in bound and 'hoover-workers' not in bound
    for d in deployments.values():
        spec = d['spec']['template']['spec']
        named = spec.get('nodeSelector') or any('persistentVolumeClaim' in v for v in spec.get('volumes', []))
        assert bool(named) == (d['metadata']['name'] in bound), d['metadata']['name']


def test_clamav_tika_and_tesseract_request_their_measured_use(tmp_path):
    items = render(tmp_path)
    requests = {i['metadata']['name']: i['spec']['template']['spec']['containers'][0]['resources']['requests']['memory']
                for i in items if i['kind'] == 'Deployment'}
    import memory_requests
    measured = memory_requests.load()['hoover']
    for name in ('hoover4-clamav', 'hoover4-tika', 'hoover4-tesseract-cpu'):
        assert requests[name] == measured[f'deployment/{name}']['request'], name


def test_the_worker_gets_the_qpdf_cap_of_the_zone_ini(tmp_path):
    items = render(tmp_path)
    for name in ('hoover-workers', 'hoover-singletons'):
        env = {e['name']: e.get('value') for e in by(items, 'Deployment', name)['spec']['template']['spec']['containers'][0]['env']}
        assert env['HOOVER4_QPDF_MEM_LIMIT_BYTES'] == str(4 * 1024 ** 3)


def test_the_opendesk_pods_with_a_claim_or_a_named_node_get_the_priority():
    import postrender
    def doc(kind, spec, claims=False):
        d = {'kind': kind, 'metadata': {'name': 'x'}, 'spec': {'template': {'metadata': {}, 'spec': spec}}}
        if claims:
            d['spec']['volumeClaimTemplates'] = [{'metadata': {'name': 'data'}}]
        return d
    cases = [(doc('StatefulSet', {'containers': []}, claims=True), True),
             (doc('Deployment', {'containers': [], 'volumes': [{'name': 'd', 'persistentVolumeClaim': {'claimName': 'd'}}]}), True),
             (doc('Deployment', {'containers': [], 'nodeSelector': {'kubernetes.io/hostname': 'edge'}}), True),
             (doc('Deployment', {'containers': [], 'volumes': [{'name': 'e', 'emptyDir': {}}]}), False),
             (doc('Deployment', {'containers': [], 'priorityClassName': 'chart'}, claims=True), False)]
    for d, expected in cases:
        postrender.node_bound(d)
        assert (d['spec']['template']['spec'].get('priorityClassName') == 'hoover-node-bound') == expected


def test_the_priority_class_stays_below_topolvm_and_the_descheduler_keeps_its_pods():
    found = [d for d in yaml.safe_load_all((K3S / 'cluster/priorityclasses.yaml').read_text()) if d]
    assert [d['metadata']['name'] for d in found] == ['hoover-node-bound']
    assert 0 < found[0]['value'] < 1000000 and found[0]['globalDefault'] is False
    assert found[0]['preemptionPolicy'] == 'PreemptLowerPriority'
    policy = next(d for d in yaml.safe_load_all((K3S / 'cluster/descheduler.yaml').read_text())
                  if d and d['kind'] == 'ConfigMap')
    profile = yaml.safe_load(policy['data']['policy.yaml'])['profiles'][0]
    evictor = next(p for p in profile['pluginConfig'] if p['name'] == 'DefaultEvictor')
    assert evictor['args']['priorityThreshold'] == {'name': 'hoover-node-bound'}
    # The pass moves only a pod that started away from its planned node (a preferred node affinity).
    assert profile['plugins'] == {'deschedule': {'enabled': ['RemovePodsViolatingNodeAffinity']}}
    affinity = next(p for p in profile['pluginConfig'] if p['name'] == 'RemovePodsViolatingNodeAffinity')
    assert affinity['args']['nodeAffinityType'] == ['preferredDuringSchedulingIgnoredDuringExecution']
    assert 'kubectl apply -f priorityclasses.yaml' in (K3S / 'cluster/setup.sh').read_text()
