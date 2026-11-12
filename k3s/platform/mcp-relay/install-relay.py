#!/usr/bin/env python3
"""Install the development relay of one Hoover installation on the loopback ports of its home node.

kubectl port-forward does not reach a pod in gVisor, so a developer on the home node reaches the MCP servers, the
operator interfaces and the stores of an installation through this relay (decision D11). The Deployment mcp-relay in
the namespace mcp-relay runs relay.py with runc in the host network of the home node. It listens on 127.0.0.1 only,
and it connects to the Services of the Hoover namespace. The relay passes bytes and reads no request content, so the
MCP servers keep their own authentication.

Ports:
- compose: the ports of the Compose install, from the source ini of the installation, else the deploy.py defaults.
  .mcp.json and the harness files then need no change. Compose must not hold these ports.
- temporary: each Compose port plus 1000, for a check while Compose still holds its ports.
The mode is saved in <operator state>/mcp-relay.json. The driver step mcp-relay and a call without --ports use the
saved mode, and the first install uses temporary.
A route whose Service does not exist in the namespace is left out, for example the internet services when
internet_tools_enabled is off.
Usage: install-relay.py <installation or zone> show|apply|delete [--ports compose|temporary] [--site FILE]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parents[1]
sys.path.insert(0, str(K3S))
import config as site_config  # noqa: E402
import settings as k3s_settings  # noqa: E402

NS = 'mcp-relay'
PYTHON = 'docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'
TEMPORARY_OFFSET = 1000
# name, the port key of the Compose ini, the Service and its port.
ROUTES = (
    ('mcp-collections', 'mcp_collections_port', 'hoover4-mcp-collections', 8085),
    ('mcp-todo', 'mcp_todo_port', 'hoover4-mcp-todo', 8088),
    ('mcp-whois', 'mcp_whois_port', 'hoover4-mcp-whois', 8082),
    ('mcp-metasearch', 'mcp_metasearch_port', 'hoover4-mcp-metasearch', 8086),
    ('mcp-browser', 'mcp_browser_port', 'hoover4-mcp-browser', 8087),
    ('temporal-ui', 'temporal_ui_port', 'temporal-ui', 8080),
    ('clickhouse-monitoring', 'clickhouse_monitoring_port', 'clickhouse-monitoring', 3000),
    ('ch-ui', 'ch_ui_port', 'ch-ui', 5521),
    ('clickhouse-http', 'clickhouse_http_port', 'clickhouse', 8123),
    ('clickhouse-native', 'clickhouse_native_port', 'clickhouse', 9000),
    ('manticore-sql', 'manticore_sql_port', 'manticore', 9306),
    ('manticore-http', 'manticore_http_port', 'manticore', 9308),
    ('manticore-vectors-sql', 'manticore_vectors_sql_port', 'manticore-vectors', 9306),
    ('manticore-vectors-http', 'manticore_vectors_http_port', 'manticore-vectors', 9308),
    ('garage-s3', 'garage_s3_port', 'garage', 3900),
    ('garage-admin', 'garage_admin_port', 'garage', 3903),
    ('temporal-grpc', 'temporal_grpc_port', 'temporal', 7233),
    ('temporal-http', 'temporal_http_port', 'temporal', 7243),
    ('cassandra', 'cassandra_port', 'temporal-cassandra', 9042),
    ('elasticsearch', 'elasticsearch_port', 'temporal-elasticsearch', 9200),
    ('tesseract-cpu', 'tesseract_cpu_port', 'hoover4-tesseract-cpu', 8000),
    ('ocr-pdf', 'ocr_pdf_port', 'hoover4-ocr-pdf', 8000),
    ('regex-entity-scanner', 'regex_entity_scanner_port', 'hoover4-regex-entity-scanner', 19705),
    ('internal-search-agent', 'internal_search_agent_port', 'hoover4-internal-search-agent', 8000),
    ('full-research-agent', 'full_research_agent_port', 'hoover4-full-research-agent', 8000),
)


def compose_ports(hoover):
    """The port of each route in the Compose install of the installation, or the deploy.py default."""
    deploy = site_config.deploy_module()
    values = {}
    if hoover.source_ini:
        values = site_config.read_source_ini(hoover.source_ini, check_paths=False).values.get('main_services', {})
    defaults = deploy.Config(None)
    return {name: int(values.get(key) or defaults.get('main_services', key)) for name, key, _, _ in ROUTES}


def routes(hoover, mode, services=None):
    ports = compose_ports(hoover)
    offset = TEMPORARY_OFFSET if mode == 'temporary' else 0
    return [{'name': name, 'listen': f'127.0.0.1:{ports[name] + offset}',
             'target': f'{service}.{hoover.namespace}.svc.cluster.local:{port}'}
            for name, _, service, port in ROUTES if services is None or service in services]


def objects(hoover, route_list):
    code = (HERE / 'relay.py').read_text()
    data = {'relay.py': code, 'routes.json': json.dumps(route_list, indent=1)}
    # The pod template names a hash of the routes, so a changed route list restarts the relay.
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
    container = {'name': 'relay', 'image': PYTHON, 'command': ['python3', '/etc/relay/relay.py'],
                 'env': [{'name': 'RELAY_ROUTES', 'value': '/etc/relay/routes.json'}, {'name': 'PYTHONDONTWRITEBYTECODE', 'value': '1'}],
                 'resources': {'requests': {'cpu': '10m', 'memory': '24Mi'}, 'limits': {'cpu': '1', 'memory': '256Mi'}},
                 'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}},
                 'volumeMounts': [{'name': 'relay', 'mountPath': '/etc/relay', 'readOnly': True}]}
    spec = {'hostNetwork': True, 'dnsPolicy': 'ClusterFirstWithHostNet', 'automountServiceAccountToken': False,
            'enableServiceLinks': False, 'nodeSelector': {'kubernetes.io/hostname': hoover.home_node},
            'securityContext': {'runAsNonRoot': True, 'runAsUser': 65534, 'runAsGroup': 65534, 'seccompProfile': {'type': 'RuntimeDefault'}},
            'containers': [container], 'volumes': [{'name': 'relay', 'configMap': {'name': 'mcp-relay'}}]}
    labels = {'app.kubernetes.io/name': 'mcp-relay', 'hoover.dev/runtime': 'runc'}
    return [
        {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NS}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'mcp-relay', 'namespace': NS}, 'data': data},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'mcp-relay', 'namespace': NS, 'labels': labels},
         'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': {'app.kubernetes.io/name': 'mcp-relay'}},
                  'template': {'metadata': {'labels': labels, 'annotations': {'hoover.dev/routes': digest}}, 'spec': spec}}},
    ]


def state_file(site):
    return site.operator_state() / 'mcp-relay.json'


def kubectl(*args, input=None, check=True):
    r = subprocess.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, *args], input=input, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:4])} failed: {(r.stderr or r.stdout).strip()[-400:]}')
    return r


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('installation')
    parser.add_argument('command', choices=('show', 'apply', 'delete'))
    parser.add_argument('--ports', choices=('compose', 'temporary'))
    parser.add_argument('--site', default=os.environ.get('HOOVER4_SITE', str(site_config.DEFAULT_SITE)))
    args = parser.parse_args(argv)
    site = site_config.read(args.site)
    hoover = next((h for h in site.hoovers.values() if args.installation in (h.name, h.zone)), None)
    if hoover is None:
        raise SystemExit(f'the site file has no [hoover.<name>] section with the name or zone {args.installation}.')
    saved = json.loads(state_file(site).read_text()) if state_file(site).exists() else {}
    mode = args.ports or saved.get('ports', 'temporary')
    if args.command == 'delete':
        kubectl('-n', NS, 'delete', 'deployment,configmap', 'mcp-relay', '--ignore-not-found')
        state_file(site).unlink(missing_ok=True)
        print(json.dumps({'relay': 'deleted'}))
        return
    services = None
    if args.command == 'apply':
        found = kubectl('-n', hoover.namespace, 'get', 'services', '-o', 'json')
        services = {i['metadata']['name'] for i in json.loads(found.stdout)['items']}
    route_list = routes(hoover, mode, services)
    items = objects(hoover, route_list)
    if args.command == 'show':
        print(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}, indent=1))
        return
    kubectl('apply', '--server-side', '--force-conflicts', '--field-manager=hoover', '-f', '-',
            input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': items}))
    kubectl('-n', NS, 'rollout', 'status', 'deployment/mcp-relay', '--timeout=180s')
    state_file(site).parent.mkdir(parents=True, exist_ok=True)
    state_file(site).write_text(json.dumps({'installation': hoover.name, 'ports': mode}) + '\n')
    print(json.dumps({'relay': hoover.name, 'ports': mode, 'routes': {r['name']: r['listen'] for r in route_list}}, indent=1))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except site_config.SiteError as error:
        raise SystemExit(str(error))
