#!/usr/bin/env python3
"""The deploy-time placement of the shared store pods that keep a local volume.

A store pod of hoover-stores with a TopoLVM volume stays on the node where its claim was bound first (VOLUME_STORES:
ClickHouse, the two Manticore daemons, Garage, Cassandra and OpenSearch). The stores step therefore chooses that node
before the first bind. solve() finds the best plan by an exact search, and shared.py writes the plan into the node
affinity of each StatefulSet. A sharded store (Garage, Cassandra, OpenSearch) gets a set of nodes and a required pod
anti-affinity, so each of its pods takes one node of the set. The default scheduler places every other pod.

Inputs (inputs()): the allocatable memory and CPU of each schedulable node that is not a GPU node (the kubelet already
lowers the CPU of a slow node by its speed factor, ../../config.py kubelet_reserved()), the requests of the pods that
stay on their node (platform pods, zone pods with a claim, zone pods that name a node), the requests of the store pods
from their render, the storage tier of each store (shared.tier()), and the zone load. The zone load is the requests of
the zones that run, and of the zones that vars.stores zones plans beyond them (ZONE_ESTIMATE, or the mean of the
running zones). vars.replicas of the site file adds the requests of the extra pods of each stateless service.

Hard rules: each new store pod fits the free memory and CPU of its node, the pods of a sharded store use different
nodes, and each pod uses a node with the storage tier of its store.
Soft goals, in this order, each compared only when the goals before it are equal:
1. Memory balance: the highest share of requested memory of a node, in per mille, after the zone pods fill the nodes
   from the least requested share up (level()). The default scheduler places the zone pods, so the plan assumes that
   they fill the free memory evenly.
2. ClickHouse and each Manticore daemon on different nodes (SEPARATE).
Three more goals decide between plans that are equal in goals 1 and 2: the CPU balance in the form of goal 1, then the
highest share of requested memory and of requested CPU of a node without the zone pods. When the zone pods can fill
every node to the same share, goal 1 is equal for every plan, and these goals spread the store pods.
Between equal plans the search keeps the first one. It tries the nodes with the lowest requested memory share first.

A store pod with a claim keeps the node of its claim (the annotation volume.kubernetes.io/selected-node). The search
keeps it there, and never moves data. When a plan without the claims has a better memory balance or separation
(goals 1 and 2), report() names the stores
that it would place on other nodes. The stores step does not apply that plan.
The search visits each choice of nodes of each store and drops a partial plan whose lower bound is not better than
the best plan found. The lower bound adds the requests of the store pods that the plan has not placed yet to the zone
load. A site of 10 nodes and 12 store pods takes less than one second (tests/test_placement.py).
"""
import itertools
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

K3S = Path(__file__).resolve().parents[2]
# The stores of hoover-stores whose pods keep a local volume. The Temporal pods hold no data.
VOLUME_STORES = ('clickhouse', 'manticore', 'manticore-vectors', 'garage', 'temporal-cassandra', 'temporal-opensearch')
# Soft goal 2: the store pairs that share a node only when no plan with a better memory balance separates them.
SEPARATE = (('clickhouse', 'manticore'), ('clickhouse', 'manticore-vectors'))
# The names of the goals of a score, in the order of comparison.
SCORE = ('memory_per_mille', 'shared_pairs', 'cpu_per_mille', 'memory_per_mille_without_zones',
         'cpu_per_mille_without_zones')
# The requests of one zone (openDesk and Hoover, with the runtime overhead of each pod) when no zone runs: a zone of a
# three-node site with the default applications and settings, measured after its create. public is the part of the pods
# that name the public node, the services that reach the internet (../manifests.py INTERNET).
ZONE_ESTIMATE = {'memory': 35139, 'cpu': 5120, 'public': {'memory': 2080, 'cpu': 60}}
# The label of the pods of the stateless services that vars.replicas scales (../manifests.py SCALABLE).
APP_LABEL = 'app.kubernetes.io/name'


class NoFit(SystemExit):
    """No plan places every new store pod. The message names the free capacity of each node and the need of each store."""


@dataclass
class Node:
    name: str
    memory: float          # allocatable MiB
    cpu: float             # allocatable millicores
    base_memory: float = 0  # requests of the pods that stay on the node
    base_cpu: float = 0
    public: bool = False


