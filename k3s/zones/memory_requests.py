#!/usr/bin/env python3
"""The memory requests of the zone and site workloads from a load measurement, and the tool that measures them.

memory-requests.json holds, for each workload <kind>/<name> of a zone (part zone: openDesk, part hoover: the Hoover
installation and the processing pools of the site in hoover-pools) and of the shared stores of the site (part site:
the namespace hoover-stores), the numbers of a measured load:
  peak     the highest working set of the pod cgroup on the host in the load period and the quiet period after it.
           The pod cgroup holds every container of the pod. It also holds the gVisor sentry, and for Kata the VM with
           its guest kernel, the agent, Cloud Hypervisor, virtiofsd and the shim (sandbox_cgroup_only).
  request  margin x peak, rounded up to ROUND MiB. margin is a value of the file.
A Kata workload also has outsidePeak: the highest difference between the pod cgroup and the working set of its
containers in the guest (the kubelet summary). It is the Kata overhead of that workload under load.
node holds the memory reserve of the kubelet of a node (../config.py kubelet_reserved()): margin x the highest
difference between the node working set and the working set of its pods, for an agent and for the control plane
(server). It holds k3s, the system and the kernel.

apply() writes the request into a workload of a render. The pod requests the table value: the main container (the
container of the memory limits, else the first) gets the table value minus the requests of the other containers and,
for a Kata pod, minus the overhead.podFixed memory of the RuntimeClass kata (../cluster/runtimeclasses.yaml), which the
scheduler adds to the pod. So the pod request of a Kata workload is its measured peak with the margin, and at least the
podFixed memory. A workload without a measurement keeps the request of its installer. The request stays at most the
container limit. postrender.py, ../hoover/manifests.py and the store installers of ../hoover/stores call apply().

Usage of the tool. It reads Prometheus of the site (the service of the monitoring step) through the API server:
  memory_requests.py measure --zone ZONE [--zone ZONE...] --start TIME --end TIME [--guest FILE] [--write]
  memory_requests.py measure --site --start TIME --end TIME [--guest FILE] [--write]
TIME is a Unix time or an ISO 8601 time with a zone. start and end enclose the load and the quiet period after it.
--guest names the output of ../tools/load/guest_sampler.py for the same period, which gives outsidePeak and node.
With more zones, each workload gets its highest peak of the zones. Without --write the tool prints the table and the
workloads whose limit is below the measured peak. With --write it replaces the measured parts: zone and hoover with
--zone (record measured), site with --site (record measuredSite), and node with --guest. The margin stays.
"""
import json
import math
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE_PATH = HERE / 'memory-requests.json'
RUNTIME_CLASSES = HERE.parent / 'cluster' / 'runtimeclasses.yaml'
# The request is rounded up to this many MiB.
ROUND = 32
# The smallest request of a main container in MiB.
FLOOR = 16
SITE_NAMESPACE = 'hoover-stores'
POOLS_NAMESPACE = 'hoover-pools'
RECORDS = {'zone': 'measured', 'hoover': 'measured', 'site': 'measuredSite'}
PEAK = 'hoover.dev/memory-peak'
BASIS = 'hoover.dev/memory-request-basis'


def load():
    return json.loads(TABLE_PATH.read_text()) if TABLE_PATH.exists() else {'margin': 1.2, 'zone': {}, 'hoover': {}, 'site': {}}


def mebibytes(value):
    text = str(value)
    units = {'Ki': 1 / 1024, 'Mi': 1, 'Gi': 1024, 'Ti': 1 << 20, 'k': 1e3 / 2 ** 20, 'K': 1e3 / 2 ** 20,
             'M': 1e6 / 2 ** 20, 'G': 1e9 / 2 ** 20, 'T': 1e12 / 2 ** 20}
    for unit in ('Ki', 'Mi', 'Gi', 'Ti', 'k', 'K', 'M', 'G', 'T'):
        if text.endswith(unit):
            return float(text[:-len(unit)]) * units[unit]
    return float(text) / 2 ** 20


def quantity(mib):
    return f'{int(math.ceil(mib - 1e-9))}Mi'


def request_of(peak, margin):
    """margin x peak in MiB, rounded up to ROUND MiB."""
    return int(math.ceil(peak * margin / ROUND - 1e-9)) * ROUND


