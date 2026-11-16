#!/usr/bin/env python3
"""Sample the memory of the Kata pods every 10 s from the kubelet summary of each node.

The pod cgroup of a Kata pod holds the whole VM, so Prometheus (cAdvisor) sees only the pod. The kubelet summary also
gives the working set of each container in the guest, from the Kata agent. ../../zones/memory_requests.py --guest reads
this output and takes the highest difference as the Kata overhead of each workload (outsidePeak).
Each line: {"t": epoch, "node": name, "ws": node working set, "avail": node available bytes, "sys": {system container:
working set}, "kata": {pod uid: {"name": "<namespace>/<pod>", "pod": working set, "c": {container: [working set,
usage, rss]}}}}. The node values give the memory of k3s and the system beside the pods.
Usage: guest_sampler.py <output.jsonl> [--seconds N]. KUBECONFIG names the cluster.
"""
import json
import subprocess
import sys
import time


def kubectl_json(*args):
    out = subprocess.run(['kubectl', *args], capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout) if out.returncode == 0 else None


def kata_pods():
    pods = kubectl_json('get', 'pods', '-A', '-o', 'json') or {'items': []}
    return {p['metadata']['uid'] for p in pods['items'] if p['spec'].get('runtimeClassName') == 'kata'}


def main():
    path = sys.argv[1]
    seconds = int(sys.argv[sys.argv.index('--seconds') + 1]) if '--seconds' in sys.argv else 3600
    nodes = [n['metadata']['name'] for n in (kubectl_json('get', 'nodes', '-o', 'json') or {'items': []})['items']]
    kata, listed = kata_pods(), time.time()
    end = time.time() + seconds
    with open(path, 'a') as f:
        while time.time() < end:
            t0 = time.time()
            if t0 - listed > 60:
                kata, listed = kata_pods(), t0
            for node in nodes:
                s = kubectl_json('get', '--raw', f'/api/v1/nodes/{node}/proxy/stats/summary')
                if s is None:
                    f.write(json.dumps({'t': round(t0, 1), 'node': node, 'error': 'no summary'}) + '\n')
                    continue
                n = s['node']
                row = {'t': round(t0, 1), 'node': node, 'ws': n['memory'].get('workingSetBytes'),
                       'avail': n['memory'].get('availableBytes'),
                       'sys': {c['name']: c['memory'].get('workingSetBytes') for c in n.get('systemContainers', [])},
                       'kata': {}}
                for p in s.get('pods', []):
                    if p['podRef']['uid'] not in kata:
                        continue
                    row['kata'][p['podRef']['uid']] = {
                        'name': f"{p['podRef']['namespace']}/{p['podRef']['name']}",
                        'pod': (p.get('memory') or {}).get('workingSetBytes'),
                        'c': {c['name']: [(c.get('memory') or {}).get(k) for k in ('workingSetBytes', 'usageBytes', 'rssBytes')]
                              for c in p.get('containers', [])}}
                f.write(json.dumps(row) + '\n')
            f.flush()
            time.sleep(max(0.5, 10 - (time.time() - t0)))


if __name__ == '__main__':
    main()