@dataclass
class Store:
    name: str
    count: int             # pods, one on each node
    memory: float          # MiB requested by one pod, with the runtime overhead
    cpu: float             # millicores requested by one pod, with the runtime overhead
    candidates: tuple      # the nodes with the storage tier of the store
    fixed: tuple = ()      # the nodes of the claims that exist


@dataclass
class Plan:
    nodes: dict            # {store: [node, ...]}
    score: tuple           # memory and CPU per mille with the zones, shared pairs, memory and CPU per mille without
    loads: dict = field(default_factory=dict)  # {node: {'memory', 'cpu'}}: the base and the store requests


def level(loads, caps, extra):
    """The highest share of capacity on a node after extra fills the nodes from the lowest share up.

    loads and caps are lists of the same length. The result is the share that the scheduler can reach at best when it
    places extra over the nodes. A node with no capacity does not count.
    """
    shares = sorted((l / c, l, c) for l, c in zip(loads, caps) if c > 0)
    if not shares:
        return math.inf
    top = shares[-1][0]
    if extra <= 0:
        return top
    used = capacity = 0.0
    for i, (_, l, c) in enumerate(shares):
        used += l
        capacity += c
        filled = (used + extra) / capacity
        if i + 1 == len(shares) or filled <= shares[i + 1][0]:
            return max(filled, top)
    return top


def per_mille(share):
    return math.inf if share == math.inf else math.ceil(share * 1000 - 1e-9)


def shared_pairs(assign, separate=SEPARATE):
    return sum(len(set(assign.get(a, ())) & set(assign.get(b, ()))) for a, b in separate)


def solve(nodes, stores, zone_memory=0.0, zone_cpu=0.0, separate=SEPARATE):
    """The best Plan for the store pods. Raise NoFit when no plan fits.

    nodes: the Nodes that can run zone pods. stores: the Stores. zone_memory and zone_cpu: the zone load that the
    scheduler places over the nodes. A fixed pod stays on its node, also when that node is full.
    """
    names = [n.name for n in nodes]
    index = {name: i for i, name in enumerate(names)}
    mem = [n.base_memory for n in nodes]
    cpu = [n.base_cpu for n in nodes]
    cap_m = [n.memory for n in nodes]
    cap_c = [n.cpu for n in nodes]
    assign = {}
    for s in stores:
        fixed = tuple(n for n in s.fixed if n in index)[:s.count]
        assign[s.name] = list(fixed)
        for n in fixed:
            mem[index[n]] += s.memory
            cpu[index[n]] += s.cpu
    order = sorted((s for s in stores if s.count > len(assign[s.name])), key=lambda s: (-s.memory * s.count, s.name))
    rest_m = sum(s.memory * (s.count - len(assign[s.name])) for s in order)
    rest_c = sum(s.cpu * (s.count - len(assign[s.name])) for s in order)
    best = {}

    def bound(rest_memory, rest_cpu):
        return (per_mille(level(mem, cap_m, zone_memory + rest_memory)), shared_pairs(assign, separate),
                per_mille(level(cpu, cap_c, zone_cpu + rest_cpu)), per_mille(level(mem, cap_m, rest_memory)),
                per_mille(level(cpu, cap_c, rest_cpu)))

    def visit(k, rest_memory, rest_cpu):
        score = bound(rest_memory, rest_cpu)
        if best and score >= best['score']:
            return
        if k == len(order):
            best.update(score=score, nodes={s: list(v) for s, v in assign.items()},
                        loads={n: {'memory': round(mem[i]), 'cpu': round(cpu[i])} for n, i in index.items()})
            return
        s = order[k]
        need = s.count - len(assign[s.name])
        options = [n for n in s.candidates if n in index and n not in assign[s.name]]
        options.sort(key=lambda n: ((mem[index[n]] + s.memory) / cap_m[index[n]], names.index(n)))
        placed = list(assign[s.name])
        for combo in itertools.combinations(options, need):
            if any(mem[index[n]] + s.memory > cap_m[index[n]] or cpu[index[n]] + s.cpu > cap_c[index[n]] for n in combo):
                continue
            for n in combo:
                mem[index[n]] += s.memory
                cpu[index[n]] += s.cpu
            assign[s.name] = placed + list(combo)
            visit(k + 1, rest_memory - s.memory * need, rest_cpu - s.cpu * need)
            for n in combo:
                mem[index[n]] -= s.memory
                cpu[index[n]] -= s.cpu
        assign[s.name] = placed

    visit(0, rest_m, rest_c)
    if not best:
        free = ', '.join(f'{n.name} {cap_m[i] - mem[i]:.0f}Mi and {cap_c[i] - cpu[i]:.0f}m' for i, n in enumerate(nodes))
        need = ', '.join(f'{s.name} {s.count - len(assign[s.name])} x ({s.memory:.0f}Mi, {s.cpu:.0f}m) on '
                         f'{"/".join(s.candidates) or "no node"}' for s in order)
        raise NoFit(f'no node plan fits the new store pods. Free before the new pods: {free}. New pods: {need}. '
                    'Add a node or memory, or lower the requests.')
    return Plan(nodes={s: sorted(v, key=names.index) for s, v in best['nodes'].items()}, score=best['score'],
                loads=best['loads'])