def kata_fixed():
    """MiB of overhead.podFixed of the RuntimeClass kata."""
    text = RUNTIME_CLASSES.read_text()
    block = text[text.index('name: kata\n'):]
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith('memory:'):
            return mebibytes(stripped.split(':', 1)[1].strip())
    return 0.0


def pod_spec(doc):
    if doc['kind'] == 'CronJob':
        return doc['spec']['jobTemplate']['spec']['template']['spec']
    return doc['spec']['template']['spec']


def template_metadata(doc):
    template = doc['spec']['jobTemplate']['spec']['template'] if doc['kind'] == 'CronJob' else doc['spec']['template']
    if not template.get('metadata'):
        template['metadata'] = {}
    return template['metadata']


def container_request(c):
    return mebibytes(((c.get('resources') or {}).get('requests') or {}).get('memory', 0))


def apply(doc, key, part, main=None, table=None):
    """Write the measured memory request and its basis into a workload. key is <kind>/<name>, part zone, hoover or
    site. main names the main container. Return True when the table has the workload. A second call gives the same
    result."""
    table = table or TABLE
    entry = table.get(part, {}).get(key)
    if not entry:
        return False
    spec = pod_spec(doc)
    containers = spec.get('containers') or []
    if not containers:
        return True
    chosen = next((c for c in containers if c['name'] == main), containers[0])
    sidecars = [c for c in spec.get('initContainers') or [] if c.get('restartPolicy') == 'Always']
    others = sum(container_request(c) for c in containers + sidecars if c is not chosen)
    # The VM of a Kata pod runs in the pod cgroup, so the measured peak holds the memory of the overhead.
    fixed = kata_fixed() if spec.get('runtimeClassName') == 'kata' else 0.0
    wanted = max(FLOOR, mebibytes(entry['request']) - others - fixed)
    resources = chosen.setdefault('resources', {})
    limit = (resources.get('limits') or {}).get('memory')
    if limit and wanted > mebibytes(limit):
        wanted = mebibytes(limit)
    resources.setdefault('requests', {})['memory'] = quantity(wanted)
    metadata = template_metadata(doc)
    if not metadata.get('annotations'):
        metadata['annotations'] = {}
    annotations = metadata['annotations']
    annotations[PEAK] = entry['peak']
    annotations[BASIS] = f"{table['margin']} x peak of the pod, {table.get(RECORDS[part], {}).get('source', 'measured')}"
    return True


TABLE = load()


# ----------------------------------------------------------------------------------------------------------------------
# Measurement
# ----------------------------------------------------------------------------------------------------------------------

def pod_memory(namespace):
    # The pod cgroup has no container and no image label.
    return f'container_memory_working_set_bytes{{namespace="{namespace}",container="",image=""}}'


def peaks(namespace, start, end):
    """{pod: MiB} of the highest working set of each pod cgroup between start and end."""
    import cpu_requests
    window = f'{int(end - start)}s'
    return {r['metric']['pod']: float(r['value'][1]) / 2 ** 20
            for r in cpu_requests.query(f'max_over_time({pod_memory(namespace)}[{window}])', end) if 'pod' in r['metric']}


def limits(namespace, end):
    """{pod: MiB} of the memory limit of each pod cgroup: the sum of the container memory limits and the overhead of the
    RuntimeClass."""
    import cpu_requests
    out = {r['metric']['pod']: float(r['value'][1]) / 2 ** 20 for r in cpu_requests.query(
        f'sum by (pod) (last_over_time(kube_pod_container_resource_limits{{namespace="{namespace}",resource="memory"}}[1h]))', end)}
    for r in cpu_requests.query(f'last_over_time(kube_pod_overhead_memory_bytes{{namespace="{namespace}"}}[1h])', end):
        if r['metric'].get('pod') in out:
            out[r['metric']['pod']] += float(r['value'][1]) / 2 ** 20
    return out


def outside(path, start, end):
    """{namespace/pod: MiB} of the highest difference between the pod and the working set of its containers, from the
    output of ../tools/load/guest_sampler.py."""
    out = {}
    for line in Path(path).read_text().splitlines():
        row = json.loads(line)
        if not start <= row.get('t', 0) <= end:
            continue
        for pod in (row.get('kata') or {}).values():
            inner = sum((c[0] or 0) for c in pod['c'].values())
            if pod.get('pod') is None:
                continue
            value = (pod['pod'] - inner) / 2 ** 20
            out[pod['name']] = max(out.get(pod['name'], 0.0), value)
    return out


