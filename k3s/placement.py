#!/usr/bin/env python3
"""The placement of every pod of a site at deploy time, with memory as the hard limit and one CPU scale factor.

The step placement of deploy-k3s up, and deploy-k3s check, compute the plan before the stores and the zones change:
- Inputs: the allocatable memory and CPU of each schedulable node without the role gpu (the kubelet reserve is already
  subtracted, and the CPU counts threads of the fastest node, config.py kubelet_reserved()). When the reserve of the
  site differs from the reserve of the running kubelet, the plan uses the allocatable after the change (kubelet.py). The pods that this
  plan does not render stay on their nodes at their requests: the platform pods, the DaemonSet pods and the Job pods.
  The site workloads come from a new render at the scale factor 1: the shared stores (hoover/stores/shared.py,
  temporal.py), and for each enabled zone of the zone state the Hoover installation (hoover/manifests.py), the zone
  gate (zones/gate.py) and openDesk (helmfile template with zones/postrender.py). The zones that vars.stores zones
  plans beyond the zone state count as copies of the first zone. They are only counted.
- Hard rules: the memory requests on each node stay at most its allocatable memory. The CPU requests, multiplied by
  the factor, stay at most its allocatable CPU. A pod with a bound local claim (the annotation
  volume.kubernetes.io/selected-node), or with a node selector of one host, stays on that node. A pod with a required
  node affinity uses only those nodes. The pods of a workload with a required pod anti-affinity against itself use
  different nodes. Two workloads with a required pod affinity of one host are placed together.
- A running pod keeps its node when its new requests fit there. No plan moves a running pod, so a zone create, a zone
  delete or a new factor moves and restarts no pod of another zone. Only deploy-k3s up --rebalance moves running pods,
  in a maintenance window that the operator chooses (rebalance()).
- Factor: the largest value of 1, 1 - STEP, 1 - 2 x STEP, ... at which a plan fits. Memory requests never scale. When
  no factor fits, the message names the free memory of each node and the pods that do not fit (NoFit).
- Goal for the pods without a node: an even share of requested CPU per allocatable CPU on every node. pack() places
  them on the node with the lowest CPU share after the pod, and improve() moves and swaps them while the sum of
  (requested CPU)^2 / allocatable CPU falls. ClickHouse and each Manticore daemon on different nodes is the lowest goal
  (SEPARATE).
- The same inputs give the same plan.

The pod templates of the renders keep the CPU requests at the factor 1 and name no planned node, so a new plan changes
no template. The plan reaches the pods in three ways (apply()):
- The ConfigMap hoover-placement of kube-system holds the factor and the planned nodes of each workload. The
  MutatingAdmissionPolicy hoover-site-placement (cluster/placement-policy.yaml) reads it at the creation of each pod
  of the stores and the zones: it multiplies the CPU requests by the factor and adds a preferred node affinity of
  weight 100 for the planned nodes. The scheduler gives the node affinity the weight 50 (the k3s scheduler
  configuration of ansible/roles/hoover4_k3s), above the resource scores, so a pod starts on its planned node when
  that node has room, and on another node when it does not, for example when its node is down.
- Each running pod of a Deployment or StatefulSet of the stores and the zones gets the CPU requests of its template
  times the factor through an in-place resize (the resize subresource), which restarts no container (resizes()).
- placement/plan.json of the state folder keeps the plan, and the cluster copy of the state holds it
  (clusterstate.py). The stores step gives each store pod with a local volume a required node affinity of its
  planned nodes (store_nodes()).
apply() writes the ConfigMap and resizes a pod only when a value differs, so a second up changes nothing.

Order: the stores step runs before the zones. When the new store pods fit only after the zones have their new
requests, the plan says zones-first, and up runs the stores step after the zone steps (order()).

The render for the plan sets HOOVER4_PLACEMENT_RENDER=1. The openDesk render of a zone is kept in
placement/render-<zone>.json with a digest of its inputs, and a later plan with the same inputs uses it.

Usage: placement.py plan [--write] [--apply] [--rebalance]
    print the plan and the problems as JSON. --write keeps the plan in the state folder, --apply writes the ConfigMap
    and resizes the running pods. --rebalance (deploy-k3s up --rebalance) lets the plan move running pods when that
    makes the CPU shares more even, and with --apply moves them one at a time (rebalance()).
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

K3S = Path(__file__).resolve().parent
# The step of the CPU scale factor. A change of the factor resizes every running pod of the site, so the factor moves
# in steps that are larger than the accuracy of the measured CPU requests.
STEP = 0.05
MIN_FACTOR = 0.05
# The lowest goal: these store pairs on different nodes.
SEPARATE = (('hoover-stores/statefulset/clickhouse', 'hoover-stores/statefulset/manticore'),
            ('hoover-stores/statefulset/clickhouse', 'hoover-stores/statefulset/manticore-vectors'))
# The stores of hoover-stores whose pods keep a local volume. The stores step pins them to their planned nodes.
VOLUME_STORES = ('clickhouse', 'manticore', 'manticore-vectors', 'garage', 'temporal-cassandra', 'temporal-opensearch')
STORES_NAMESPACE = 'hoover-stores'
ZONE_NAMESPACE = re.compile(r'(hoover-)?zone-[a-z0-9]{1,12}')
PLAN_FILE = 'placement/plan.json'
RENDER_ENV = 'HOOVER4_PLACEMENT_RENDER'
CONFIGMAP = ('kube-system', 'hoover-placement')
SCALE = 'hoover.dev/cpu-scale'
HOST = 'kubernetes.io/hostname'
SELECTED = 'volume.kubernetes.io/selected-node'
CONTROLLERS = ('Deployment', 'StatefulSet')


class NoFit(SystemExit):
    """The memory requests of the site do not fit the nodes at any factor."""


# ----------------------------------------------------------------------------------------------------------------------
# Quantities and requests
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


def scaled(value, factor):
    """The CPU request value times the factor in millicores, rounded up to 1m, as the admission policy computes it."""
    return max(1, math.ceil(cpu_m(value) * factor - 1e-9))


def runtime_overhead():
    """{RuntimeClass: {'memory', 'cpu'}} of cluster/runtimeclasses.yaml."""
    import yaml
    out = {}
    for doc in yaml.safe_load_all((K3S / 'cluster' / 'runtimeclasses.yaml').read_text()):
        if doc and doc.get('kind') == 'RuntimeClass':
            fixed = (doc.get('overhead') or {}).get('podFixed') or {}
            out[doc['metadata']['name']] = {'memory': mem_mi(fixed.get('memory', 0)), 'cpu': cpu_m(fixed.get('cpu', 0))}
    return out


def pod_request(spec, overhead=None):
    """(MiB, container millicores, overhead millicores) that the scheduler counts for a pod spec: the containers and
    the sidecars, at least each init container, plus the overhead of the RuntimeClass. A container without a request
    has its limit as request. The factor scales the container part only."""
    def one(c, key, parse):
        res = c.get('resources') or {}
        return parse((res.get('requests') or {}).get(key, (res.get('limits') or {}).get(key, 0)))
    init = spec.get('initContainers') or []
    sidecars = [c for c in init if c.get('restartPolicy') == 'Always']
    plain = [c for c in init if c.get('restartPolicy') != 'Always']
    out = []
    for key, parse in (('memory', mem_mi), ('cpu', cpu_m)):
        main = sum(one(c, key, parse) for c in spec['containers'] + sidecars)
        out.append(max([main] + [one(c, key, parse) for c in plain]))
    if 'overhead' in spec:
        extra = {'memory': mem_mi(spec['overhead'].get('memory', 0)), 'cpu': cpu_m(spec['overhead'].get('cpu', 0))}
    else:
        extra = (overhead or {}).get(spec.get('runtimeClassName')) or {'memory': 0, 'cpu': 0}
    return out[0] + extra['memory'], out[1], extra['cpu']


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def workload_key(doc):
    return f"{doc['metadata'].get('namespace', '')}/{doc['kind'].lower()}/{doc['metadata']['name']}"


def store_nodes(plan):
    """{store: [node, ...]} of the volume stores in a plan."""
    out = {}
    for store in VOLUME_STORES:
        nodes = ((plan or {}).get('workloads') or {}).get(f'{STORES_NAMESPACE}/statefulset/{store}')
        if nodes:
            out[store] = sorted(set(nodes))
    return out


# ----------------------------------------------------------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------------------------------------------------------

@dataclass
class Node:
    name: str
    memory: float               # allocatable MiB
    cpu: float                  # allocatable millicores
    fixed_memory: float = 0.0   # requests of the pods that stay (platform, DaemonSet and Job pods)
    fixed_cpu: float = 0.0


@dataclass
class Pod:
    keys: tuple                 # ((workload key, replica), ...): more than one for workloads placed together
    memory: float
    cpu: float                  # container millicores at the factor 1
    cpu_fixed: float = 0.0      # millicores that the factor does not scale (RuntimeClass overhead, other installers)
    allowed: tuple = ()         # the nodes it may use. Empty: every node.
    fixed: str = ''             # the node it cannot leave
    current: str = ''           # the node of its running pod
    apart: str = ''             # pods with the same value use different nodes
    steer: bool = True          # False: counted, but the plan names no node for it
    step: str = ''              # the up step that renders it
    named: bool = False         # True: fixed by a node selector, not by a claim
    names: tuple = ()           # the names of its running pods

    @property
    def key(self):
        return self.keys[0][0]


@dataclass
class Plan:
    factor: float
    where: list                 # the node of each pod
    nodes: list
    pods: list

    def workloads(self):
        out = {}
        for pod, node in zip(self.pods, self.where):
            if not pod.steer:
                continue
            for key, replica in pod.keys:
                out.setdefault(key, []).append((replica, node))
        return {k: [n for _, n in sorted(v)] for k, v in sorted(out.items())}


def node_loads(nodes, pods, where, factor):
    mem = {n.name: n.fixed_memory for n in nodes}
    cpu = {n.name: n.fixed_cpu for n in nodes}
    for p, w in zip(pods, where):
        mem[w] += p.memory
        cpu[w] += p.cpu * factor + p.cpu_fixed
    return mem, cpu


def spread_points(nodes, pods, where, factor):
    """The gap between the highest and the lowest CPU share of a node, in points."""
    _, cpu = node_loads(nodes, pods, where, factor)
    values = [cpu[n.name] / n.cpu for n in nodes if n.cpu]
    return round((max(values) - min(values)) * 100, 1) if values else 0.0


def pairs(pods, where, separate=SEPARATE):
    nodes = {}
    for p, w in zip(pods, where):
        for key, _ in p.keys:
            nodes.setdefault(key, set()).add(w)
    return sum(len(nodes.get(a, set()) & nodes.get(b, set())) for a, b in separate)


def partners(pods, separate=SEPARATE):
    """{pod index: indexes of the pods that SEPARATE keeps on other nodes}."""
    by_key = {}
    for i, p in enumerate(pods):
        for key, _ in p.keys:
            by_key.setdefault(key, []).append(i)
    out = {}
    for a, b in separate:
        for i in by_key.get(a, []):
            for j in by_key.get(b, []):
                out.setdefault(i, set()).add(j)
                out.setdefault(j, set()).add(i)
    return out


# ----------------------------------------------------------------------------------------------------------------------
# Solver
# ----------------------------------------------------------------------------------------------------------------------

def pack(nodes, pods, factor, keep=True):
    """(a node for each pod that keeps the hard rules at the factor, the indexes of the pods that stay) or None.

    The fixed pods first. With keep, each running pod on its node when it fits there, largest memory first. Then the
    other pods, largest memory first, each on the node with the lowest CPU share after the pod.
    """
    names = [n.name for n in nodes]
    cap_m = {n.name: n.memory for n in nodes}
    cap_c = {n.name: n.cpu for n in nodes}
    mem = {n.name: n.fixed_memory for n in nodes}
    cpu = {n.name: n.fixed_cpu for n in nodes}
    where = [None] * len(pods)
    used = {}
    apart_of = partners(pods)

    def demand(p):
        return p.memory, p.cpu * factor + p.cpu_fixed

    def options(i):
        p = pods[i]
        return [n for n in (p.allowed or names) if n in cap_m and not (p.apart and n in used.get(p.apart, ()))]

    def fits(i, n):
        m, c = demand(pods[i])
        return mem[n] + m <= cap_m[n] + 1e-6 and cpu[n] + c <= cap_c[n] + 1e-6

    def put(i, n):
        m, c = demand(pods[i])
        mem[n] += m
        cpu[n] += c
        where[i] = n
        if pods[i].apart:
            used.setdefault(pods[i].apart, set()).add(n)

    for i, p in enumerate(pods):
        if p.fixed:
            if p.fixed not in cap_m:
                return None
            put(i, p.fixed)
    if any(mem[n] > cap_m[n] + 1e-6 or cpu[n] > cap_c[n] + 1e-6 for n in names):
        return None
    stay = {i for i, p in enumerate(pods) if p.fixed}
    rest = sorted((i for i, p in enumerate(pods) if not p.fixed),
                  key=lambda i: (-pods[i].memory, -pods[i].cpu, pods[i].keys))
    if keep:
        for i in list(rest):
            p = pods[i]
            if p.current and p.current in options(i) and fits(i, p.current):
                put(i, p.current)
                rest.remove(i)
                stay.add(i)
    for i in rest:
        choices = [n for n in options(i) if fits(i, n)]
        if not choices:
            return None
        m, c = demand(pods[i])
        put(i, min(choices, key=lambda n: ((cpu[n] + c) / cap_c[n], sum(1 for j in apart_of.get(i, ()) if where[j] == n),
                                           (mem[n] + m) / cap_m[n], names.index(n))))
    return where, stay


def improve(nodes, pods, where, factor, movable, rounds=400, swaps=True):
    """Move and swap the pods of movable while the sum of (requested CPU)^2 / allocatable CPU falls. A move that keeps
    that sum and separates a pair of SEPARATE also counts.

    Without swaps each step is one move that fits the nodes after the steps before it, so the moves can run one after
    the other on a full site (rebalance())."""
    where = list(where)
    cap_m = {n.name: n.memory for n in nodes}
    cap_c = {n.name: n.cpu for n in nodes}
    mem, cpu = node_loads(nodes, pods, where, factor)
    names = [n.name for n in nodes]
    movable = sorted(movable)
    apart_of = partners(pods)
    demand = [(p.memory, p.cpu * factor + p.cpu_fixed) for p in pods]
    groups = {}
    for i, p in enumerate(pods):
        if p.apart:
            groups.setdefault(p.apart, []).append(i)

    def allowed(i, n, ignore=None):
        p = pods[i]
        if p.allowed and n not in p.allowed:
            return False
        return not (p.apart and any(where[j] == n for j in groups[p.apart] if j not in (i, ignore)))

    def cost(n, c):
        return c * c / cap_c[n]

    def shared(i, n):
        return sum(1 for j in apart_of.get(i, ()) if where[j] == n)

    eps = 1e-9 * max(1.0, sum(cost(n, cpu[n]) for n in names))
    for _ in range(rounds):
        best = None
        for i in movable:
            a = where[i]
            m, c = demand[i]
            for b in names:
                if b == a or not allowed(i, b) or mem[b] + m > cap_m[b] + 1e-6 or cpu[b] + c > cap_c[b] + 1e-6:
                    continue
                gain = (cost(a, cpu[a] - c) + cost(b, cpu[b] + c) - cost(a, cpu[a]) - cost(b, cpu[b]),
                        shared(i, b) - shared(i, a))
                if (gain[0] < -eps or (abs(gain[0]) <= eps and gain[1] < 0)) and (best is None or gain < best[0]):
                    best = (gain, ('move', i, b))
        if best is None and swaps:
            for x, i in enumerate(movable):
                for j in movable[x + 1:]:
                    a, b = where[i], where[j]
                    if a == b or not allowed(i, b, j) or not allowed(j, a, i):
                        continue
                    mi, ci = demand[i]
                    mj, cj = demand[j]
                    if (mem[a] - mi + mj > cap_m[a] + 1e-6 or mem[b] - mj + mi > cap_m[b] + 1e-6
                            or cpu[a] - ci + cj > cap_c[a] + 1e-6 or cpu[b] - cj + ci > cap_c[b] + 1e-6):
                        continue
                    delta = cost(a, cpu[a] - ci + cj) + cost(b, cpu[b] - cj + ci) - cost(a, cpu[a]) - cost(b, cpu[b])
                    if delta < -eps and (best is None or (delta, 0) < best[0]):
                        best = ((delta, 0), ('swap', i, j))
        if best is None:
            break
        action = best[1]
        if action[0] == 'move':
            _, i, b = action
            a = where[i]
            mem[a] -= demand[i][0]
            cpu[a] -= demand[i][1]
            mem[b] += demand[i][0]
            cpu[b] += demand[i][1]
            where[i] = b
        else:
            _, i, j = action
            a, b = where[i], where[j]
            mem[a] += demand[j][0] - demand[i][0]
            cpu[a] += demand[j][1] - demand[i][1]
            mem[b] += demand[i][0] - demand[j][0]
            cpu[b] += demand[i][1] - demand[j][1]
            where[i], where[j] = b, a
    return where


def factors():
    out, value = [], 1.0
    while value >= MIN_FACTOR - 1e-9:
        out.append(round(value, 2))
        value -= STEP
    return out


def solve(nodes, pods, rebalance=False):
    """The Plan: the largest factor at which a plan fits with the running pods on their nodes, and the most even
    places for the other pods. Raise NoFit when no factor fits.

    rebalance (up --rebalance) also moves running pods: it starts from the same places and lets improve() move every
    pod that has no fixed node and belongs to one workload, so it moves a running pod only when the move makes the CPU
    shares more even. It uses single moves and no swaps: a swap needs free room for both pods at once, which a full
    site does not have. The step rebalance then moves these pods one at a time (rebalance())."""
    for factor in factors():
        found = pack(nodes, pods, factor)
        if found is None and rebalance:
            found = pack(nodes, pods, factor, keep=False)
        if found is None:
            continue
        where, stay = found
        movable = [i for i in range(len(pods)) if i not in stay]
        if rebalance:
            movable = [i for i, p in enumerate(pods) if not p.fixed and p.steer and len(p.keys) == 1]
        where = improve(nodes, pods, where, factor, movable, swaps=not rebalance)
        return Plan(factor=factor, where=where, nodes=nodes, pods=pods)
    moved = next((f for f in factors() if pack(nodes, pods, f, keep=False) is not None), None)
    hint = (f' A plan that moves running pods fits at the factor {moved:.2f}. No step moves a running pod. Stop or '
            'delete a zone, or add capacity.' if moved is not None else '')
    raise NoFit(memory_shortfall(nodes, pods) + hint)


def memory_shortfall(nodes, pods):
    """The message of a site whose requests do not fit: the free memory of each node after the pods that stay and the
    running pods on their nodes, and the pods that a placement by memory alone could not place."""
    free = {n.name: n.memory - n.fixed_memory for n in nodes}
    for p in pods:
        if p.fixed and p.fixed in free:
            free[p.fixed] -= p.memory
    missing, rest = [], []
    for p in sorted((p for p in pods if not p.fixed), key=lambda p: (-p.memory, p.keys)):
        if p.current in free and free[p.current] >= p.memory:
            free[p.current] -= p.memory
        else:
            rest.append(p)
    for p in rest:
        choices = [n for n in (p.allowed or free) if n in free and free[n] >= p.memory]
        if not choices:
            missing.append(p)
            continue
        free[min(choices, key=lambda n: free[n] - p.memory)] -= p.memory
    need = sum(p.memory for p in missing)
    text = ', '.join(f'{n} {v:.0f}Mi' for n, v in free.items())
    names = ', '.join(f'{p.key} {p.memory:.0f}Mi' for p in missing[:12]) + (' and more' if len(missing) > 12 else '')
    return (f'the site does not fit its nodes at any CPU scale factor with the running pods on their nodes. Free memory '
            f'per node after the pods that stay and a placement by memory: {text}. Pods without room ({len(missing)}, '
            f'{need:.0f}Mi): {names or "none, the CPU requests of the pods that stay are too high"}.')


# ----------------------------------------------------------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------------------------------------------------------

def owner_key(pod):
    """The workload key of a pod of a Deployment or StatefulSet, else None."""
    meta = pod['metadata']
    for ref in meta.get('ownerReferences') or []:
        if ref.get('kind') == 'StatefulSet':
            return f"{meta['namespace']}/statefulset/{ref['name']}"
        if ref.get('kind') == 'ReplicaSet':
            return f"{meta['namespace']}/deployment/{ref['name'].rsplit('-', 1)[0]}"
    return None


def step_of(namespace, zones):
    if namespace == STORES_NAMESPACE:
        return 'stores'
    for zone in zones:
        if namespace in (zone, f'hoover-{zone}'):
            return f'zone:{zone}'
    return ''


def required_hosts(spec):
    terms = (((spec.get('affinity') or {}).get('nodeAffinity') or {}).get('requiredDuringSchedulingIgnoredDuringExecution')
             or {}).get('nodeSelectorTerms') or []
    hosts = set()
    for term in terms:
        for e in term.get('matchExpressions') or []:
            if e.get('key') == HOST and e.get('operator') == 'In':
                hosts.update(e.get('values') or [])
    return tuple(sorted(hosts))


def matches(selector, labels):
    return bool(selector) and all(labels.get(k) == v for k, v in selector.items())


def pod_terms(spec, kind):
    terms = ((spec.get('affinity') or {}).get(kind) or {}).get('requiredDuringSchedulingIgnoredDuringExecution') or []
    return [((t.get('labelSelector') or {}).get('matchLabels') or {}) for t in terms if t.get('topologyKey') == HOST]


def inputs(nodes_json, pods_json, claims_json, rendered, eligible, zones=(), planned=0):
    """(Nodes, Pods, live) from the cluster objects and the rendered workloads.

    eligible: the node names that may run site pods. zones: the zone names in step order. planned: the zone count that
    the plan counts, at least the zones. live: [(step, node, MiB, container millicores, overhead millicores)] for each
    running pod that belongs to a rendered workload, for transition().
    """
    overhead = runtime_overhead()
    nodes = {}
    for item in sorted(nodes_json['items'], key=lambda i: i['metadata']['name']):
        name = item['metadata']['name']
        if name not in eligible or item['spec'].get('unschedulable'):
            continue
        alloc = item['status']['allocatable']
        nodes[name] = Node(name, mem_mi(alloc['memory']), cpu_m(alloc['cpu']))
    keys = {workload_key(d) for d in rendered}
    selected = {}
    for claim in claims_json['items']:
        meta = claim['metadata']
        node = (meta.get('annotations') or {}).get(SELECTED)
        if node:
            selected[(meta.get('namespace'), meta['name'])] = node
    running, live, waiting = {}, [], []
    for pod in sorted(pods_json['items'], key=lambda p: (p['metadata']['namespace'], p['metadata']['name'])):
        meta, spec, status = pod['metadata'], pod['spec'], pod.get('status') or {}
        if status.get('phase') in ('Succeeded', 'Failed') or meta.get('deletionTimestamp'):
            continue
        memory, cpu, fixed_cpu = pod_request(spec, overhead)
        node = spec.get('nodeName')
        key = owner_key(pod)
        if key in keys:
            if node:
                running.setdefault(key, []).append((meta['name'], node))
                live.append((step_of(meta['namespace'], zones), node, memory, cpu, fixed_cpu))
            continue
        if node in nodes:
            nodes[node].fixed_memory += memory
            nodes[node].fixed_cpu += cpu + fixed_cpu
        elif not node and status.get('phase') == 'Pending':
            # A pod of another installer that waits for a node. The plan counts it and names no node for it.
            waiting.append(Pod(((f"{meta['namespace']}/pod/{meta['name']}", 0),), memory, 0.0, cpu + fixed_cpu,
                               steer=False))
    pods, groups = [], {}
    for doc in sorted(rendered, key=workload_key):
        key = workload_key(doc)
        ns = doc['metadata']['namespace']
        spec = doc['spec']['template']['spec']
        labels = (doc['spec']['template'].get('metadata') or {}).get('labels') or {}
        replicas = doc['spec'].get('replicas', 1)
        if not replicas:
            continue
        if not spec.get('runtimeClassName') and ZONE_NAMESPACE.fullmatch(ns) and labels.get('hoover.dev/runtime') != 'runc':
            # The zone pod policy (zones/manifests/zone-pods.yaml) gives such a pod gVisor at admission.
            spec = dict(spec, runtimeClassName='gvisor')
        memory, cpu, fixed_cpu = pod_request(spec, overhead)
        named = (spec.get('nodeSelector') or {}).get(HOST, '')
        allowed = tuple(n for n in required_hosts(spec) if n in nodes)
        apart = key if any(matches(sel, labels) for sel in pod_terms(spec, 'podAntiAffinity')) else ''

        def ordinal(item, statefulset=doc['kind'] == 'StatefulSet'):
            tail = item[0].rsplit('-', 1)[-1]
            return (int(tail) if statefulset and tail.isdigit() else 0, item[1], item[0])
        now = sorted(running.get(key, []), key=ordinal)
        mine = []
        for i in range(replicas):
            fixed = named
            if not fixed:
                for template in doc['spec'].get('volumeClaimTemplates') or []:
                    fixed = fixed or selected.get((ns, f"{template['metadata']['name']}-{doc['metadata']['name']}-{i}"), '')
                for v in spec.get('volumes') or []:
                    if 'persistentVolumeClaim' in v:
                        fixed = fixed or selected.get((ns, v['persistentVolumeClaim']['claimName']), '')
            mine.append(Pod(((key, i),), memory, cpu, fixed_cpu, allowed, fixed, now[i][1] if i < len(now) else '',
                            apart, step=step_of(ns, zones), named=bool(named),
                            names=(now[i][0],) if i < len(now) else ()))
        groups[key] = (doc, labels, mine)
        pods.extend(mine)
    pods = together(pods, groups)
    # The zones that vars.stores zones plans beyond the zone state: copies of the first zone, counted only.
    if zones and planned > len(zones):
        first = [p for p in pods if p.step == f'zone:{zones[0]}']
        for n in range(len(zones) + 1, planned + 1):
            for p in first:
                pods.append(Pod(tuple((f'planned-{n}:{k}', r) for k, r in p.keys), p.memory, p.cpu, p.cpu_fixed,
                                p.allowed, p.fixed if p.named else '', '', f'planned-{n}:{p.apart}' if p.apart else '',
                                steer=False, named=p.named))
    return list(nodes.values()), pods + waiting, live


def together(pods, groups):
    """Join the pod of a workload with a required pod affinity of one host to the pod of the workload of its namespace
    that the affinity selects. Only workloads with one replica are joined."""
    by_key = {p.keys[0][0]: p for p in pods if len(p.keys) == 1}
    joined = {}
    for key, (doc, labels, mine) in sorted(groups.items()):
        spec = doc['spec']['template']['spec']
        ns = doc['metadata']['namespace']
        for selector in pod_terms(spec, 'podAffinity'):
            if matches(selector, labels):
                continue
            target = next((k for k, (d, l, _) in sorted(groups.items()) if k != key and d['metadata']['namespace'] == ns
                           and matches(selector, l)), None)
            if target and len(mine) == 1 and len(groups[target][2]) == 1:
                joined[key] = target
    absorbed = set()
    for key, target in sorted(joined.items()):
        seen = {key}
        while target in joined and target not in seen:
            seen.add(target)
            target = joined[target]
        a, b = by_key[key], by_key[target]
        if a is b:
            continue
        b.keys = b.keys + a.keys
        b.memory += a.memory
        b.cpu += a.cpu
        b.cpu_fixed += a.cpu_fixed
        b.fixed = b.fixed or a.fixed
        b.current = b.current or a.current
        b.names = b.names + a.names
        b.allowed = tuple(n for n in b.allowed if not a.allowed or n in a.allowed) or a.allowed
        absorbed.add(id(a))
    return [p for p in pods if id(p) not in absorbed]


# ----------------------------------------------------------------------------------------------------------------------
# Order of the up steps
# ----------------------------------------------------------------------------------------------------------------------

def transition(nodes, pods, where, factor, live, steps):
    """The pods that do not fit at the turn of their step, when the steps run in this order: [(step, workload key)].

    The state starts with the running pods, resized to the factor. Each step removes its running pods and starts the
    new pods: on the planned node when it has room, else on the node with the most free memory that has room.
    """
    cap = {n.name: (n.memory, n.cpu) for n in nodes}
    mem = {n.name: n.fixed_memory for n in nodes}
    cpu = {n.name: n.fixed_cpu for n in nodes}
    for _, node, m, c, o in live:
        if node in cap:
            mem[node] += m
            cpu[node] += c * factor + o
    for p, w in zip(pods, where):
        if not p.step:
            mem[w] += p.memory
            cpu[w] += p.cpu * factor + p.cpu_fixed
    failed = []
    for step in steps:
        for s, node, m, c, o in live:
            if s == step and node in cap:
                mem[node] -= m
                cpu[node] -= c * factor + o
        for p, w in zip(pods, where):
            if p.step != step:
                continue
            m, c = p.memory, p.cpu * factor + p.cpu_fixed

            def room(n):
                return mem[n] + m <= cap[n][0] + 1e-6 and cpu[n] + c <= cap[n][1] + 1e-6
            if room(w):
                choice = w
            elif p.fixed:
                choice = None
            else:
                choice = min((n for n in (p.allowed or sorted(cap)) if n in cap and room(n)),
                             key=lambda n: (mem[n] - cap[n][0], n), default=None)
            if choice is None:
                failed.append((step, p.key))
                continue
            mem[choice] += m
            cpu[choice] += c
    return failed


def order(plan, live, zones):
    """('stores-first' or 'zones-first', the pods that wait at the turn of their step in that order)."""
    zone_steps = [f'zone:{z}' for z in zones]
    first = transition(plan.nodes, plan.pods, plan.where, plan.factor, live, ['stores'] + zone_steps)
    if not any(step == 'stores' for step, _ in first):
        return 'stores-first', first
    second = transition(plan.nodes, plan.pods, plan.where, plan.factor, live, zone_steps + ['stores'])
    if len(second) < len(first):
        return 'zones-first', second
    return 'stores-first', first


# ----------------------------------------------------------------------------------------------------------------------
# Report and application
# ----------------------------------------------------------------------------------------------------------------------

def report(plan, order_name='stores-first', waits=()):
    mem, cpu = node_loads(plan.nodes, plan.pods, plan.where, plan.factor)
    nodes = {n.name: {'memory': {'allocatable': round(n.memory), 'requested': round(mem[n.name]),
                                 'share': round(mem[n.name] / n.memory, 3) if n.memory else None},
                      'cpu': {'allocatable': round(n.cpu), 'requested': round(cpu[n.name]),
                              'share': round(cpu[n.name] / n.cpu, 3) if n.cpu else None}}
             for n in plan.nodes}
    new = sorted({p.key for p in plan.pods if p.steer and not p.current and not p.fixed})
    return {'factor': plan.factor, 'step': STEP, 'nodes': nodes,
            'cpu_spread_points': spread_points(plan.nodes, plan.pods, plan.where, plan.factor),
            'separate_pairs_shared': pairs(plan.pods, plan.where), 'new_pods': new,
            'order': order_name, 'waits': [f'{s}: {k}' for s, k in waits], 'workloads': plan.workloads()}


def configmap(plan):
    """The ConfigMap of the admission policy: the factor and the planned nodes of each workload."""
    data = {'factor': f"{plan['factor']:.2f}"}
    for key, nodes in plan['workloads'].items():
        data[key.replace('/', '.')] = ','.join(sorted(set(nodes)))
    return {'apiVersion': 'v1', 'kind': 'ConfigMap',
            'metadata': {'name': CONFIGMAP[1], 'namespace': CONFIGMAP[0], 'labels': {'app.kubernetes.io/name': 'hoover-placement'}},
            'data': data}


def template_requests(controllers):
    """{(namespace, kind, name): {container: CPU request}} of the pod templates of ReplicaSets or StatefulSets."""
    out = {}
    for item in controllers['items']:
        spec = item['spec']['template']['spec']
        out[(item['metadata']['namespace'], item['kind'], item['metadata']['name'])] = {
            c['name']: ((c.get('resources') or {}).get('requests') or {}).get('cpu')
            for c in spec.get('containers', []) + [i for i in spec.get('initContainers') or [] if i.get('restartPolicy') == 'Always']}
    return out


def resizes(pods_json, templates, factor):
    """[(namespace, pod, change, annotate)] of the running pods of the stores and the zones whose CPU requests differ
    from their template times the factor, or whose annotation hoover.dev/cpu-scale differs. change holds the containers
    and sidecars with their new CPU request."""
    out = []
    for pod in sorted(pods_json['items'], key=lambda p: (p['metadata']['namespace'], p['metadata']['name'])):
        meta, spec = pod['metadata'], pod['spec']
        ns = meta['namespace']
        if not (ns == STORES_NAMESPACE or ZONE_NAMESPACE.fullmatch(ns)) or meta.get('deletionTimestamp'):
            continue
        if (pod.get('status') or {}).get('phase') != 'Running':
            continue
        ref = next((r for r in meta.get('ownerReferences') or [] if r.get('kind') in ('ReplicaSet', 'StatefulSet')), None)
        base = templates.get((ns, ref['kind'], ref['name'])) if ref else None
        if base is None:
            continue
        change = {}
        for part in ('containers', 'initContainers'):
            for c in spec.get(part) or []:
                if part == 'initContainers' and c.get('restartPolicy') != 'Always':
                    continue
                now = ((c.get('resources') or {}).get('requests') or {}).get('cpu')
                if now is None or base.get(c['name']) is None:
                    continue
                want = scaled(base[c['name']], factor)
                if abs(cpu_m(now) - want) > 1e-6:
                    change.setdefault(part, []).append({'name': c['name'], 'resources': {'requests': {'cpu': f'{want}m'}}})
        annotate = (meta.get('annotations') or {}).get(SCALE) != f'{factor:.2f}'
        if change or annotate:
            out.append((ns, meta['name'], change, annotate))
    return out


def kubectl(*args, input_text=None, check=True):
    command = ['kubectl']
    if os.environ.get('KUBECONFIG'):
        command += ['--kubeconfig', os.environ['KUBECONFIG']]
    result = subprocess.run(command + list(args), input=input_text, capture_output=True, text=True)
    if check and result.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:5])} failed: {(result.stderr or result.stdout).strip()[-400:]}')
    return result


def kubectl_json(*args):
    return json.loads(kubectl(*args, '-o', 'json').stdout)


def apply(plan):
    """Write the ConfigMap of the admission policy when it differs, then resize each running pod whose CPU requests
    differ from its template times the factor, and write the factor into its annotation. A resize restarts no
    container. Return a summary."""
    wanted = configmap(plan)
    found = kubectl('-n', CONFIGMAP[0], 'get', 'configmap', CONFIGMAP[1], '--ignore-not-found', '-o', 'json').stdout.strip()
    changed = not found or json.loads(found).get('data') != wanted['data']
    if changed:
        kubectl('apply', '-f', '-', input_text=json.dumps(wanted))
    templates = {}
    for kind in ('replicasets', 'statefulsets'):
        templates.update(template_requests(kubectl_json('get', kind, '-A')))
    resized, annotated, failed = 0, 0, []
    for ns, name, change, annotate in resizes(kubectl_json('get', 'pods', '-A'), templates, plan['factor']):
        if change:
            result = kubectl('-n', ns, 'patch', 'pod', name, '--subresource', 'resize', '--type', 'strategic',
                             '-p', json.dumps({'spec': change}), check=False)
            if result.returncode:
                failed.append(f'{ns}/{name}: {(result.stderr or result.stdout).strip()[-200:]}')
                continue
            resized += 1
        if annotate:
            result = kubectl('-n', ns, 'annotate', 'pod', name, '--overwrite', f"{SCALE}={plan['factor']:.2f}", check=False)
            annotated += result.returncode == 0
    return {'configmap_changed': changed, 'resized_pods': resized, 'annotated_pods': annotated, 'resize_failures': failed}


def moves(plan):
    """[(namespace, pod, workload key, from node, to node)] of the running pods that the plan puts on another node, in
    the order of the plan."""
    out = []
    for pod, node in zip(plan.pods, plan.where):
        if pod.current and node != pod.current and pod.names and len(pod.keys) == 1 and not pod.fixed:
            out.append((pod.key.split('/')[0], pod.names[0], pod.key, pod.current, node))
    return out


def free_room(nodes_json, pods_json):
    """{node: [free MiB, free millicores]} after the requests of the pods that run or wait on each node."""
    overhead = runtime_overhead()
    room = {i['metadata']['name']: [mem_mi(i['status']['allocatable']['memory']), cpu_m(i['status']['allocatable']['cpu'])]
            for i in nodes_json['items']}
    for pod in pods_json['items']:
        node = pod['spec'].get('nodeName')
        if node in room and (pod.get('status') or {}).get('phase') not in ('Succeeded', 'Failed'):
            memory, cpu, fixed = pod_request(pod['spec'], overhead)
            room[node][0] -= memory
            room[node][1] -= cpu + fixed
    return room


def workload_pods(key):
    """The pods of the workload key that are not being deleted."""
    namespace = key.split('/')[0]
    return [p for p in kubectl_json('-n', namespace, 'get', 'pods')['items']
            if owner_key(p) == key and not p['metadata'].get('deletionTimestamp')]


def ready(pod):
    return any(c['type'] == 'Ready' and c['status'] == 'True' for c in (pod.get('status') or {}).get('conditions') or [])


def rebalance(plan, timeout=600, pause=3):
    """Move the running pods of moves(plan) to their planned nodes, one at a time (up --rebalance).

    Each move takes the next pod whose planned node has room for its requests now, evicts it through the eviction API
    (which keeps a PodDisruptionBudget), and waits until the new pod of its workload is ready. The admission policy
    gives the new pod a preferred affinity for its planned node. The first failure stops the moves: a move that no
    node has room for, an eviction that the API refuses, a new pod on another node, or a pod that is not ready after
    timeout seconds. Return the summary, with the failure in 'error'.
    """
    import time
    overhead = runtime_overhead()
    pending, done = moves(plan), []
    while pending:
        pods_json = kubectl_json('get', 'pods', '-A')
        live = {(p['metadata']['namespace'], p['metadata']['name']): p for p in pods_json['items']}
        room = free_room(kubectl_json('get', 'nodes'), pods_json)
        chosen = None
        for move in pending:
            pod = live.get(move[:2])
            if pod is None or pod['spec'].get('nodeName') != move[3]:
                chosen = (move, None)
                break
            memory, cpu, fixed = pod_request(pod['spec'], overhead)
            if room.get(move[4], [0, 0])[0] >= memory and room[move[4]][1] >= cpu + fixed:
                chosen = (move, pod)
                break
        if chosen is None:
            return {'moved': done, 'pending': [f'{m[0]}/{m[1]} to {m[4]}' for m in pending],
                    'error': 'no planned node has room for the next move: ' + ', '.join(
                        f'{m[0]}/{m[1]} to {m[4]}' for m in pending[:5])}
        move, pod = chosen
        pending.remove(move)
        namespace, name, key, source, target = move
        if pod is None:
            # The pod is gone or on another node since the plan, so it does not move.
            continue
        before = {p['metadata']['uid'] for p in workload_pods(key)}
        eviction = {'apiVersion': 'policy/v1', 'kind': 'Eviction', 'metadata': {'name': name, 'namespace': namespace}}
        result = kubectl('create', '--raw', f'/api/v1/namespaces/{namespace}/pods/{name}/eviction', '-f', '-',
                         input_text=json.dumps(eviction), check=False)
        if result.returncode:
            return {'moved': done, 'error': f'the eviction of {namespace}/{name} failed: '
                                            f'{(result.stderr or result.stdout).strip()[-300:]}'}
        deadline = time.monotonic() + timeout
        while True:
            new = [p for p in workload_pods(key) if p['metadata']['uid'] not in before]
            if new and all(ready(p) for p in new) and all(p['metadata']['uid'] not in (pod['metadata']['uid'],)
                                                          for p in workload_pods(key)):
                break
            if time.monotonic() > deadline:
                return {'moved': done, 'error': f'the new pod of {key} was not ready {timeout} s after the eviction of '
                                                f'{namespace}/{name}'}
            time.sleep(pause)
        nodes = sorted({p['spec'].get('nodeName') for p in new})
        if nodes != [target]:
            return {'moved': done, 'error': f'the new pod of {key} started on {", ".join(nodes)}, not on its planned '
                                            f'node {target}'}
        done.append({'pod': f'{namespace}/{name}', 'workload': key, 'from': source, 'to': target,
                     'new_pod': new[0]['metadata']['name']})
        print(json.dumps({'moved': done[-1]}), file=sys.stderr, flush=True)
    return {'moved': done}


# ----------------------------------------------------------------------------------------------------------------------
# The render of the site at the factor 1
# ----------------------------------------------------------------------------------------------------------------------

def slim(doc):
    """The parts of a rendered workload that the plan reads. Environment values and commands stay out, so the kept
    render holds no secret."""
    spec = doc['spec']['template']['spec']

    def container(c):
        return {k: c[k] for k in ('name', 'resources', 'restartPolicy') if k in c}
    out_spec = {'containers': [container(c) for c in spec.get('containers') or []],
                'initContainers': [container(c) for c in spec.get('initContainers') or []]}
    for k in ('runtimeClassName', 'overhead', 'nodeSelector', 'affinity'):
        if spec.get(k):
            out_spec[k] = spec[k]
    out_spec['volumes'] = [{'name': v['name'], 'persistentVolumeClaim': v['persistentVolumeClaim']}
                           for v in spec.get('volumes') or [] if 'persistentVolumeClaim' in v]
    body = {'replicas': doc['spec'].get('replicas', 1),
            'template': {'metadata': {'labels': ((doc['spec']['template'].get('metadata') or {}).get('labels') or {})},
                         'spec': out_spec}}
    if doc['spec'].get('volumeClaimTemplates'):
        body['volumeClaimTemplates'] = [{'metadata': {'name': t['metadata']['name']}} for t in doc['spec']['volumeClaimTemplates']]
    return {'kind': doc['kind'], 'metadata': {'name': doc['metadata']['name'], 'namespace': doc['metadata'].get('namespace')},
            'spec': body}


def opendesk_digest(zone, private):
    """The digest of the inputs of the openDesk render of a zone: its values, its zone state entry, the operator
    settings, the openDesk release and the files of zones/ and cluster/runtimeclasses.yaml."""
    h = hashlib.sha256()
    for path in [private / 'zones' / zone / 'values.yaml', private / 'operator' / 'desired.json',
                 K3S / 'cluster' / 'runtimeclasses.yaml']:
        h.update(path.name.encode())
        h.update(path.read_bytes() if path.exists() else b'')
    entry = ((read_json(private / 'zone-state.json') or {}).get('zones') or {}).get(zone)
    h.update(json.dumps(entry, sort_keys=True).encode())
    for path in sorted(p for p in (K3S / 'zones').rglob('*') if p.is_file() and '__pycache__' not in p.parts):
        h.update(str(path.relative_to(K3S)).encode())
        h.update(path.read_bytes())
    for path in sorted((private / 'downloads').glob('opendesk-*')):
        h.update(path.name.encode())
    return h.hexdigest()


def opendesk_render(zone, private):
    """The slim openDesk workloads in one zone: the kept render when its digest matches, else a new helmfile template
    of every openDesk entry at the same time."""
    import yaml
    digest = opendesk_digest(zone, private)
    kept = private / 'placement' / f'render-{zone}.json'
    data = read_json(kept) or {}
    if data.get('digest') == digest:
        return data['workloads']
    if str(K3S / 'zones') not in sys.path:
        sys.path.insert(0, str(K3S / 'zones'))
    import zone as installer
    workloads = []
    for text in installer.template_entries(zone):
        for doc in yaml.safe_load_all(text):
            if isinstance(doc, dict) and doc.get('kind') in CONTROLLERS:
                doc['metadata'].setdefault('namespace', zone)
                workloads.append(slim(doc))
    workloads.sort(key=workload_key)
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(json.dumps({'digest': digest, 'workloads': workloads}, sort_keys=True))
    return workloads


def render_site(site, site_path, private):
    """(slim workloads, zones, planned zone count) of the site at the factor 1: the shared stores, and for each
    enabled zone the Hoover installation, the zone gate and openDesk."""
    os.environ[RENDER_ENV] = '1'
    for folder in ('zones', 'hoover/stores', 'hoover'):
        if str(K3S / folder) not in sys.path:
            sys.path.insert(0, str(K3S / folder))
    import config
    import gate
    import manifests
    import shared
    import temporal
    plan = config.store_plan(site)
    state = read_json(private / 'zone-state.json') or {'zones': {}}
    count = sum(1 for e in state['zones'].values() if e.get('stores') == 'site')
    out = shared.objects(site, plan, count, {}) + temporal.objects(site, plan, count, '{"keys": []}')
    zones = [z for z, e in state['zones'].items() if e.get('enabled')]
    # The render reads the NFS address of each data node. The address does not change a request.
    nfs = {n.name: '10.43.0.1' for n in site.nodes.values()}
    for zone in zones:
        target = manifests.target_from_site(str(site_path), zone, revision=os.environ.get('HOOVER4_REVISION') or manifests.NO_REVISION,
                                            nfs=nfs)
        out += manifests.objects(target) + gate.objects(zone)['items'] + opendesk_render(zone, private)
    workloads = [slim(d) for d in out if d.get('kind') in CONTROLLERS]
    return workloads, zones, max(plan['zones'], len(zones))


def compute(write=False, act=False, move=False):
    """The result of the command: the plan of the site, the problems as messages, and with act the summary of
    apply(). write keeps a changed plan in the state folder. move plans moves of running pods and, with act, runs them
    (rebalance())."""
    if str(K3S) not in sys.path:
        sys.path.insert(0, str(K3S))
    import config
    site_path = Path(os.environ['HOOVER4_SITE']).resolve()
    site = config.read(site_path)
    private = config.state_folder(site_path)
    rendered, zones, planned = render_site(site, site_path, private)
    eligible = {n.name for n in site.nodes.values() if not n.has('gpu')}
    import kubelet
    nodes_json, pods_json = kubectl_json('get', 'nodes'), kubectl_json('get', 'pods', '-A')
    # The plan fits the allocatable of each node after the change of its kubelet reserve, which up can apply after
    # the zone steps (kubelet.py).
    reserved = {n: v['kubelet_reserved'] for n, v in config.ansible_variables(site, private)['hoover4_nodes'].items()}
    rows = kubelet.changes(reserved, nodes_json, pods_json, kubelet.configz(lambda *a: kubectl(*a).stdout, list(reserved)))
    nodes, pods, live = inputs(kubelet.target_nodes(nodes_json, rows), pods_json,
                               kubectl_json('get', 'pvc', '-A'), rendered, eligible, zones, planned)
    plan = solve(nodes, pods, rebalance=move)
    order_name, waits = order(plan, live, zones)
    out = report(plan, order_name, waits)
    if move:
        out['moves'] = [f'{m[0]}/{m[1]}: {m[3]} to {m[4]}' for m in moves(plan)]
    before = read_json(private / PLAN_FILE) or {}
    problems = []
    if waits:
        problems.append(f'{len(waits)} pods of the plan have no room at the turn of their step ({order_name}): '
                        + ', '.join(out['waits'][:6]) + '. Their step waits until a later step frees the room.')
    if write and before != out:
        path = private / PLAN_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    result = {'placement': out, 'problems': problems, 'kept_factor': before.get('factor'), 'plan_changed': before != out,
              'kubelet': rows}
    if act:
        result['applied'] = apply(out)
        if move:
            result['rebalance'] = rebalance(plan)
    return result


def main(argv):
    if not argv or argv[0] != 'plan' or any(a not in ('--write', '--apply', '--rebalance') for a in argv[1:]):
        raise SystemExit(__doc__)
    try:
        result = compute(write='--write' in argv, act='--apply' in argv, move='--rebalance' in argv)
    except NoFit as error:
        result = {'placement': {}, 'problems': [str(error)]}
    print(json.dumps(result, sort_keys=True))
    if '--apply' in argv and (not result['placement'] or (result.get('applied') or {}).get('resize_failures')
                              or (result.get('rebalance') or {}).get('error')):
        sys.exit(1)


if __name__ == '__main__':
    main(sys.argv[1:])
