"""The placement of the shared store pods (k3s/hoover/stores/placement.py), the PriorityClass of the pods that can run on
one node only, and the replica count of the stateless processing services."""
import itertools
import json
import random
import sys
import time

import pytest
import yaml

from conftest import K3S, site_text, write_site

import config  # noqa: E402
import placement  # noqa: E402
import shared  # noqa: E402

sys.path.insert(0, str(K3S / 'zones'))

ALL = ('a', 'b', 'c')


def three(base=(0, 0, 0)):
    return [placement.Node(n, 32000, 8000, base_memory=m) for n, m in zip(ALL, base)]


def oracle(nodes, stores, zone_memory, zone_cpu):
    """The best score of every plan, by a search of all plans without pruning."""
    caps = {n.name: n for n in nodes}
    choices = [list(itertools.combinations(s.candidates, s.count)) for s in stores]
    best = None
    for combo in itertools.product(*choices):
        mem = {n.name: n.base_memory for n in nodes}
        cpu = {n.name: n.base_cpu for n in nodes}
        fits = True
        for s, picked in zip(stores, combo):
            for n in picked:
                mem[n] += s.memory
                cpu[n] += s.cpu
                fits = fits and mem[n] <= caps[n].memory and cpu[n] <= caps[n].cpu
        if not fits:
            continue
        m, c = [mem[n.name] for n in nodes], [cpu[n.name] for n in nodes]
        cm, cc = [n.memory for n in nodes], [n.cpu for n in nodes]
        assign = {s.name: list(picked) for s, picked in zip(stores, combo)}
        score = (placement.per_mille(placement.level(m, cm, zone_memory)), placement.shared_pairs(assign),
                 placement.per_mille(placement.level(c, cc, zone_cpu)), placement.per_mille(placement.level(m, cm, 0)),
                 placement.per_mille(placement.level(c, cc, 0)))
        best = score if best is None or score < best else best
    return best


def test_the_zone_load_fills_the_nodes_from_the_lowest_share_up():
    assert placement.level([0, 0], [100, 100], 100) == 0.5
    # The fuller node keeps its share. The free one takes the zone load until both are equal.
    assert placement.level([60, 0], [100, 100], 40) == 0.6
    assert placement.level([60, 0], [100, 100], 100) == 0.8
    assert placement.level([30, 10], [100, 100], 0) == 0.3


def test_a_store_pod_that_fits_no_node_is_refused_with_the_free_capacity():
    nodes = three(base=(30000, 31000, 31500))
    with pytest.raises(placement.NoFit, match=r'no node plan fits the new store pods.*a 2000Mi.*clickhouse 1 x \(4000Mi'):
        placement.solve(nodes, [placement.Store('clickhouse', 1, 4000, 100, ALL)])
    # One pod of a sharded store on each node: three pods do not fit two nodes.
    with pytest.raises(placement.NoFit):
        placement.solve(three(), [placement.Store('garage', 3, 100, 10, ('a', 'b'))])


def test_each_new_pod_fits_its_node_and_a_sharded_store_uses_separate_nodes():
    nodes = three(base=(29000, 0, 0))
    plan = placement.solve(nodes, [placement.Store('garage', 2, 4000, 10, ALL), placement.Store('clickhouse', 1, 4000, 10, ('a', 'b'))])
    assert 'a' not in plan.nodes['garage'] and len(set(plan.nodes['garage'])) == 2
    assert plan.nodes['clickhouse'] == ['b']


def test_memory_balance_comes_before_the_separation_of_clickhouse_and_manticore():
    two = [placement.Node(n, 32000, 8000) for n in ('a', 'b')]
    stores = [placement.Store('clickhouse', 1, 2000, 10, ('a', 'b')), placement.Store('manticore', 1, 8000, 10, ('a', 'b')),
              placement.Store('manticore-vectors', 1, 8000, 10, ('a', 'b'))]
    # The two Manticore daemons on separate nodes give the best memory balance, so ClickHouse shares a node with one.
    plan = placement.solve(two, stores)
    assert plan.score[:2] == (313, 1) and plan.nodes['manticore'] != plan.nodes['manticore-vectors']
    assert plan.score == oracle(two, stores, 0, 0)
    # When the zone pods fill both nodes to the same share, memory balance is equal for every plan, and the
    # separation decides.
    plan = placement.solve(two, stores, zone_memory=40000)
    assert plan.score[1] == 0 and plan.nodes['manticore'] == plan.nodes['manticore-vectors']
    assert plan.score == oracle(two, stores, 40000, 0)


