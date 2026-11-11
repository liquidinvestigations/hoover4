#!/usr/bin/env python3
"""The Hoover data directories: an NFS server on each data node, and the dataset mounts of each zone.

The databases of a zone stay on local volumes of its home node. Only the data directories, which Hoover scans and
where uploads arrive, use NFS. Hoover pods on any node then read the same files.
hoover_data in k3s/private/settings.json holds the site values:
  roots  the data root of each node, for example {"node-a": "/srv/hoover-data"}. A node without a root gets
         DEFAULT_ROOT. The root has one folder for each zone, with testdata and uploads.
  zones  the data node of each zone. The default is the home node of the zone.
  extra  read-only host directories of a zone, for example
         {"zone-b": [{"name": "archive", "node": "node-b", "path": "/srv/archive"}]}
Each data node runs the Deployment nfs-<node> in the namespace hoover-data with the Service nfs-<node>.
The kubelet mounts NFS with the resolver of the host, which has no cluster names, so a pod names the Service address.
A zone has these dataset mounts below /data:
  testdata  read-only, the NFS path /<zone>/testdata on its data node. seed.py writes the demo corpus here.
  uploads   writable, /<zone>/uploads on its data node. Uploads arrive here.
  <name>    read-only, /extra/<zone>/<name>, one for each extra directory.
The NFS paths are relative to the data root, which the server exports as the NFS version 4 root.
The zone pod policy (../../zones/manifests/zone-pods.yaml) refuses an NFS path of another zone.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'zones'))
import settings  # noqa: E402

NS = 'hoover-data'
DEFAULT_ROOT = '/srv/hoover-data'
CONFIG = settings.HOST.get('hoover_data', {})


def root(node):
    return CONFIG.get('roots', {}).get(node, DEFAULT_ROOT)


def data_node(zone):
    import zonestate
    return CONFIG.get('zones', {}).get(zone) or zonestate.home(zone)


def extra(zone):
    return CONFIG.get('extra', {}).get(zone, [])


def nodes(zones):
    """The data nodes of the zones and of their extra directories, sorted."""
    found = {data_node(z) for z in zones}
    found |= {e['node'] for z in zones for e in extra(z)}
    return sorted(found)


def address(node):
    """The Service address of the NFS server of a node."""
    out = subprocess.run(['kubectl', '--kubeconfig', settings.KUBECONFIG, '-n', NS, 'get', 'service', f'nfs-{node}', '-o',
                          'jsonpath={.spec.clusterIP}'], capture_output=True, text=True)
    if out.returncode or not out.stdout.strip():
        raise SystemExit(f'the NFS server of {node} has no Service. Run k3s/platform/hoover-data/install-hoover-data.py.')
    return out.stdout.strip()


def mounts(zone):
    """The dataset mounts of a zone: name, NFS server address, export path, container path and writable flag.

    testdata comes first, because Hoover takes the first mount as DATASETS_MOUNT_PATH."""
    home = data_node(zone)
    rows = [('testdata', home, f'/{zone}/testdata', False), ('uploads', home, f'/{zone}/uploads', True)]
    rows += [(e['name'], e['node'], f"/extra/{zone}/{e['name']}", False) for e in extra(zone)]
    servers = {n: address(n) for n in {r[1] for r in rows}}
    return [{'name': name, 'server': servers[node], 'export': export, 'path': f'/data/{name}', 'writable': writable}
            for name, node, export, writable in rows]
