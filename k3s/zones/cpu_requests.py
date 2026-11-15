#!/usr/bin/env python3
"""The CPU requests of the zone and site workloads from telemetry, and the tool that measures them.

cpu-requests.json holds, for each workload <kind>/<name> of a zone (part zone: openDesk, part hoover: the Hoover
installation), the CPU numbers of a measured zone create, and for each shared store of the site (part site: the
namespace hoover-stores, ../hoover/stores/shared.py and temporal.py), the numbers of a measured store start:
  startPeak  the highest CPU rate of a pod (rate over 1 min) from its start until it is Ready, plus SETTLE seconds.
  baseline   the median CPU rate of the pods in an idle period after the create or the start.
  request    baseline + factor x (startPeak - baseline), rounded up to 10m. factor is a value of the file.
The scheduler (the k3s scheduler configuration of ../ansible/roles/hoover4_k3s) places each new pod on the node with the
lowest requested CPU per thread, so the request is the load that the scheduler sees.

runtimeOverhead holds the steady CPU of k3s and the runtime outside the pod cgroups. pod_fixed() gives the part that
is the same for each pod of a RuntimeClass (its overhead.podFixed, ../cluster/runtimeclasses.yaml), and runtime_cost()
the part that depends on the containers and exec probes of one pod. apply() adds runtime_cost() to the request of the
main container and names it in the annotation hoover.dev/cpu-runtime.

apply() writes the request into a workload of a render, and the annotations hoover.dev/cpu-start-peak,
hoover.dev/cpu-baseline and hoover.dev/cpu-request-basis into its pod template. The pod CPU request is the table value:
the main container (the container of the memory table, else the first) gets the table value minus the requests of
the other containers. A workload without a measurement keeps the request of the CPU policy (cpu_policy.py) or of its
installer, and its basis annotation says so. postrender.py, gate.py, ../hoover/manifests.py and the store installers
of ../hoover/stores call apply().

Usage of the tool. It reads Prometheus of the site (the service of the monitoring step) through the API server:
  cpu_requests.py measure --zone ZONE --start TIME --end TIME --idle-start TIME --idle-end TIME [--write]
  cpu_requests.py measure --site --start TIME --end TIME --idle-start TIME --idle-end TIME [--write]
TIME is a Unix time or an ISO 8601 time with a zone. start and end enclose the zone create (--zone) or the start of
the shared stores (--site), and the idle period follows it. Without --write the tool prints the table. With --write
it replaces the measured parts of cpu-requests.json: zone and hoover with --zone (record measured), site with --site
(record measuredSite).
"""
import json
import math
import os
import statistics
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE_PATH = HERE / 'cpu-requests.json'
# Seconds after Ready that still count as start.
SETTLE = 120
STEP = 15
# The namespace of the shared stores of a site (part site).
SITE_NAMESPACE = 'hoover-stores'
# The record of the measurement of each part, which the basis annotation names.
RECORDS = {'zone': 'measured', 'hoover': 'measured', 'site': 'measuredSite'}
PROMETHEUS = '/api/v1/namespaces/monitoring/services/monitor-kube-prometheus-st-prometheus:9090/proxy/api/v1'
START_PEAK = 'hoover.dev/cpu-start-peak'
BASELINE = 'hoover.dev/cpu-baseline'
BASIS = 'hoover.dev/cpu-request-basis'
RUNTIME = 'hoover.dev/cpu-runtime'
# The RuntimeClass of a pod without runtimeClassName in each part. The zone namespaces get gVisor from the admission
# policy of ../zones/manifests/zone-pods.yaml, unless the pod has the label hoover.dev/runtime=runc.
DEFAULT_RUNTIME = {'zone': 'gvisor', 'hoover': 'gvisor', 'site': 'runc'}
PROBES = ('livenessProbe', 'readinessProbe')


def load():
    return json.loads(TABLE_PATH.read_text()) if TABLE_PATH.exists() else {'factor': 0.2, 'zone': {}, 'hoover': {}, 'site': {}}


def millicores(value):
    text = str(value)
    return float(text[:-1]) if text.endswith('m') else float(text) * 1000


def quantity(value):
    return f'{int(value)}m'


def request_of(peak, baseline, factor):
    """baseline + factor x (peak - baseline) in millicores, rounded up to 10m, at least 10m."""
    value = baseline + factor * max(0.0, peak - baseline)
    return max(10, int(math.ceil(value / 10.0 - 1e-9)) * 10)


def pod_spec(doc):
    if doc['kind'] == 'CronJob':
        return doc['spec']['jobTemplate']['spec']['template']['spec']
    return doc['spec']['template']['spec']


def template_metadata(doc):
    template = doc['spec']['jobTemplate']['spec']['template'] if doc['kind'] == 'CronJob' else doc['spec']['template']
    # A chart can render an empty mapping as null.
    if not template.get('metadata'):
        template['metadata'] = {}
    return template['metadata']


