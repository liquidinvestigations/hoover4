"""The order of a change of the kubelet reserve of a node (deploy-k3s up, steps hosts:k3s and hosts:kubelet).

The k3s play writes the system-reserved value of each node (config.py kubelet_reserved()) and restarts k3s when it
changes. The restarted kubelet admits its running pods again against the new allocatable memory and CPU. It refuses
each pod that does not fit (OutOfmemory, OutOfcpu), and the controller of that pod starts a new pod on another node.
So a reserve that lowers the allocatable of a node must not reach the node while the pods there request more than
the new allocatable.

changes() compares, for each node, the reserve that the kubelet runs with (its configz) and the reserve of the site,
and computes the new allocatable: the current allocatable plus the current reserve minus the new reserve. The pods
of the node fit when their requests (with the RuntimeClass overhead) stay at most the new allocatable memory and CPU.
held() gives the value that keeps the current reserve of each node that would refuse pods. deploy-k3s up then runs
the k3s play with that value in the step hosts:k3s, lets the later steps lower the requests, and applies the new
reserve in the step hosts:kubelet after the zone steps. That step checks the requests again first, and fails without
a change when they still do not fit.
The placement plan (placement.py) uses the new allocatable of each node (target_nodes()), so the plan fits the nodes
after the change.
"""
import json
import subprocess

import placement


def parse(value):
    """{resource: quantity} of a system-reserved value such as 'memory=1472Mi,cpu=200m'."""
    return dict(part.split('=', 1) for part in (value or '').split(',') if '=' in part)


def joined(parts):
    return ','.join(f'{k}={v}' for k, v in parts.items())


def held(new, current):
    """The system-reserved value with the keys of new in their order and the values of current. The k3s play then
    writes the file of the running kubelet again, and k3s does not restart."""
    out = {k: current[k] for k in parse(new) if k in current}
    out.update({k: v for k, v in current.items() if k not in out})
    return joined(out)


def requested(pods_json, overhead=None):
    """{node: (MiB, millicores)} of the pods that the kubelet of each node admits: every pod that has not ended."""
    overhead = overhead if overhead is not None else placement.runtime_overhead()
    out = {}
    for pod in pods_json['items']:
        node = pod['spec'].get('nodeName')
        if not node or (pod.get('status') or {}).get('phase') in ('Succeeded', 'Failed'):
            continue
        memory, cpu, fixed = placement.pod_request(pod['spec'], overhead)
        total = out.setdefault(node, [0.0, 0.0])
        total[0] += memory
        total[1] += cpu + fixed
    return {k: tuple(v) for k, v in out.items()}


def changes(reserved, nodes_json, pods_json, configz, overhead=None):
    """{node: row} for each node of reserved ({node: new system-reserved value}) that the cluster has.

    configz: {node: {resource: quantity}}, the systemReserved of the running kubelet. A row names the current and the
    new reserve and allocatable, the requests of the pods of the node, lowered (the new allocatable memory or CPU is
    lower) and fits (the requests stay within the new allocatable).
    """
    load = requested(pods_json, overhead)
    out = {}
    for item in sorted(nodes_json['items'], key=lambda i: i['metadata']['name']):
        name = item['metadata']['name']
        if name not in reserved or name not in configz:
            continue
        current, new = configz[name], parse(reserved[name])
        alloc = item['status']['allocatable']
        memory = placement.mem_mi(alloc['memory'])
        cpu = placement.cpu_m(alloc['cpu'])
        new_memory = memory + placement.mem_mi(current.get('memory', '0')) - placement.mem_mi(new.get('memory', '0'))
        new_cpu = cpu + placement.cpu_m(current.get('cpu', '0')) - placement.cpu_m(new.get('cpu', '0'))
        used_memory, used_cpu = load.get(name, (0.0, 0.0))
        out[name] = {'reserved': {'current': joined(current), 'new': reserved[name]},
                     'allocatable': {'memory': [round(memory), round(new_memory)], 'cpu': [round(cpu), round(new_cpu)]},
                     'requested': {'memory': round(used_memory), 'cpu': round(used_cpu)},
                     'lowered': new_memory < memory or new_cpu < cpu,
                     'fits': used_memory <= new_memory and used_cpu <= new_cpu,
                     'hold': held(reserved[name], current)}
    return out


def hold(rows):
    """{node: system-reserved value that keeps the current reserve} for each node that would refuse pods."""
    return {name: row['hold'] for name, row in rows.items() if row['lowered'] and not row['fits']}


def target_nodes(nodes_json, rows):
    """nodes_json with the allocatable memory and CPU of each node of rows after its reserve change."""
    out = json.loads(json.dumps(nodes_json))
    for item in out['items']:
        row = rows.get(item['metadata']['name'])
        if row:
            item['status']['allocatable']['memory'] = f"{row['allocatable']['memory'][1]}Mi"
            item['status']['allocatable']['cpu'] = f"{row['allocatable']['cpu'][1]}m"
    return out


def kubectl_json(kubectl, *args):
    return json.loads(kubectl(*args))


def configz(kubectl, names):
    """{node: systemReserved} of the running kubelet of each node that answers."""
    out = {}
    for name in names:
        try:
            config = json.loads(kubectl('get', '--raw', f'/api/v1/nodes/{name}/proxy/configz'))['kubeletconfig']
        except (subprocess.CalledProcessError, ValueError, KeyError, SystemExit):
            continue
        out[name] = config.get('systemReserved') or {}
    return out


def read(site, private, kubectl, names=None):
    """The rows of changes() for the nodes of the site (or names) from the cluster. kubectl(*args) returns the
    output text of one kubectl command."""
    import config
    variables = config.ansible_variables(site, private)['hoover4_nodes']
    names = [n for n in (names or variables) if n in variables]
    reserved = {n: variables[n]['kubelet_reserved'] for n in names}
    return changes(reserved, kubectl_json(kubectl, 'get', 'nodes', '-o', 'json'),
                   kubectl_json(kubectl, 'get', 'pods', '-A', '-o', 'json'), configz(kubectl, names))
