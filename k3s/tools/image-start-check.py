#!/usr/bin/env python3
"""Start each store image and each custom image of a zone on one node, and record the result.

The images build for the x86-64-v2 baseline. A node without AVX2 shows an image that needs more: the process stops
with an illegal instruction or a CPU check message. The check runs the main program of each image with a command that
loads it, in the runtime of the zone workload: Kata for the stores and the parse workers, gVisor for the others.
ClickHouse starts its server, because it checks the CPU features at start, and the check waits for its ping answer.
The pods run in the namespace image-check, which the script deletes at the end.
Usage: image-start-check.py <zone> <node>
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402
K = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG)]
NS = 'image-check'
# image name part, runtime, command
CHECKS = [
    ('/postgres:', 'kata', ['postgres', '--version']),
    ('/redis:', 'kata', ['redis-server', '--version']),
    ('/memcached:', 'kata', ['memcached', '-V']),
    ('/nats:', 'kata', ['/nats-server', '--version']),
    ('/seaweedfs:', 'kata', ['/usr/bin/weed', 'version']),
    ('clickhouse-server', 'kata', ['sh', '-c', '(/entrypoint.sh >/tmp/log 2>&1 &); for i in $(seq 60); do '
                                   'wget -qO- http://127.0.0.1:8123/ping && exit 0; sleep 1; done; tail -5 /tmp/log; exit 1']),
    ('manticoresearch/manticore', 'kata', ['searchd', '--version']),
    ('dxflrs/garage', 'kata', ['/garage', '--version']),
    ('hoover/blockmount', 'kata', ['/busybox', 'true']),
    ('hoover/hoover-processing', 'kata', ['/opt/pysetup/.venv/bin/python3', '/app/main.py', 'version']),
    ('hoover/hoover-website', 'gvisor', ['sh', '-c', 'timeout 5 /app/server; code=$?; echo "exit $code"; [ $code = 124 ] || [ $code = 0 ] || [ $code = 1 ]']),
    ('hoover/hoover-regex', 'gvisor', ['sh', '-c', '/usr/local/bin/regex-entity-scanner & child=$!; '
                                    'trap "kill $child 2>/dev/null" EXIT; for i in $(seq 60); do '
                                    '/usr/local/bin/regex-entity-scanner --health-check && exit 0; '
                                    'kill -0 $child || exit 1; sleep 1; done; exit 1']),
    ('hoover/hoover-tesseract', 'gvisor', ['sh', '-c', 'tesseract --version && cd /app && python -c "import ocr_tesseract"']),
    ('hoover/hoover-ocr-pdf', 'gvisor', ['sh', '-c', 'cd /app && python -c "import ocr_pdf"']),
    ('hoover/hoover-clamav', 'gvisor', ['clamscan', '--version']),
    ('hoover/hoover-pdf-search', 'gvisor', ['python', '-c', 'import pypdfium2']),
    ('hoover/hoover-mcp-collections', 'gvisor', ['sh', '-c', 'cd /app && python -c "import collection_search_server.server"']),
    ('hoover/hoover-mcp-todo', 'gvisor', ['sh', '-c', 'cd /app && python -c "import agent_todo_server"']),
    ('hoover/hoover-mcp-whois', 'gvisor', ['sh', '-c', 'cd /app && python -c "import whois_server.server"']),
    ('hoover/hoover-mcp-metasearch', 'gvisor', ['sh', '-c', 'cd /app && python -c "import metasearch_server.server"']),
    ('hoover/hoover-mcp-browser', 'gvisor', ['sh', '-c', 'cd /app && python -c "import browser_use_server"']),
    ('hoover/hoover-web-tor', 'gvisor', ['tor', '--version']),
    ('hoover/hoover-research-agent', 'gvisor', ['sh', '-c', 'cd /app && python -c "import research_agent.api"']),
    ('hoover/nextcloud-ai', 'gvisor', ['php', '-v']),
    ('hoover/xwiki-extensions', 'gvisor', ['sh', '-c', 'ls /repo | head -3']),
]


def kubectl(*args, input=None, check=True):
    r = subprocess.run(K + list(args), input=input, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(r.stderr.strip()[-400:])
    return r.stdout


def images(zone):
    found = set()
    for namespace in (zone, f'hoover-{zone}', 'extensions'):
        for item in json.loads(kubectl('-n', namespace, 'get', 'pods', '-o', 'json'))['items']:
            if item.get('status', {}).get('phase') in ('Succeeded', 'Failed') or item['metadata'].get('deletionTimestamp'):
                continue
            spec = item['spec']
            found |= {c['image'] for c in spec['containers'] + spec.get('initContainers', [])}
    return found


def main():
    zone, node = sys.argv[1:3]
    found = images(zone)
    kubectl('create', 'namespace', NS)
    try:
        pods = []
        failed = False
        for part, runtime, command in CHECKS:
            matched = [i for i in sorted(found) if part in i]
            if not matched:
                print(json.dumps({'image': part, 'result': 'not used by the zone'}))
                failed = True
                continue
            for image in matched:
                name = f'check-{len(pods)}'
                pods.append((name, image, runtime))
                kubectl('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': NS},
                    'spec': {'nodeName': node, 'runtimeClassName': runtime, 'restartPolicy': 'Never', 'enableServiceLinks': False,
                             'containers': [{'name': 'main', 'image': image, 'command': command,
                                             # The kubelet admits a pod with nodeName by its requests, so all pods fit.
                                             'resources': {'requests': {'cpu': '10m', 'memory': '64Mi'},
                                                           'limits': {'cpu': '2', 'memory': '1536Mi'}}}]}}))
        deadline = time.time() + 900
        for name, image, runtime in pods:
            phase = ''
            while True:
                phase = kubectl('-n', NS, 'get', 'pod', name, '-o', 'jsonpath={.status.phase}', check=False)
                if phase in ('Succeeded', 'Failed') or time.time() >= deadline:
                    break
                time.sleep(3)
            log = kubectl('-n', NS, 'logs', name, check=False).strip().splitlines()
            print(json.dumps({'node': node, 'image': image, 'runtime': runtime, 'phase': phase, 'output': log[-2:]}), flush=True)
            failed |= phase != 'Succeeded'
    finally:
        kubectl('delete', 'namespace', NS, '--wait=false')
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