def control_planes():
    """The names of the nodes with the role control-plane."""
    import subprocess
    out = subprocess.run(['kubectl', 'get', 'nodes', '-l', 'node-role.kubernetes.io/control-plane', '-o', 'name'],
                         capture_output=True, text=True)
    return {line.split('/', 1)[1] for line in out.stdout.split()}


def node_reserve(path, start, end, margin, servers):
    """{'agent': quantity, 'server': quantity}: margin x the highest difference between the node working set and the
    working set of the pods, from the output of ../tools/load/guest_sampler.py. It holds k3s, the system and the
    kernel. servers names the control plane nodes."""
    peak = {}
    for line in Path(path).read_text().splitlines():
        row = json.loads(line)
        if 'error' in row or not start <= row.get('t', 0) <= end or not row.get('ws'):
            continue
        role = 'server' if row['node'] in servers else 'agent'
        value = (row['ws'] - ((row.get('sys') or {}).get('pods') or 0)) / 2 ** 20
        peak[role] = max(peak.get(role, 0.0), value)
    return {role: f'{request_of(value, margin)}Mi' for role, value in sorted(peak.items())}


def measure(parts, start, end, margin, guest=None):
    """Measure each (part, namespace) of parts. A part with more namespaces, for example the zone part of two zones,
    takes the highest peak of each workload. Return the table of each part and the workloads whose limit is below the
    peak."""
    import cpu_requests
    out, low = {}, []
    extra = outside(guest, start, end) if guest else {}
    founds = {}
    for part, namespace in parts:
        owner = cpu_requests.owners(namespace, start, end)
        found, limit = founds.setdefault(part, {}), limits(namespace, end)
        for pod, value in peaks(namespace, start, end).items():
            if pod in owner:
                item = found.setdefault(owner[pod], {'peak': 0.0, 'outside': None, 'limit': None})
                item['peak'] = max(item['peak'], value)
                if f'{namespace}/{pod}' in extra:
                    item['outside'] = max(item['outside'] or 0.0, extra[f'{namespace}/{pod}'])
                if pod in limit:
                    item['limit'] = min(item['limit'] or limit[pod], limit[pod])
    for part, found in founds.items():
        table = {}
        for key, item in sorted(found.items()):
            entry = {'peak': quantity(item['peak']), 'request': f"{request_of(item['peak'], margin)}Mi"}
            if item['outside'] is not None:
                entry['outsidePeak'] = quantity(item['outside'])
            table[key] = entry
            if item['limit'] and item['limit'] < item['peak']:
                low.append({'part': part, 'workload': key, 'peak': entry['peak'], 'limit': quantity(item['limit'])})
        out[part] = table
    return out, low


def main():
    import argparse
    sys.path.insert(0, str(HERE))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('measure',))
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--zone', action='append', help='a zone. Give it once for each zone of the measurement.')
    target.add_argument('--site', action='store_true', help=f'measure the shared stores ({SITE_NAMESPACE})')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--guest')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    import cpu_requests
    start, end = cpu_requests.parse_time(args.start), cpu_requests.parse_time(args.end)
    table = load()
    # The processing pools of the site (../hoover/pools.py) belong to the part hoover. A zone load measures them with
    # the zones.
    parts = [('site', SITE_NAMESPACE)] if args.site else \
        [p for z in args.zone for p in (('zone', z), ('hoover', f'hoover-{z}'))] + [('hoover', POOLS_NAMESPACE)]
    measured, low = measure(parts, start, end, table['margin'], args.guest)
    if not args.write:
        node = node_reserve(args.guest, start, end, table['margin'], control_planes()) if args.guest else {}
        print(json.dumps({**measured, 'node': node, 'limitBelowPeak': low}, indent=1))
        return
    table.update(measured)
    if args.guest:
        table['node'] = node_reserve(args.guest, start, end, table['margin'], control_planes())
    table[RECORDS[parts[0][0]]] = {'source': f"load of {datetime.fromtimestamp(start).date().isoformat()}",
                                   'seconds': [int(start), int(end)]}
    TABLE_PATH.write_text(json.dumps(table, indent=1) + '\n')
    print(json.dumps({'written': str(TABLE_PATH), **{part: len(table[part]) for part, _ in parts}, 'limitBelowPeak': low}))


if __name__ == '__main__':
    main()