def test_an_existing_store_keeps_the_node_of_its_claim_and_a_better_plan_is_only_reported():
    stores = [placement.Store('clickhouse', 1, 6000, 10, ALL, fixed=('a',)), placement.Store('manticore', 1, 6000, 10, ALL, fixed=('a',)),
              placement.Store('garage', 3, 500, 10, ALL, fixed=('a', 'b'))]
    out = placement.report(three(), stores, 0, 0)
    assert out['stores']['clickhouse'] == ['a'] and out['stores']['manticore'] == ['a']
    assert out['stores']['garage'] == ['a', 'b', 'c']
    # A plan without the claims separates ClickHouse and Manticore. The report names the moves, and applies none.
    assert out['changes'] and {c['store'] for c in out['changes']} <= {'clickhouse', 'manticore'}
    assert all(c['nodes'] == ['a'] and c['better'] != ['a'] for c in out['changes'])
    # A claim on a full node stays. The search only checks the fit of new pods.
    full = three(base=(31000, 0, 0))
    plan = placement.solve(full, [placement.Store('clickhouse', 1, 6000, 10, ALL, fixed=('a',))])
    assert plan.nodes['clickhouse'] == ['a']


def test_the_search_finds_the_best_score_of_every_plan():
    rng = random.Random(7)
    for _ in range(40):
        nodes = [placement.Node(n, rng.choice([16000, 32000]), rng.choice([4000, 12000]), rng.randint(0, 9000),
                                rng.randint(0, 1500)) for n in ('a', 'b', 'c', 'd')[:rng.randint(2, 4)]]
        names = tuple(n.name for n in nodes)
        stores = [placement.Store('clickhouse', 1, rng.randint(1000, 8000), rng.randint(10, 800), names),
                  placement.Store('manticore', 1, rng.randint(1000, 8000), rng.randint(10, 800), names[:max(1, len(names) - 1)]),
                  placement.Store('manticore-vectors', 1, rng.randint(1000, 8000), 50, names),
                  placement.Store('garage', rng.randint(1, len(names)), 1500, 20, names)]
        zone_memory, zone_cpu = rng.choice([0, 20000, 60000]), rng.choice([0, 6000])
        best = oracle(nodes, stores, zone_memory, zone_cpu)
        if best is None:
            with pytest.raises(placement.NoFit):
                placement.solve(nodes, stores, zone_memory, zone_cpu)
        else:
            assert placement.solve(nodes, stores, zone_memory, zone_cpu).score == best


def test_ten_nodes_and_twelve_store_pods_take_less_than_two_seconds():
    rng = random.Random(3)
    nodes = [placement.Node(f'n{i}', rng.choice([32768, 65536, 131072]), rng.choice([4000, 8000, 16000]),
                            rng.randint(0, 3000), rng.randint(0, 500)) for i in range(10)]
    names = tuple(n.name for n in nodes)
    stores = [placement.Store('clickhouse', 1, 8000, 500, names), placement.Store('manticore', 1, 9000, 300, names),
              placement.Store('manticore-vectors', 1, 7000, 300, names), placement.Store('garage', 3, 1500, 50, names),
              placement.Store('temporal-cassandra', 3, 4000, 700, names), placement.Store('temporal-opensearch', 3, 2000, 200, names)]
    for zone_memory in (0, 100000, 300000):
        started = time.monotonic()
        placement.solve(nodes, stores, zone_memory, 20000)
        assert time.monotonic() - started < 2


# Cluster inputs --------------------------------------------------------------------------------------------------------

def pod(ns, name, node, memory, cpu='10m', labels=None, selector=None, claim=False, phase='Running', runtime=None):
    spec = {'containers': [{'name': 'c', 'resources': {'requests': {'memory': memory, 'cpu': cpu}}}]}
    if node:
        spec['nodeName'] = node
    if selector:
        spec['nodeSelector'] = {'kubernetes.io/hostname': selector}
    if claim:
        spec['volumes'] = [{'name': 'data', 'persistentVolumeClaim': {'claimName': 'data'}}]
    if runtime:
        spec['overhead'] = {'memory': '32Mi', 'cpu': '10m'}
    return {'metadata': {'namespace': ns, 'name': name, 'labels': labels or {}}, 'spec': spec, 'status': {'phase': phase}}


def remote(extra=''):
    return config.parse(site_text('remote.yml').replace('    gpu_pool:\n', f'{extra}    gpu_pool:\n'))