# ----------------------------------------------------------------------------------------------------------------------
# Requests
# ----------------------------------------------------------------------------------------------------------------------

def cpu_m(value):
    value = str(value)
    return float(value[:-1]) if value.endswith('m') else float(value) * 1000


def mem_mi(value):
    m = re.fullmatch(r'(\d+(?:\.\d+)?)(Ki|Mi|Gi|Ti|k|K|M|G|T)?', str(value).strip())
    if not m:
        raise ValueError(f'{value} is not a memory quantity')
    factor = {'Ki': 2 ** 10, 'Mi': 2 ** 20, 'Gi': 2 ** 30, 'Ti': 2 ** 40, 'k': 1e3, 'K': 1e3, 'M': 1e6, 'G': 1e9,
              'T': 1e12, None: 1}[m.group(2)]
    return float(m.group(1)) * factor / 2 ** 20


def runtime_overhead():
    """{RuntimeClass: {'memory', 'cpu'}} of ../../cluster/runtimeclasses.yaml."""
    import yaml
    out = {}
    for doc in yaml.safe_load_all((K3S / 'cluster' / 'runtimeclasses.yaml').read_text()):
        if doc and doc.get('kind') == 'RuntimeClass':
            fixed = (doc.get('overhead') or {}).get('podFixed') or {}
            out[doc['metadata']['name']] = {'memory': mem_mi(fixed.get('memory', 0)), 'cpu': cpu_m(fixed.get('cpu', 0))}
    return out


def pod_request(spec, overhead=None):
    """(MiB, millicores) that the scheduler counts for a pod spec: the containers and the sidecars, at least each init
    container, plus the overhead of the RuntimeClass. A container without a request has its limit as request."""
    def one(c, key, parse):
        res = c.get('resources') or {}
        value = (res.get('requests') or {}).get(key, (res.get('limits') or {}).get(key, 0))
        return parse(value)
    init = spec.get('initContainers') or []
    sidecars = [c for c in init if c.get('restartPolicy') == 'Always']
    plain = [c for c in init if c.get('restartPolicy') != 'Always']
    out = []
    for key, parse in (('memory', mem_mi), ('cpu', cpu_m)):
        main = sum(one(c, key, parse) for c in spec['containers'] + sidecars)
        main = max([main] + [one(c, key, parse) for c in plain])
        if 'overhead' in spec:
            main += parse(spec['overhead'].get(key, 0))
        elif overhead is not None:
            main += (overhead.get(spec.get('runtimeClassName')) or {}).get(key, 0)
        out.append(main)
    return tuple(out)


def store_requests(objects, overhead):
    """{store: (MiB, millicores)} of one pod of each store of VOLUME_STORES in the rendered objects."""
    return {o['metadata']['name']: pod_request(o['spec']['template']['spec'], overhead) for o in objects
            if o['kind'] == 'StatefulSet' and o['metadata']['name'] in VOLUME_STORES}


# ----------------------------------------------------------------------------------------------------------------------
# Cluster inputs
# ----------------------------------------------------------------------------------------------------------------------