def pod_fixed(runtime, table=None):
    """Millicores of the RuntimeClass overhead: the kubelet and the shim of one pod, and for gVisor the statistics call
    of its sandbox. Rounded up to 1m."""
    o = (table or TABLE)['runtimeOverhead']
    value = o['kubeletPerPod'] + o['shimPerPod']
    if runtime == 'gvisor':
        value += o['runscStatsCpuSeconds'] * 1000 / o['statsPeriodSeconds']
    return int(math.ceil(value - 1e-9))


def runtime(doc, part):
    """The RuntimeClass of the pods of a workload: runtimeClassName, else the default of the part."""
    spec = pod_spec(doc)
    if spec.get('runtimeClassName'):
        return spec['runtimeClassName']
    labels = template_metadata(doc).get('labels') or {}
    return 'runc' if labels.get('hoover.dev/runtime') == 'runc' else DEFAULT_RUNTIME[part]


def runtime_cost(spec, runtime_class, table=None):
    """Millicores that one pod causes outside its cgroup beyond pod_fixed(): the statistics call of each gVisor
    container, and each liveness and readiness exec probe at its period. A startup probe ends at the start, so it does
    not count. Rounded up to 1m."""
    o = (table or TABLE)['runtimeOverhead']
    containers = list(spec.get('containers') or []) + [c for c in spec.get('initContainers') or []
                                                       if c.get('restartPolicy') == 'Always']
    value = 0.0
    if runtime_class == 'gvisor':
        value += len(containers) * o['runscStatsCpuSeconds'] * 1000 / o['statsPeriodSeconds']
    for c in containers:
        for kind in PROBES:
            probe = c.get(kind) or {}
            if 'exec' in probe:
                value += o['execCpuSeconds'] * 1000 / max(1, probe.get('periodSeconds', 10))
    return int(math.ceil(value - 1e-9))


def main_container(containers, main):
    return next((c for c in containers if c['name'] == main), containers[0])


def requests_of(c):
    if not c.get('resources'):
        c['resources'] = {}
    if not c['resources'].get('requests'):
        c['resources']['requests'] = {}
    return c['resources']['requests']


def cap(c):
    """Keep the CPU request of a container at most its CPU limit."""
    resources = c['resources']
    limit = (resources.get('limits') or {}).get('cpu')
    if limit and millicores(limit) < millicores(resources['requests']['cpu']):
        resources['requests']['cpu'] = limit


def apply(doc, key, part, main=None, table=None):
    """Write the table request, the runtime cost and the annotations into a workload. key is <kind>/<name>, part zone,
    hoover or site.

    main names the main container. The runtime cost (runtime_cost()) goes on top of the request of the main container,
    also for a workload without a measurement. A second call gives the same result. Return True when the table has the
    workload.
    """
    table = table or TABLE
    entry = table.get(part, {}).get(key)
    metadata = template_metadata(doc)
    if not metadata.get('annotations'):
        metadata['annotations'] = {}
    annotations = metadata['annotations']
    containers = pod_spec(doc).get('containers', [])
    costed = 'runtimeOverhead' in table
    extra = runtime_cost(pod_spec(doc), runtime(doc, part), table) if costed else 0
    if not entry:
        annotations[BASIS] = 'no measurement: the request of the CPU policy'
        for name in (START_PEAK, BASELINE):
            annotations.pop(name, None)
        if containers:
            chosen = main_container(containers, main)
            requests = requests_of(chosen)
            before = millicores(annotations.get(RUNTIME, '0m'))
            requests['cpu'] = quantity(max(10, millicores(requests.get('cpu', 0)) - before + extra))
            cap(chosen)
        if costed:
            annotations[RUNTIME] = quantity(extra)
        return False
    annotations[START_PEAK] = entry['startPeak']
    annotations[BASELINE] = entry['baseline']
    annotations[BASIS] = f"baseline + {table['factor']} x (start peak - baseline), {table.get(RECORDS[part], {}).get('source', 'measured')}"
    if costed:
        annotations[RUNTIME] = quantity(extra)
    if not containers:
        return True
    chosen = main_container(containers, main)
    others = sum(millicores(((c.get('resources') or {}).get('requests') or {}).get('cpu', 0))
                 for c in containers if c is not chosen)
    wanted = millicores(entry['request'])
    requests_of(chosen)['cpu'] = quantity(max(10, wanted - others) + extra)
    cap(chosen)
    return True


TABLE = load()


# ----------------------------------------------------------------------------------------------------------------------
# Measurement
# ----------------------------------------------------------------------------------------------------------------------

def parse_time(text):
    try:
        return float(text)
    except ValueError:
        return datetime.fromisoformat(text).timestamp()


def kubectl_raw(path):
    command = ['kubectl']
    if os.environ.get('KUBECONFIG'):
        command += ['--kubeconfig', os.environ['KUBECONFIG']]
    out = subprocess.run(command + ['get', '--raw', path], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f'the Prometheus query {urllib.parse.unquote(path)[-300:]} failed: {out.stderr.strip()[-300:]}')
    data = json.loads(out.stdout)
    if data.get('status') != 'success':
        raise SystemExit(f'Prometheus answered {data}')
    return data['data']['result']