def test_the_inputs_separate_bound_pods_from_the_zone_load_and_add_planned_zones_and_replicas():
    site = remote()
    nodes = {'items': [{'metadata': {'name': n}, 'spec': {}, 'status': {'allocatable': {'memory': '32000Mi', 'cpu': '8'}}}
                       for n in ('server-a', 'worker-b', 'edge', 'gpu-1')]}
    pods = {'items': [
        pod('monitoring', 'alloy-1', 'server-a', '100Mi', '20m'),
        pod('hoover-stores', 'clickhouse-0', 'server-a', '640Mi', labels={'hoover.dev/store': 'clickhouse'}),
        pod('hoover-stores', 'temporal-x', 'worker-b', '448Mi', '290m', labels={'hoover.dev/store': 'temporal'}),
        pod('zone-a', 'postgresql-0', 'worker-b', '1000Mi', claim=True),
        pod('zone-a', 'xwiki-x', 'edge', '2000Mi', '100m'),
        pod('hoover-zone-a', 'hoover4-clamav-x', 'edge', '2048Mi', '50m', selector='edge',
            labels={'app.kubernetes.io/name': 'hoover4-clamav'}),
        pod('hoover-zone-a', 'hoover4-tika-x', 'server-a', '640Mi', '90m', labels={'app.kubernetes.io/name': 'hoover4-tika'}),
        pod('zone-a', 'job-x', 'edge', '5000Mi', phase='Succeeded'),
    ]}
    claims = {'items': [{'metadata': {'name': 'data-clickhouse-0', 'annotations': {'volume.kubernetes.io/selected-node': 'server-a'}}},
                        {'metadata': {'name': 'data-garage-1', 'annotations': {'volume.kubernetes.io/selected-node': 'edge'}}},
                        {'metadata': {'name': 'data-garage-0', 'annotations': {'volume.kubernetes.io/selected-node': 'worker-b'}}}]}
    scalable = {'hoover4-tika': (672, 100, False), 'hoover4-clamav': (2080, 60, True)}
    found, fixed, zone_memory, zone_cpu, details = placement.inputs(site, nodes, pods, claims, 2, {'hoover4-tika': 3}, scalable, 'edge')
    by = {n.name: n for n in found}
    # The GPU node runs no zone pod. A store pod with a volume is an item of the plan, not a base load.
    assert set(by) == {'server-a', 'worker-b', 'edge'}
    assert by['server-a'].base_memory == 100
    # Temporal holds no data and stays on its node. The claim of postgresql binds it.
    assert by['worker-b'].base_memory == 448 + 1000
    # The running zone keeps its ClamAV pod on the public node, and the planned second zone adds the estimate of the
    # public pods of zone-a: its ClamAV at its replica count.
    assert by['edge'].base_memory == 2080 + 2080
    # Over the nodes: the stateless pods of zone-a, its three Tika pods, and the second zone with the mean of zone-a
    # without its scaled pods, plus three Tika pods.
    assert zone_memory == 2000 + 3 * 672 + (1000 + 2000) + 3 * 672
    assert fixed == {'clickhouse': ('server-a',), 'garage': ('worker-b', 'edge')}
    assert details['running_zones'] == ['zone-a'] and details['planned_zones'] == 2


def test_a_site_without_zones_plans_with_the_zone_estimate():
    site = remote()
    nodes = {'items': [{'metadata': {'name': 'edge'}, 'spec': {}, 'status': {'allocatable': {'memory': '64Gi', 'cpu': '8'}}},
                       {'metadata': {'name': 'server-a'}, 'spec': {'unschedulable': True},
                        'status': {'allocatable': {'memory': '64Gi', 'cpu': '8'}}}]}
    scalable = {'hoover4-tika': (672, 100, False), 'hoover4-clamav': (2080, 60, True)}
    found, _, zone_memory, _, _ = placement.inputs(site, nodes, {'items': []}, {'items': []}, 1, {}, scalable, 'edge')
    # A cordoned node takes no pod.
    assert [n.name for n in found] == ['edge']
    estimate = placement.ZONE_ESTIMATE
    assert found[0].base_memory == estimate['public']['memory']
    assert zone_memory == estimate['memory'] - estimate['public']['memory']


def test_the_store_pod_request_counts_the_runtime_overhead_and_the_init_containers():
    overhead = placement.runtime_overhead()
    assert overhead['kata']['memory'] == 1024 and overhead['gvisor']['memory'] == 32
    s = remote('    stores: {nodes: [server-a, worker-b]}\n')
    plan = config.store_plan(s)
    items = shared.objects(s, plan, 1, {})
    requests = placement.store_requests(items, overhead)
    # ClickHouse: the container request and the Kata overhead. The blockmount init container is smaller.
    assert requests['clickhouse'][0] == 640 + 1024


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


def test_a_replica_count_that_does_not_fit_is_a_problem_of_the_deploy_check():
    s = remote('    replicas: {tika: 4, clamav: 2}\n')
    out = {'zones_fit': False, 'requested_share': {'memory': 1.08, 'cpu': 0.5},
           'nodes': {'edge': {'capacity': {'memory': 4000, 'cpu': 8000}, 'base_and_stores': {'memory': 4200, 'cpu': 100}}}}
    problems = shared.placement_problems(s, out)
    assert problems[0].startswith('vars.replicas (clamav 2, tika 4) does not fit: the zones and stores request 108% of the memory')
    assert 'does not fit the public node edge' in problems[1]
    # Without a count above 1 the same overcommit is no problem of vars.replicas.
    assert shared.placement_problems(remote(), out) == []


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
    assert (requests['hoover4-clamav'], requests['hoover4-tika'], requests['hoover4-tesseract-cpu']) == ('2048Mi', '640Mi', '512Mi')
    import manifests
    pods = manifests.scaled_pods()
    assert pods['hoover4-clamav'] == (2048 + 32, pods['hoover4-clamav'][1], True)
    assert set(pods) == {f'hoover4-{k}' for k in config.REPLICA_SERVICES}


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
    assert 'kubectl apply -f priorityclasses.yaml' in (K3S / 'cluster/setup.sh').read_text()