def node_bound(pod):
    """The node that a pod cannot leave, or None: the node of a pod with a claim, or the node that its selector names."""
    spec = pod['spec']
    named = (spec.get('nodeSelector') or {}).get('kubernetes.io/hostname')
    if named:
        return named
    if any('persistentVolumeClaim' in v for v in spec.get('volumes') or []):
        return spec.get('nodeName') or None
    return None


def zone_of(namespace):
    match = re.fullmatch(r'(?:hoover-)?(zone-[a-z0-9]{1,12})', namespace)
    return match.group(1) if match else None


def inputs(site, nodes_json, pods_json, claims_json, planned_zones, replicas, scalable, public_node):
    """(Nodes, {store: fixed nodes}, zone memory, zone CPU, details) from the cluster objects.

    planned_zones: the zone count that the plan reserves for. replicas: {service: count} of vars.replicas. scalable:
    {service: (MiB, millicores, public)} of one pod of each scaled service, by its label value. public_node: the node of
    the services that reach the internet.
    """
    eligible = {n.name for n in site.nodes.values() if not n.has('gpu')}
    nodes = {}
    for item in nodes_json['items']:
        name = item['metadata']['name']
        if name not in eligible or item['spec'].get('unschedulable'):
            continue
        alloc = item['status']['allocatable']
        nodes[name] = Node(name, mem_mi(alloc['memory']), cpu_m(alloc['cpu']), public=name == public_node)
    zones = {}
    spread_m = spread_c = 0.0
    for pod in pods_json['items']:
        if pod['status'].get('phase') in ('Succeeded', 'Failed'):
            continue
        meta, spec = pod['metadata'], pod['spec']
        ns = meta['namespace']
        if ns == 'hoover-stores' and (meta.get('labels') or {}).get('hoover.dev/store') in VOLUME_STORES:
            continue
        memory, cpu = pod_request(spec)
        zone = zone_of(ns)
        bound = node_bound(pod)
        if zone:
            z = zones.setdefault(zone, {'memory': 0.0, 'cpu': 0.0, 'public': [0.0, 0.0], 'scaled': {}})
            z['memory'] += memory
            z['cpu'] += cpu
            app = (meta.get('labels') or {}).get(APP_LABEL)
            if ns.startswith('hoover-') and app in scalable:
                z['scaled'][app] = z['scaled'].get(app, 0) + 1
                # The plan adds the scaled pods of vars.replicas again below.
                z['memory'] -= memory
                z['cpu'] -= cpu
                continue
            if bound and bound == (spec.get('nodeSelector') or {}).get('kubernetes.io/hostname'):
                z['public'][0] += memory
                z['public'][1] += cpu
        else:
            # A platform pod stays on its node. Most of them are DaemonSet pods or have a claim.
            bound = spec.get('nodeName') or bound
        if bound in nodes:
            nodes[bound].base_memory += memory
            nodes[bound].base_cpu += cpu
        elif not bound:
            spread_m += memory
            spread_c += cpu
    # The bound pods of a running zone are in the base of their nodes. The scaled pods of each zone, at their
    # vars.replicas count, are added here: on the public node or over the nodes. A service that a zone does not run
    # adds nothing.
    for z in zones.values():
        for app, (memory, cpu, public) in scalable.items():
            count = replicas.get(app, 1) if app in z['scaled'] else 0
            if public and public_node in nodes:
                nodes[public_node].base_memory += memory * count
                nodes[public_node].base_cpu += cpu * count
            else:
                spread_m += memory * count
                spread_c += cpu * count
    # The zones that the plan reserves beyond the running zones.
    if zones:
        estimate = {'memory': sum(z['memory'] for z in zones.values()) / len(zones),
                    'cpu': sum(z['cpu'] for z in zones.values()) / len(zones),
                    'public': {'memory': sum(z['public'][0] for z in zones.values()) / len(zones),
                               'cpu': sum(z['public'][1] for z in zones.values()) / len(zones)}}
    else:
        estimate = _estimate_without_scaled(scalable)
    extra = max(0, planned_zones - len(zones))
    for _ in range(extra):
        public_m, public_c = estimate['public']['memory'], estimate['public']['cpu']
        for app, (memory, cpu, public) in scalable.items():
            count = replicas.get(app, 1)
            if public:
                public_m += memory * count
                public_c += cpu * count
            else:
                spread_m += memory * count
                spread_c += cpu * count
        if public_node in nodes:
            nodes[public_node].base_memory += public_m
            nodes[public_node].base_cpu += public_c
            spread_m += estimate['memory'] - estimate['public']['memory']
            spread_c += estimate['cpu'] - estimate['public']['cpu']
        else:
            spread_m += estimate['memory'] - estimate['public']['memory'] + public_m
            spread_c += estimate['cpu'] - estimate['public']['cpu'] + public_c
    fixed = {}
    for claim in claims_json['items']:
        name = claim['metadata']['name']
        node = (claim['metadata'].get('annotations') or {}).get('volume.kubernetes.io/selected-node')
        for store in VOLUME_STORES:
            if re.fullmatch(rf'data-{re.escape(store)}-\d+', name) and node:
                fixed.setdefault(store, []).append((int(name.rsplit('-', 1)[1]), node))
    fixed = {s: tuple(n for _, n in sorted(v)) for s, v in fixed.items()}
    details = {'running_zones': sorted(zones), 'planned_zones': planned_zones, 'zone_estimate': estimate,
               'spread': {'memory': round(spread_m), 'cpu': round(spread_c)}}
    return list(nodes.values()), fixed, spread_m, spread_c, details


