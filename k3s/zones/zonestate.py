"""Read the persistent zone state: the zones, their storage tiers and their on and off switch.

zone-state.json of the state folder of the site (../settings.py PRIVATE) is the list of the zones of the site. The site
file names no zone. Each entry names whether the zone is enabled, the namespaces that it owns, and
whether its first openDesk install completed (bootstrapped, which zone.py writes for a new zone). The value stores of
the Hoover installation of the zone is site for a new zone (the shared ClickHouse, Garage and Manticore of the site), local for a
Compose import, and zone for an entry without the value, from an earlier version (../config.py ZONE_VALUES). The value
temporal is site for a new zone of the layout site (the Temporal of the site, with a namespace for the zone), and zone
otherwise (the default). The value manticore is site for a new zone of the layout site (the Manticore daemons of the
site, with three users of the zone), and zone otherwise (the default). extra_datasets lists read-only dataset folders of data nodes as name:node:/path.
../config.py zone_hoover() reads these values and derives the storage names from the zone id.
zone-state.example.json shows the format. The file is state, so Git does not track it. zone.py and the zone runner of
the operator portal add and remove zones.
A disabled zone keeps its manifests, credentials, databases and volumes, but no workload of it runs.
A file that is missing or invalid raises ZoneStateError. Callers must then treat every zone as disabled.
A namespace that no zone owns, such as calls or monitoring, is outside zone control.

A zone has no home node. The scheduler places each pod of a zone by its requests, and a pod with a local volume stays
on the node of its volume (TopoLVM). An entry of an earlier version can keep the value home: only the data node choice
of ../config.py Hoover.data_node() reads it.
Each volume of the zone uses one storage tier. TIERS gives the tier list of each store. A zone entry can replace a list
with its own "tiers" table. The first tier of the list that a node of the site has wins, because TopoLVM does not fall
back between device classes. The scheduler then binds the volume on a node with that tier and free capacity.
"*" stands for any tier of the site, in the order of TIER_ORDER. A node has a tier when it has the label
storage.tier/<tier>=true.

zone-definitions.json of the state folder holds the intended zones apart from their state (DEFINITIONS): for each zone
the switch enabled, the store layout, the extra datasets and the tier lists. It holds no credential and no runtime
value, such as bootstrapped or the result of a move. zone.py register() adds a new zone and zone.py delete removes it,
so the file follows the zone state. deploy-k3s reset (../driver/reset.py) keeps the file and removes the zone state, and
the next deploy-k3s up creates each zone of the file that the zone state lacks (intended()). A zone of the store layout
zone or local of an earlier version keeps its layout in the file. zone.py refuses a new zone of the layout zone.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
import settings  # noqa: E402

PATH = settings.PRIVATE / 'zone-state.json'
DEFINITIONS = settings.PRIVATE / 'zone-definitions.json'
SCHEMA = 1
# The values of a zone entry that define the zone. The other values are state.
DEFINED = ('enabled', 'stores', 'extra_datasets', 'tiers')
TIER_ORDER = ['nvme', 'ssd', 'hdd']
FAST = ['nvme', 'ssd', 'hdd']
# The key "default" covers the volumes of the apps and every store that the table does not name.
TIERS = {'default': ['hdd', '*'], 'clickhouse': FAST, 'manticore': FAST, 'manticore-vectors': FAST,
         'temporal-cassandra': FAST, 'temporal-opensearch': FAST}


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
        problems = config.zone_problems(zone, entry)
        if problems:
            raise ZoneStateError('; '.join(problems))
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


def site_tiers(kubeconfig):
    """Return the storage tiers of the site: every tier that a node has as a storage.tier/<tier>=true label."""
    nodes = json.loads(subprocess.run(['kubectl', '--kubeconfig', str(kubeconfig), 'get', 'nodes', '-o', 'json'],
                                      check=True, capture_output=True, text=True).stdout)['items']
    return sorted({k.split('/', 1)[1] for n in nodes for k, v in n['metadata'].get('labels', {}).items()
                   if k.startswith('storage.tier/') and v == 'true'})


def tier(zone, store, available, data=None):
    """Return the tier of a store of a zone, from the tier list and the tiers of the site."""
    data = load() if data is None else data
    tiers = {**TIERS, **(data['zones'].get(zone, {}).get('tiers') or {})}
    for wanted in tiers.get(store, tiers['default']):
        for name in ([t for t in TIER_ORDER if t in available] + sorted(set(available) - set(TIER_ORDER))) if wanted == '*' else [wanted]:
            if name in available:
                return name
    raise ZoneStateError(f'the site has none of the tiers {tiers.get(store, tiers["default"])} for {store} of {zone}')


def save(data, path=PATH):
    """Write the zone state after a check of its format."""
    validate(data)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=1) + '\n')


def definition(entry):
    """The defining values of a zone state entry (DEFINED)."""
    return {k: entry[k] for k in DEFINED if k in entry and entry[k] not in (None, '', [], {})}


def definitions(path=DEFINITIONS):
    """{zone: definition} of the zone definitions file. A missing file gives {}."""
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ZoneStateError(f'the zone definitions {path} are unreadable: {error}') from None
    if not isinstance(data, dict) or data.get('schemaVersion') != SCHEMA or not isinstance(data.get('zones'), dict):
        raise ZoneStateError(f'the zone definitions {path} have no schema version 1 zone table')
    for zone, entry in data['zones'].items():
        problems = config.zone_problems(zone, entry)
        if problems:
            raise ZoneStateError('; '.join(problems))
    return data['zones']


def save_definitions(zones, path=DEFINITIONS):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(path).with_name(f'.{Path(path).name}.tmp')
    tmp.write_text(json.dumps({'schemaVersion': SCHEMA, 'zones': zones}, indent=1, sort_keys=True) + '\n')
    tmp.replace(path)


def _locked(path):
    """An exclusive lock of the definitions file, so zone steps that run at the same time do not lose a change."""
    import contextlib
    import fcntl

    @contextlib.contextmanager
    def hold():
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(Path(path).with_name(f'.{Path(path).name}.lock'), 'a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield
    return hold()


def define(zone, entry, path=DEFINITIONS):
    """Keep the definition of a zone from its zone state entry."""
    with _locked(path):
        zones = definitions(path)
        if zones.get(zone) != definition(entry):
            zones[zone] = definition(entry)
            save_definitions(zones, path)


def undefine(zone, path=DEFINITIONS):
    with _locked(path):
        zones = definitions(path)
        if zone in zones:
            del zones[zone]
            save_definitions(zones, path)


def intended(path=DEFINITIONS, state_path=PATH):
    """{zone: definition} of the zones that the site must have: the definitions, and each zone of the zone state that
    the definitions lack, for example a zone of a version before the file."""
    zones = dict(definitions(path))
    try:
        state = load(state_path)['zones']
    except ZoneStateError:
        state = {}
    for zone, entry in state.items():
        zones.setdefault(zone, definition(entry))
    return zones
