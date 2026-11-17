#!/usr/bin/env python3
"""Check the network policies of the Hoover namespace of a zone. Usage: hoover-network-check.py <zone> <other zone>

Each case opens one TCP connection from a running pod of hoover-<zone> with kubectl exec. It compares the result with
the expected one of network() in ../hoover/manifests.py and ../hoover/stores/shared.py. A worker checks its stores,
Temporal, the GPU forwarder and the internet. It also checks the GPU box, the schema proxy of the other zone, the Garage
RPC and admin ports of the shared stores, the file service of the Manticore text daemon (open only for the schema proxy), the internal ports of a Temporal pod of the site, the Cassandra and
OpenSearch of Temporal, the openDesk stores of its zone, Prometheus and the Kubernetes API.
An internet service checks the internet, the GPU box, the stores and a service of its namespace. The forwarder gpu
checks the GPU proxy and the GPU box. A site without a GPU pool has no GPU cases.
The processing pools of the site (../hoover/pools.py): the worker and the website reach the pools that they call, and
the collections server reaches none. From the namespace hoover-pools, the searchable-PDF builder reaches Tesseract and
no other pool, Tesseract reaches no store, no zone namespace, no other pool, the Kubernetes API or the internet, and
ClamAV reaches the internet and no store.
The script prints one JSON line for each case and exits with 1 when a case has another result than expected. A case
of a Deployment that the site does not run has the result absent and no pass or fail.
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
    """open or closed with the reason, through python3, else nc, else the /dev/tcp of bash. 'absent' when the
    Deployment does not exist, for example an internet service of a site that has the internet tools off."""
    found = subprocess.run(['kubectl', '-n', namespace, 'get', 'deployment', deployment, '--ignore-not-found', '-o', 'name'],
                           capture_output=True, text=True, timeout=60)
    if not found.stdout.strip():
        return 'absent'
    base = ['kubectl', '-n', namespace, 'exec', f'deploy/{deployment}', '-c', container, '--']
    r = subprocess.run(base + ['sh', '-c', f'if command -v python3 >/dev/null; then python3 -c "$0" {host} {port}; '
                               f'elif command -v nc >/dev/null; then nc -z -w 5 {host} {port} && echo open || echo closed; '
                               f'else timeout 5 bash -c "echo > /dev/tcp/{host}/{port}" 2>/dev/null && echo open || echo closed bash; fi',
                               PROBE],
                       capture_output=True, text=True, timeout=60)
    out = (r.stdout.strip() or r.stderr.strip()).splitlines()
    return out[-1] if out else 'no output'


def temporal_pod():
    """The address of a Temporal pod of the site. The Service temporal publishes only the frontend ports."""
    out = subprocess.run(['kubectl', '-n', 'hoover-stores', 'get', 'pods', '-l', 'app.kubernetes.io/name=temporal', '-o',
                          'jsonpath={.items[0].status.podIP}'], capture_output=True, text=True, timeout=60).stdout.strip()
    return out or 'temporal-pod-not-found'


def gpu_box():
    """The address of the GPU pool, or None for a site without one."""
    import config
    import gpu
    if not config.read(settings.SITE_FILE).gpu_pool:
        return None
    return gpu.site_pool()['address']


# The processing pools and their ports (../hoover/pools.py).
POOLS = {'hoover4-tika': 9998, 'hoover4-clamav': 8000, 'hoover4-tesseract-cpu': 8000, 'hoover4-ocr-pdf': 8000,
         'hoover4-pdf-search': 13500, 'hoover4-regex-entity-scanner': 19705}


def pool_cases(zone):
    """(namespace, (deployment, container), name, host, port, open) of the processing pools."""
    own = f'hoover-{zone}'
    worker, website = ('hoover-workers', 'hoover-workers'), ('hoover-website', 'hoover-website')
    ocr_pdf, tesseract, clamav = (('hoover4-ocr-pdf',) * 2, ('hoover4-tesseract-cpu',) * 2, ('hoover4-clamav',) * 2)
    out = [(own, worker, f'pool {name}', name, port, True) for name, port in POOLS.items()]
    out += [(own, website, 'pool hoover4-pdf-search', 'hoover4-pdf-search', 13500, True),
            (own, ('hoover4-mcp-collections', 'hoover4-mcp-collections'), 'pool hoover4-tika', 'hoover4-tika', 9998, False)]
    pools = 'hoover-pools'
    out += [(pools, ocr_pdf, 'pool Tesseract', 'hoover4-tesseract-cpu', 8000, True),
            (pools, ocr_pdf, 'pool ClamAV', 'hoover4-clamav', 8000, False),
            (pools, tesseract, 'pool Tika', 'hoover4-tika', 9998, False),
            (pools, tesseract, 'shared ClickHouse', 'clickhouse.hoover-stores.svc.cluster.local', 8123, False),
            (pools, tesseract, 'shared Garage', 'garage.hoover-stores.svc.cluster.local', 3900, False),
            (pools, tesseract, 'shared Manticore', 'manticore.hoover-stores.svc.cluster.local', 9306, False),
            (pools, tesseract, 'website of the zone', f'hoover-website.{own}.svc.cluster.local', 8080, False),
            (pools, tesseract, 'schema proxy of the zone', f'manticore-schema.{own}.svc.cluster.local', 8080, False),
            (pools, tesseract, 'openDesk Redis of the zone', f'redis-master.{zone}.svc.cluster.local', 6379, False),
            (pools, tesseract, 'Kubernetes API', 'kubernetes.default.svc.cluster.local', 443, False),
            (pools, tesseract, 'internet', '1.1.1.1', 443, False),
            (pools, clamav, 'internet', '1.1.1.1', 443, True),
            (pools, clamav, 'shared ClickHouse', 'clickhouse.hoover-stores.svc.cluster.local', 8123, False),
            (pools, clamav, 'website of the zone', f'hoover-website.{own}.svc.cluster.local', 8080, False)]
    return out


def cases(zone, other):
    box = gpu_box()
    temporal = temporal_pod()
    stores = [('shared ClickHouse', 'clickhouse', 8123, True), ('shared ClickHouse native', 'clickhouse', 9000, True),
              ('shared Manticore', 'manticore', 9306, True), ('shared Manticore read-only HTTP', 'manticore', 9309, True),
              ('shared Manticore vectors', 'manticore-vectors', 9306, True), ('own schema proxy', 'manticore-schema', 8080, True),
              ('shared Garage', 'garage', 3900, True), ('Temporal', 'temporal', 7233, True)]
    garage_pod = 'garage-0.garage-peers.hoover-stores.svc.cluster.local'
    worker = ('hoover-workers', 'hoover-workers')
    found = [
        *[(worker, name, host, port, ok) for name, host, port, ok in stores],
        (worker, 'GPU forwarder', 'gpu', 21961, True),
        (worker, 'internet', '1.1.1.1', 443, False),
        (worker, 'GPU box', box, 21961, False),
        (worker, 'schema proxy of the other zone', f'manticore-schema.hoover-{other}.svc.cluster.local', 8080, False),
        (('hoover4-mcp-collections', 'hoover4-mcp-collections'), 'own schema proxy', 'manticore-schema', 8080, False),
        (worker, 'Manticore file service', 'manticore', 9318, False),
        (('manticore-schema', 'manticore-schema'), 'Manticore file service', 'manticore', 9318, True),
        (worker, 'Garage RPC', garage_pod, 3901, False),
        (worker, 'Garage admin', garage_pod, 3903, False),
        (worker, 'Temporal internal frontend', temporal, 7236, False),
        (worker, 'Temporal history', temporal, 7234, False),
        (worker, 'Temporal Cassandra', 'temporal-cassandra-0.temporal-cassandra-peers.hoover-stores.svc.cluster.local', 9042, False),
        (worker, 'Temporal OpenSearch', 'temporal-opensearch.hoover-stores.svc.cluster.local', 9200, False),
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
    if box is None:
        found = [c for c in found if c[0][0] != 'gpu' and c[1] not in ('GPU box', 'GPU forwarder')]
    return [(f'hoover-{zone}', *c) for c in found] + pool_cases(zone)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    zone, other = sys.argv[1:]
    ok = True
    for namespace, (deployment, container), name, host, port, expected in cases(zone, other):
        result = connect(namespace, deployment, container, host, port)
        good = None if result == 'absent' else result.startswith('open') == expected
        ok &= good is not False
        print(json.dumps({'from': f'{namespace}/{deployment}', 'case': name, 'target': f'{host}:{port}',
                          'expected': 'open' if expected else 'closed', 'result': result, 'pass': good}), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
