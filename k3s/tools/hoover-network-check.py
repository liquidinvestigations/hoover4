#!/usr/bin/env python3
"""Check the network policies of the Hoover namespace of a zone. Usage: hoover-network-check.py <zone> <other zone>

Each case opens one TCP connection from a running pod of hoover-<zone> with kubectl exec. It compares the result with
the expected one of network() in ../hoover/manifests.py and ../hoover/stores/shared.py. A worker checks its stores,
Temporal, the GPU forwarder and the internet. It also checks the GPU box, the Manticore of the other zone, the Garage
RPC and admin ports of the shared stores, the openDesk stores of its zone, Prometheus and the Kubernetes API.
An internet service checks the internet, the GPU box, the stores and a service of its namespace. The forwarder gpu
checks the GPU proxy and the GPU box.
The script prints one JSON line for each case and exits with 1 when a case has another result than expected.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hoover'))
import settings  # noqa: E402

settings.use_kubeconfig()
PROBE = ("import socket,sys\ntry:\n socket.create_connection((sys.argv[1],int(sys.argv[2])),5).close();print('open')\n"
         "except Exception as e:\n print('closed',type(e).__name__)")


def connect(namespace, deployment, container, host, port):
    base = ['kubectl', '-n', namespace, 'exec', f'deploy/{deployment}', '-c', container, '--']
    r = subprocess.run(base + ['sh', '-c', f'command -v python3 >/dev/null && python3 -c "$0" {host} {port} || '
                               f'(nc -z -w 5 {host} {port} && echo open || echo closed)', PROBE],
                       capture_output=True, text=True, timeout=60)
    out = (r.stdout.strip() or r.stderr.strip()).splitlines()
    return out[-1] if out else 'no output'


def cases(zone, other):
    import gpu
    box = gpu.site_pool()['address']
    stores = [('shared ClickHouse', 'clickhouse', 8123, True), ('shared ClickHouse native', 'clickhouse', 9000, True),
              ('own Manticore', 'manticore', 9306, True), ('shared Garage', 'garage', 3900, True), ('Temporal', 'temporal', 7233, True)]
    garage_pod = 'garage-0.garage-peers.hoover-stores.svc.cluster.local'
    worker = ('hoover-workers', 'hoover-workers')
    return [
        *[(worker, name, host, port, ok) for name, host, port, ok in stores],
        (worker, 'GPU forwarder', 'gpu', 21961, True),
        (worker, 'internet', '1.1.1.1', 443, False),
        (worker, 'GPU box', box, 21961, False),
        (worker, 'Manticore of the other zone', f'manticore.{other}.svc.cluster.local', 9306, False),
        (worker, 'Garage RPC', garage_pod, 3901, False),
        (worker, 'Garage admin', garage_pod, 3903, False),
        (worker, 'openDesk Redis of the zone', f'redis-master.{zone}.svc.cluster.local', 6379, False),
        (worker, 'Prometheus', 'monitor-kube-prometheus-st-prometheus.monitoring.svc.cluster.local', 9090, False),
        (worker, 'Kubernetes API', 'kubernetes.default.svc.cluster.local', 443, False),
        (('hoover4-mcp-whois', 'hoover4-mcp-whois'), 'internet', '1.1.1.1', 443, True),
        (('hoover4-mcp-whois', 'hoover4-mcp-whois'), 'GPU box', box, 21961, False),
        (('hoover4-mcp-whois', 'hoover4-mcp-whois'), 'shared ClickHouse', 'clickhouse', 8123, False),
        (('hoover4-mcp-whois', 'hoover4-mcp-whois'), 'a service of the namespace', 'hoover4-mcp-collections', 8085, True),
        (('gpu', 'nginx'), 'GPU proxy', 'gpu-proxy.gpu-proxy.svc.cluster.local', 21961, True),
        (('gpu', 'nginx'), 'GPU box', box, 21961, False),
        (('gpu', 'nginx'), 'internet', '1.1.1.1', 443, False),
    ]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    zone, other = sys.argv[1:]
    ok = True
    for (deployment, container), name, host, port, expected in cases(zone, other):
        result = connect(f'hoover-{zone}', deployment, container, host, port)
        good = result.startswith('open') == expected
        ok &= good
        print(json.dumps({'from': deployment, 'case': name, 'target': f'{host}:{port}',
                          'expected': 'open' if expected else 'closed', 'result': result, 'pass': good}), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
