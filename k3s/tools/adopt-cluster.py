#!/usr/bin/env python3
"""Prepare the adoption of a running cluster by the site file and the driver of this checkout.

An earlier tool installed the cluster. Before the first deploy-k3s up of this site, the operator state must hold the
identities of that cluster, so the driver keeps them.
  inventory   Reads the cluster and writes <operator state>/adoption/inventory-<time>.json: the nodes with their roles
              and datastore labels, the zone and Hoover namespaces, their claims with UID, volume and size, the Secret
              names (no values), the images of each workload and the storage identity of each Hoover installation.
              It compares them with the site file and lists each difference. It changes nothing.
  tokens      Copies the server token and the agent token of the control plane into k3s/private/staging/tokens/,
              through the root route of the control plane (../driver/hostroute.py). The files are private, and no
              token value reaches a log, a command argument or the output. A server without an agent token gets the
              secret of the server token as agent token, which is the token that its agents already use.
  runners     Lists the operator runner units of the earlier tool on the control plane, as the user shell sees them.
Usage: adopt-cluster.py inventory|tokens|runners [--site FILE]
"""
import argparse
import json
import os
import shlex
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parent
sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'driver'))
import config  # noqa: E402
import hostroute  # noqa: E402
import settings as k3s_settings  # noqa: E402

IDENTITY_VARIABLES = ('CLICKHOUSE_DATABASE_PREFIX', 'MANTICORE_TABLE_PREFIX', 'SYSTEM_BUCKET', 'COLLECTION_BUCKET_PREFIX')


def kubectl_json(*args):
    code, out = hostroute.run(['kubectl', '--kubeconfig', k3s_settings.KUBECONFIG, *args, '-o', 'json'], timeout=120)
    if code:
        raise SystemExit(f'kubectl {" ".join(args)} failed: {out[-300:]}')
    return json.loads(out)