def _estimate_without_scaled(scalable):
    """ZONE_ESTIMATE without the pods of the scaled services, which inputs() adds by their replica count."""
    out = {'memory': ZONE_ESTIMATE['memory'], 'cpu': ZONE_ESTIMATE['cpu'], 'public': dict(ZONE_ESTIMATE['public'])}
    for memory, cpu, public in scalable.values():
        out['memory'] -= memory
        out['cpu'] -= cpu
        if public:
            out['public']['memory'] -= memory
            out['public']['cpu'] -= cpu
    return out


def report(nodes, stores, zone_memory, zone_cpu):
    """The plan of the stores with their claims, and the stores that a plan without the claims would move, as a dict.

    A store without a claim takes the planned nodes. A store with claims keeps them: a better plan for it is only
    reported, because a move copies its data.
    """
    plan = solve(nodes, stores, zone_memory, zone_cpu)
    changes = []
    if any(s.fixed for s in stores):
        try:
            free = solve(nodes, [Store(s.name, s.count, s.memory, s.cpu, s.candidates) for s in stores], zone_memory, zone_cpu)
        except NoFit:
            free = None
        # Only a better memory balance or separation counts. The goals for equal plans do not justify a move.
        if free and free.score[:2] < plan.score[:2]:
            changes = [{'store': s.name, 'nodes': plan.nodes[s.name], 'better': free.nodes[s.name],
                        'score': dict(zip(SCORE[:2], plan.score[:2])), 'better_score': dict(zip(SCORE[:2], free.score[:2]))}
                       for s in stores if s.fixed and sorted(free.nodes[s.name]) != sorted(plan.nodes[s.name])]
    capacity = {n.name: {'memory': round(n.memory), 'cpu': round(n.cpu)} for n in nodes}
    total_m = sum(n.memory for n in nodes)
    total_c = sum(n.cpu for n in nodes)
    used_m = sum(v['memory'] for v in plan.loads.values()) + zone_memory
    used_c = sum(v['cpu'] for v in plan.loads.values()) + zone_cpu
    return {'stores': plan.nodes, 'score': dict(zip(SCORE, plan.score)),
            'nodes': {n: {'capacity': capacity[n], 'base_and_stores': plan.loads[n]} for n in capacity},
            'zones': {'memory': round(zone_memory), 'cpu': round(zone_cpu)},
            'requested_share': {'memory': round(used_m / total_m, 3) if total_m else None,
                                'cpu': round(used_c / total_c, 3) if total_c else None},
            'zones_fit': used_m <= total_m and used_c <= total_c, 'changes': changes}


if __name__ == '__main__':
    raise SystemExit('Run shared.py plan. It reads the cluster and prints the plan of the stores.')