def query(expr, at):
    return kubectl_raw(f'{PROMETHEUS}/query?' + urllib.parse.urlencode({'query': expr, 'time': at}))


def query_range(expr, start, end, step=STEP):
    return kubectl_raw(f'{PROMETHEUS}/query_range?' + urllib.parse.urlencode(
        {'query': expr, 'start': start, 'end': end, 'step': step}))


def owners(namespace, start, end):
    """{pod: <kind>/<name>} of the controller of each pod. A Job, a bare pod and an unknown owner are left out."""
    window = f'{int(end - start) + 600}s'
    sets = {r['metric']['replicaset']: r['metric']['owner_name']
            for r in query(f'last_over_time(kube_replicaset_owner{{namespace="{namespace}",owner_kind="Deployment"}}[{window}])', end)}
    out = {}
    for r in query(f'last_over_time(kube_pod_owner{{namespace="{namespace}"}}[{window}])', end):
        m = r['metric']
        kind, name = m.get('owner_kind'), m.get('owner_name')
        if kind == 'ReplicaSet' and name in sets:
            out[m['pod']] = f'deployment/{sets[name]}'
        elif kind in ('StatefulSet', 'DaemonSet'):
            out[m['pod']] = f'{kind.lower()}/{name}'
    return out


def pod_cpu(namespace):
    # The pod cgroup has no container and no image label. It holds every container of a pod, also the sandbox of a
    # gVisor or Kata pod, whose containers have no cgroup of their own.
    return f'sum by (pod) (rate(container_cpu_usage_seconds_total{{namespace="{namespace}",container="",image=""}}[1m]))'


def start_peaks(namespace, start, end):
    """{pod: millicores} of the highest CPU rate from the first sample until Ready plus SETTLE."""
    ready = {}
    for r in query_range(f'kube_pod_status_ready{{namespace="{namespace}",condition="true"}} == 1', start, end):
        ready[r['metric']['pod']] = min(float(t) for t, _ in r['values'])
    peaks = {}
    for r in query_range(pod_cpu(namespace), start, end):
        pod = r['metric'].get('pod')
        if pod not in ready:
            continue
        limit = ready[pod] + SETTLE
        values = [float(v) for t, v in r['values'] if float(t) <= limit]
        if values:
            peaks[pod] = max(values) * 1000
    return peaks


def baselines(namespace, start, end):
    """{pod: millicores} of the median CPU rate in the idle period."""
    window = f'{int(end - start)}s'
    return {r['metric']['pod']: float(r['value'][1]) * 1000
            for r in query(f'quantile_over_time(0.5, {pod_cpu(namespace)}[{window}:30s])', end) if 'pod' in r['metric']}


def measure(parts, start, end, idle_start, idle_end, factor):
    """Measure each (part, namespace) of parts and return the table of each part."""
    out = {}
    for part, namespace in parts:
        owner = owners(namespace, start, idle_end)
        peaks = start_peaks(namespace, start, end)
        idle = baselines(namespace, idle_start, idle_end)
        found = {}
        for pod, key in owner.items():
            item = found.setdefault(key, {'peaks': [], 'idle': []})
            if pod in peaks:
                item['peaks'].append(peaks[pod])
            if pod in idle:
                item['idle'].append(idle[pod])
        table = {}
        for key, item in sorted(found.items()):
            if not item['peaks'] or not item['idle']:
                continue
            peak, base = max(item['peaks']), statistics.median(item['idle'])
            peak_m, base_m = int(math.ceil(peak)), int(math.ceil(base))
            table[key] = {'startPeak': quantity(peak_m), 'baseline': quantity(base_m),
                          'request': quantity(request_of(peak_m, base_m, factor))}
        out[part] = table
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('measure',))
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--zone')
    target.add_argument('--site', action='store_true', help=f'measure the shared stores ({SITE_NAMESPACE})')
    for name in ('start', 'end', 'idle-start', 'idle-end'):
        parser.add_argument(f'--{name}', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    times = [parse_time(getattr(args, n)) for n in ('start', 'end', 'idle_start', 'idle_end')]
    table = load()
    parts = [('site', SITE_NAMESPACE)] if args.site else [('zone', args.zone), ('hoover', f'hoover-{args.zone}')]
    measured = measure(parts, *times, table['factor'])
    if not args.write:
        print(json.dumps(measured, indent=1))
        return
    table.update(measured)
    event = 'store start' if args.site else 'zone create'
    table[RECORDS[parts[0][0]]] = {'source': f"{event} of {datetime.fromtimestamp(times[0]).date().isoformat()}",
                                   'createSeconds': [int(times[0]), int(times[1])], 'idleSeconds': [int(times[2]), int(times[3])]}
    TABLE_PATH.write_text(json.dumps(table, indent=1) + '\n')
    print(json.dumps({'written': str(TABLE_PATH), **{part: len(table[part]) for part, _ in parts}}))


if __name__ == '__main__':
    main()