def inventory(site):
    nodes = {n['metadata']['name']: {'labels': {k: v for k, v in n['metadata']['labels'].items()
                                                if k.startswith('node-role') or k.startswith('hoover')},
                                     'version': n['status']['nodeInfo']['kubeletVersion'],
                                     'architecture': n['status']['nodeInfo']['architecture']}
             for n in kubectl_json('get', 'nodes')['items']}
    namespaces = [n['metadata']['name'] for n in kubectl_json('get', 'namespaces')['items']]
    out = {'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'nodes': nodes, 'namespaces': {}, 'differences': []}
    for hoover in site.hoovers.values():
        for ns in (hoover.zone, hoover.namespace):
            if ns not in namespaces:
                out['differences'].append(f'the namespace {ns} of [hoover.{hoover.name}] does not exist')
                continue
            claims = {c['metadata']['name']: {'uid': c['metadata']['uid'], 'volume': c['spec'].get('volumeName', ''),
                                              'size': c['spec']['resources']['requests']['storage'],
                                              'class': c['spec'].get('storageClassName'),
                                              'mode': c['spec'].get('volumeMode', 'Filesystem')}
                      for c in kubectl_json('-n', ns, 'get', 'pvc')['items']}
            secrets = sorted(s['metadata']['name'] for s in kubectl_json('-n', ns, 'get', 'secrets')['items'])
            workloads, identity = {}, {}
            for w in kubectl_json('-n', ns, 'get', 'deployments,statefulsets')['items']:
                containers = w['spec']['template']['spec']['containers']
                workloads[f'{w["kind"]}/{w["metadata"]["name"]}'] = sorted({c['image'] for c in containers})
                for c in containers:
                    for e in c.get('env', []):
                        if e['name'] in IDENTITY_VARIABLES and 'value' in e:
                            identity[e['name']] = e['value']
            out['namespaces'][ns] = {'claims': claims, 'secrets': secrets, 'workloads': workloads, 'identity': identity}
            if ns == hoover.namespace and identity:
                wanted = hoover.identity()
                for key, value in identity.items():
                    if wanted.get(key) != value:
                        out['differences'].append(f'{ns} runs {key} = {value}, and the site file names {wanted.get(key)}')
        home = nodes.get(hoover.home_node)
        if home is None:
            out['differences'].append(f'the home node {hoover.home_node} of [hoover.{hoover.name}] is not a node')
    control = nodes.get(site.control_plane, {})
    out['etcd_role'] = control.get('labels', {}).get('node-role.kubernetes.io/etcd') == 'true'
    for name in site.nodes:
        if name not in nodes and not site.nodes[name].has('gpu'):
            out['differences'].append(f'the node {name} of the site file is not in the cluster')
    folder = site.operator_state() / 'adoption'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'inventory-{time.strftime("%Y%m%dT%H%M%S")}.json'
    path.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    print(json.dumps({'inventory': str(path), 'differences': out['differences'], 'etcd_role': out['etcd_role']}, indent=1))


def tokens(site):
    node = site.nodes[site.control_plane]
    shell = hostroute.Shell(node)
    code, home = shell.run('echo "$HOME"', timeout=30)
    user = site.operator_user or os.environ.get('USER', '')
    folder = f'{home.strip()}/.hoover4-adopt'
    copy = (f'install -d -m 0700 -o {shlex.quote(user)} {folder} && '
            f'install -m 0600 -o {shlex.quote(user)} /var/lib/rancher/k3s/server/token {folder}/server-token && '
            f'if [ -s /var/lib/rancher/k3s/server/agent-token ]; then install -m 0600 -o {shlex.quote(user)} '
            f'/var/lib/rancher/k3s/server/agent-token {folder}/agent-token; fi')
    if shell.run('sudo -n true', timeout=30)[0] == 0:
        code, out = shell.run(f'sudo -n sh -c {shlex.quote(copy)}', timeout=120)
        if code:
            raise SystemExit(f'the token copy on {node.name} failed: {out[-200:]}')
    else:
        root = hostroute.ClusterRoot(k3s_settings.KUBECONFIG, shell)
        unit = f'hoover4-adopt-tokens-{int(time.time())}'
        root.start(unit, (), ['/bin/sh', '-c', copy])
        root.wait(unit)
    target = k3s_settings.PRIVATE / 'staging' / 'tokens'
    target.mkdir(parents=True, exist_ok=True)
    os.chmod(target, 0o700)
    written = []
    try:
        for name in ('server-token', 'agent-token'):
            code, value = shell.run(f'cat {folder}/{name} 2>/dev/null', timeout=30)
            value = value.strip()
            if name == 'agent-token' and not value:
                # The agents of a server without an agent token join with the secret of the server token.
                server = (target / 'server-token').read_text().strip()
                value = server.split('::', 1)[1].split(':', 1)[-1] if '::' in server else server
            if not value:
                raise SystemExit(f'{name} of {node.name} is empty.')
            path = target / name
            with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
                f.write(value + '\n')
            written.append(str(path))
    finally:
        shell.run(f'rm -rf {folder}', timeout=30)
    # The staging folder of each architecture copies the site tokens at its next use (deploy.tokens()).
    for arch in ('amd64', 'arm64'):
        for name in ('server-token', 'agent-token'):
            (k3s_settings.PRIVATE / 'staging' / arch / name).unlink(missing_ok=True)
    print(json.dumps({'tokens': written}))


def runners(site):
    shell = hostroute.Shell(site.nodes[site.control_plane])
    code, out = shell.run("systemctl --user list-units --all --no-legend --plain | grep -Ei 'operator|runner|hoover' ; "
                          "systemctl list-units --all --no-legend --plain | grep -Ei 'operator|runner' ; true", timeout=60)
    print(json.dumps({'node': site.control_plane, 'units': [line.split()[0] for line in out.splitlines() if line.strip()]}))


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('inventory', 'tokens', 'runners'))
    parser.add_argument('--site', default=str(k3s_settings.SITE_FILE))
    args = parser.parse_args(argv)
    site = config.read(args.site)
    {'inventory': inventory, 'tokens': tokens, 'runners': runners}[args.command](site)


if __name__ == '__main__':
    main(sys.argv[1:])
