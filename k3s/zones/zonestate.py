"""Read the persistent zone state: the zones, their home nodes, their storage tiers and their on and off switch.

k3s/private/zone-state.json names each zone, whether it is enabled, its home node, and the namespaces that it owns.
zone-state.example.json shows the format. The file is state, so Git does not track it. zone.py adds and removes zones.
A disabled zone keeps its manifests, credentials, databases and volumes, but no workload of it runs.
A file that is missing or invalid raises ZoneStateError. Callers must then treat every zone as disabled.
A namespace that no zone owns, such as calls or monitoring, is outside zone control.

Every pod of a zone runs on its home node. Each volume of the zone uses one storage tier of that node.
TIERS gives the tier list of each store. A zone entry can replace a list with its own "tiers" table.
The first tier of the list that the home node has wins, because TopoLVM does not fall back between device classes.
"*" stands for any tier of the node, in the order of TIER_ORDER. A node has a tier when it has the label
storage.tier/<tier>=true.
"""
import json
import subprocess
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'private' / 'zone-state.json'
SCHEMA = 1
TIER_ORDER = ['nvme', 'ssd', 'hdd']
FAST = ['nvme', 'ssd', 'hdd']
# The key "default" covers the volumes of the apps and every store that the table does not name.
TIERS = {'default': ['hdd', '*'], 'clickhouse': FAST, 'manticore': FAST, 'manticore-vectors': FAST}


class ZoneStateError(RuntimeError):
    pass


def load(path=PATH):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise ZoneStateError(f'the zone state {path} is unreadable: {error}') from None
    return validate(data)


def validate(data):
    if not isinstance(data, dict) or data.get('schemaVersion') != SCHEMA or not isinstance(data.get('zones'), dict):
        raise ZoneStateError('the zone state has no schema version 1 zone table')
    owners = {}
    for zone, entry in data['zones'].items():
        if not isinstance(entry, dict) or not isinstance(entry.get('enabled'), bool):
            raise ZoneStateError(f'the zone {zone} has no boolean enabled field')
        entry.setdefault('namespaces', [zone])
        for namespace in entry['namespaces']:
            if owners.setdefault(namespace, zone) != zone:
                raise ZoneStateError(f'the namespace {namespace} belongs to two zones')
    return data


def zone_of(namespace, data=None):
    """Return the zone that owns a namespace, or None for a namespace outside zone control."""
    data = load() if data is None else data
    for zone, entry in data['zones'].items():
        if namespace in entry['namespaces']:
            return zone
    # A zone namespace that the file does not list, such as a new zone, is controlled and therefore disabled.
    if namespace.startswith('zone-') or namespace.startswith('hoover-zone-'):
        return namespace.removeprefix('hoover-')
    return None


def enabled(zone, data=None):
    """Return True only for a zone that the file lists as enabled."""
    data = load() if data is None else data
    return data['zones'].get(zone, {}).get('enabled') is True


def namespace_enabled(namespace, data=None):
    """Return False for a namespace of a disabled or unknown zone. An unreadable file raises ZoneStateError."""
    data = load() if data is None else data
    zone = zone_of(namespace, data)
    return zone is None or enabled(zone, data)


def disabled_namespaces(data=None):
    data = load() if data is None else data
    return sorted(ns for zone, entry in data['zones'].items() if not entry['enabled'] for ns in entry['namespaces'])


def home(zone, data=None):
    """Return the home node of a zone."""
    data = load() if data is None else data
    entry = data['zones'].get(zone) or {}
    if not entry.get('home'):
        raise ZoneStateError(f'the zone {zone} has no home node')
    return entry['home']


def node_tiers(node, kubeconfig):
    """Return the storage tiers of a node from its storage.tier/<tier> labels."""
    labels = json.loads(subprocess.run(['kubectl', '--kubeconfig', str(kubeconfig), 'get', 'node', node, '-o', 'json'],
                                       check=True, capture_output=True, text=True).stdout)['metadata']['labels']
    return [k.split('/', 1)[1] for k, v in labels.items() if k.startswith('storage.tier/') and v == 'true']


def tier(zone, store, available, data=None):
    """Return the tier of a store of a zone, from the tier list and the tiers that the home node has."""
    data = load() if data is None else data
    tiers = {**TIERS, **(data['zones'].get(zone, {}).get('tiers') or {})}
    for wanted in tiers.get(store, tiers['default']):
        for name in ([t for t in TIER_ORDER if t in available] + sorted(set(available) - set(TIER_ORDER))) if wanted == '*' else [wanted]:
            if name in available:
                return name
    raise ZoneStateError(f'the home node of {zone} has none of the tiers {tiers.get(store, tiers["default"])} for {store}')


def save(data, path=PATH):
    """Write the zone state after a check of its format."""
    validate(data)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1) + '\n')
