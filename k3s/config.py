#!/usr/bin/env python3
"""Read and check the site file of a cluster installation.

The site file is a YAML Ansible inventory with one group, hoover4. The group variables (hoover4.vars) are the site
values, and each host of the group (hoover4.hosts) is one node with its values as host variables. The file names the
resources of the installation, the roles of its nodes and the host changes that the installer makes on each node. It
holds no SSH address, port or user, no port of a service, no tuning, no application switch, no backup schedule and no
secret value. Tunings, application switches and schedules are operator settings (platform/operator/settings.py). A
secret is a reference to a private file on the node that reads it.

  hoover4:
    vars:                domain, control_plane, and the optional mappings networks, lans, gpu_pool, backup, stores,
                         deploy and replicas
      networks:          one entry per WireGuard network: interface, cidr, hubs, port and managed (NETWORK_KEYS)
      lans:              one entry per LAN, with an optional cidr
      gpu_pool:          the GPU services: the GPU nodes of the site, or the address of a shared pool
      backup:            one node and one host folder that receive the backups
      stores:            the nodes of the shared Hoover stores, the node count of each store that shards its data, the
                         Temporal pods, the Cassandra data size, the history shard count of the site Temporal and the
                         planned zone count (STORES_KEYS, STORE_PARTS)
      replicas:          the pod count of each stateless processing service of the zones (REPLICA_KEYS)
    hosts:
      <node>:            node_roles, local, ssh_host, networks (its address in each network), lan (its LAN address),
                         public_address, storage (tier: volume group), the switches k3s_volume_group, stop_docker and
                         public_firewall, the TLS mode of a public node and its secret files

The probe of each node (the role hoover4_facts of ansible/) reads the architecture, AVX2, the GPUs and the volume groups
into facts/<node>.json of the state folder. The role hoover4_speed measures the CPU speed and the disk speeds of a node
once, while k3s does not run, into speed/<node>.json (node_speed()). The site file does not state them.
The state folder of a site is beside the site file and has the name of the file without its extension
(state_folder()). The site id is the domain with each . replaced by - (Site.id).
The driver connects to a node with `ssh <node name>` and the SSH configuration of the current user. ssh_host names
another alias of that configuration for the node. The local node of a single-node site connects to localhost.
The node roles are control-plane, worker, public, registry, data, calls and gpu. The value `single` gives one host
every role except calls and gpu. A site with one node needs no network, no LAN address and no public address.
Each zone host is <zone>-<app>.<domain> (zone_host()).
The site file names no zone. The zone state of the state folder (zone-state.json, ../zones/zonestate.py) holds each
zone, and hoovers() gives the Hoover installation of each zone. The storage names of an installation come from its
zone id (Hoover). The GPU services share one generated key, which the cluster keeps in a Secret (../hoover/gpu.py).

parse() refuses an unknown group, an unknown key, a missing resource and an incompatible role combination, and names
every problem in one message. It changes nothing on any host. The import of a Compose install is a separate command
(import_compose/), and the site file has no key for it.
A YAML site file needs PyYAML. A site file in JSON form needs only the standard library.

Usage: config.py check <site file>           checks the file and prints its summary as JSON
       config.py project <site file> <node>  prints the part of the site that one node receives
       config.py ansible <site file>         prints the variables that the driver gives to the host plays as JSON
"""
import ipaddress
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STORAGE_IDENTITY = REPO / 'main_services/processing/tasks/storage_identity.json'


def state_folder(site_path):
    """The state folder of a site file: the folder beside the file with the name of the file without its extension."""
    return Path(site_path).resolve().with_suffix('')


# The fixed address of the local node of a single-node site. The host script puts it on the dummy link hoover4, so
# k3s, the registry, the HTTPS frontend and the local DNS server keep one address when the LAN address changes.
LOCAL_ADDRESS = '10.254.54.1'
# The fixed Service address of the cluster ingress, inside the default k3s Service range 10.43.0.0/16.
INGRESS_ADDRESS = '10.43.0.80'
REGISTRY_PORT = 5000

ROLES = ('control-plane', 'worker', 'public', 'registry', 'data', 'calls', 'gpu')
# The TLS modes of the HTTPS frontend of the public node, and the site file keys that each mode needs.
#   cloudflare  a public wildcard certificate from certbot with the Cloudflare DNS challenge
#   internal    certificates of the local CA of Caddy on the public node. The pods trust that CA, and the state folder
#               gets its root certificate frontend/local-ca.crt for the browsers.
#   files       the certificate and key files that the person puts on the public node
TLS_MODES = {'cloudflare': ('tls_dns_credentials_file',), 'internal': (), 'files': ('tls_certificate_file', 'tls_key_file')}
TLS_KEYS = ('tls_dns_credentials_file', 'tls_certificate_file', 'tls_key_file')
SINGLE = ('control-plane', 'worker', 'public', 'registry', 'data')
# The storage tiers, in the order of the default storage class (../cluster/topolvm_values.py).
TIERS = ('hdd', 'ssd', 'nvme')
NAME = re.compile(r'[a-z][a-z0-9-]{0,31}')
ZONE = re.compile(r'zone-[a-z0-9]{1,12}')
GROUP = 'hoover4'
# The share of each volume group that TopoLVM keeps free (spare-gb of a device class). The cluster schedules at most
# the rest of the capacity of each tier on each node.
STORAGE_RESERVE = 0.05

# Each key of a section: (required, kind). Kinds: text, name, bool, address, cidr, path, list, roles, choice values,
# secret (the absolute path of a private file), alias (an SSH host alias).
SITE_KEYS = {'domain': (True, 'domain'), 'control_plane': (True, 'name')}
# The mappings of hoover4.vars beside the site values.
SITE_MAPPINGS = ('networks', 'lans', 'gpu_pool', 'backup', 'stores', 'deploy', 'replicas')
# A WireGuard network: vars.networks.<name>. hubs names the nodes that every other node of the network peers with.
# Without hubs, every node peers with every other node. managed: the installer writes and starts the interface on each
# node of the network and adds its peers. Without it, the installer reads the interface and changes nothing on it.
NETWORK_KEYS = {'interface': (False, 'interface'), 'cidr': (True, 'cidr'), 'hubs': (False, 'names'),
                'port': (False, 'port'), 'managed': (False, 'bool')}
# The values of one node in a network: hosts.<node>.networks.<name>, an address or a mapping with these keys.
# interface, port and managed replace the values of the network for this node.
MEMBER_KEYS = {'address': (True, 'address'), 'public_key': (False, 'wgkey'), 'interface': (False, 'interface'),
               'port': (False, 'port'), 'managed': (False, 'bool')}
# A LAN: vars.lans.<name>. Two nodes on one LAN reach each other at their LAN addresses. A cidr also admits the admin
# routes of the HTTPS frontend from that range, as the cidr of each network does.
LAN_KEYS = {'cidr': (False, 'cidr')}
# The mappings of a node beside its values.
NODE_MAPPINGS = ('networks', 'lan', 'storage')
NODE_KEYS = {
    # Ansible reserves the variable name roles, so the node roles have the key node_roles.
    'node_roles': (True, 'roles'), 'local': (False, 'bool'), 'ssh_host': (False, 'alias'),
    'public_address': (False, 'address'), 'k3s_volume_group': (False, 'name_any'), 'stop_docker': (False, 'bool'),
    'public_firewall': (False, 'bool'), 'reserved': (False, 'reserved'), 'data_root': (False, 'path'),
    'tls_mode': (False, ('choice', tuple(TLS_MODES))), 'tls_dns_credentials_file': (False, 'secret'),
    'tls_certificate_file': (False, 'secret'), 'tls_key_file': (False, 'secret'),
}
# The GPU pool names nodes or an address. Its key is a generated Secret of the cluster, so the site file names no key.
GPU_POOL_KEYS = {'nodes': (False, 'names'), 'address': (False, 'address')}
BACKUP_KEYS = {'node': (True, 'name'), 'path': (True, 'path')}
# The deployment driver (driver/deploy.py): vars.deploy.
#   parallel_zones  the count of zone steps that deploy-k3s up runs at the same time. Default: PARALLEL_ZONES.
DEPLOY_KEYS = {'parallel_zones': (False, 'count')}
PARALLEL_ZONES = 2
# The shared Hoover stores of the site (../hoover/stores/shared.py, ../hoover/stores/temporal.py): vars.stores. Each
# store keeps one copy of each part of its data. ClickHouse runs one pod. Garage, Cassandra and OpenSearch can shard
# their data over several nodes, one pod on each node. A lost node loses its part until it returns, and the backups are
# the recovery path.
#   nodes     the nodes that can run a store pod. Default: every node with the role worker and a storage tier.
#   history_shards  the history shard count of the Temporal of the site. Default: HISTORY_SHARDS. Temporal keeps the
#             count of its creation, so a change is refused (deploy check).
#   zones     the zone count that the placement of the store pods reserves memory and CPU for
#             (../hoover/stores/placement.py). Default: the zones of the zone state, at least 1.
#   garage.nodes      the Garage node count. Default: the store node count, at most 3.
#   cassandra.nodes   the Cassandra node count. Default: 1.
#   cassandra.data_gib  the live data of Cassandra in GiB, which sets its heap (../hoover/stores/temporal.py). Default: 2.
#   opensearch.nodes  the OpenSearch node count. Default: 1.
#   temporal.pods     the Temporal pod count. Temporal holds no data. Default: 1.
# A store node count cannot become smaller than the count of the last apply, because the removed nodes hold a part of
# the data (deploy check).
STORES_KEYS = {'nodes': (False, 'names'), 'history_shards': (False, 'count'), 'zones': (False, 'count')}
STORE_PARTS = {'garage': {'nodes': (False, 'count')}, 'cassandra': {'nodes': (False, 'count'), 'data_gib': (False, 'count')},
               'opensearch': {'nodes': (False, 'count')}, 'temporal': {'pods': (False, 'count')}}
# The replica count of each stateless processing service of every zone: vars.replicas.<service>. Default: 1. Each
# service runs its pods behind its Service, which spreads the connections over the ready pods. The deploy check refuses
# counts whose requests do not fit the nodes (../hoover/stores/shared.py plan). The other services of a zone run one
# pod, or scale by their own setting (budget.worker_pods of the workers), see ../hoover/manifests.py SCALABLE.
REPLICA_SERVICES = ('tika', 'tesseract-cpu', 'ocr-pdf', 'pdf-search', 'regex-entity-scanner', 'clamav')
REPLICA_KEYS = {k: (False, 'count') for k in REPLICA_SERVICES}
# The history shard count of a new site Temporal. The Compose default (deploy.py temporal_history_shards) is the same.
HISTORY_SHARDS = 128
# The values of a zone entry of the zone state that the Hoover installation of the zone reads (zone_hoover()):
# stores, the store layout, temporal, the place of the Temporal of the zone, and manticore, the place of the Manticore
# daemons of the zone, each with its default first.
# extra_datasets lists read-only dataset folders of data nodes as name:node:/path.
# The store layouts: site (ClickHouse, Garage and Manticore are the shared stores of the site), local (the Compose stores in the Hoover namespace, from the Compose import), and zone (every store in the
# zone namespace, from an earlier version). An entry without the value is a zone of that earlier version. A new zone
# gets site (../zones/zone.py register()). The installer refuses to apply a zone with the layout zone: delete the zone
# and create it again.
# The Temporal places: site (the Temporal of the site in hoover-stores, with one namespace for each zone), and zone
# (the Temporal of the zone itself). A zone with stores = local runs the Compose Temporal in its Hoover namespace. A
# zone with stores = site and temporal = zone is from an earlier version, whose Temporal ran on the PostgreSQL of the
# zone. The installer refuses it: delete the zone and create it again. A new zone with stores = site gets site.
# The Manticore places: site (the two Manticore daemons of the site in hoover-stores, with three users of the zone and
# the schema proxy of the zone), and zone (two Manticore daemons in the zone namespace). A zone with stores = site and
# manticore = zone is from an earlier version. The installer refuses it: delete the zone and create it again. A new
# zone with stores = site gets site.
ZONE_VALUES = {'stores': ('zone', 'local', 'site'), 'temporal': ('zone', 'site'), 'manticore': ('zone', 'site')}
# The defaults of the optional keys. A key without a default here is empty. public_firewall has no default here: it is
# true on a public or calls node with a public address (parse).
DEFAULTS = {
    'node': {'local': 'false', 'stop_docker': 'false', 'data_root': '/srv/hoover-data'},
    'network': {'interface': 'wg0', 'port': '51820', 'managed': 'true'},
}
# The secret files that each role reads.
SECRET_ROLES = {'tls_dns_credentials_file': 'public', 'tls_certificate_file': 'public', 'tls_key_file': 'public'}
# The storage identity keys of a Hoover installation and the names in storage_identity.json.
IDENTITY = {'clickhouse_database_prefix': 'clickhouse_database_prefix', 'manticore_table_prefix': 'manticore_table_prefix',
            'system_bucket': 'system_bucket', 'collection_bucket_prefix': 'collection_bucket_prefix'}


class SiteError(ValueError):
    """The site file or the zone state has problems. The message names each problem."""


@dataclass
class Member:
    """The values of one node in one network. interface, port and managed are the effective values: the values of the
    node, else the values of the network."""
    address: str
    interface: str
    port: int
    managed: bool
    public_key: str = ''


@dataclass
class Network:
    name: str
    cidr: str
    interface: str = 'wg0'
    port: int = 51820
    managed: bool = True
    hubs: tuple = ()


@dataclass
class Node:
    name: str
    roles: tuple
    local: bool = False
    # The SSH alias of the node. Empty: the node name, or localhost for the local node (ssh_host()).
    ssh_host: str = ''
    # {network name: Member}, in the order of vars.networks.
    networks: dict = field(default_factory=dict)
    # {LAN name: address}.
    lan: dict = field(default_factory=dict)
    public_address: str = ''
    # {tier: volume group}. The person creates each volume group. The installer changes no disk.
    storage: dict = field(default_factory=dict)
    # The volume group of the k3s data volumes /var/lib/rancher and /var/lib/kubelet, or empty to keep them on the root
    # file system.
    k3s_volume_group: str = ''
    stop_docker: bool = False
    public_firewall: bool = False
    reserved: str = ''
    data_root: str = '/srv/hoover-data'
    # Empty: internal on the local node, else cloudflare (tls_mode()).
    tls_mode: str = ''
    tls_dns_credentials_file: str = ''
    tls_certificate_file: str = ''
    tls_key_file: str = ''

    def has(self, role):
        return role in self.roles

    @property
    def tiers(self):
        """The storage tiers of the node, in the order of TIERS."""
        return tuple(t for t in TIERS if t in self.storage)


@dataclass
class Hoover:
    """The Hoover installation of one zone, from the zone entry of the zone state (zone_hoover()).

    The installation has the name of its zone. Its storage names come from the zone id: for zone-x the ClickHouse
    database prefix zone_x, the Manticore table prefix zone_x_, the system bucket zone-x-system and the collection
    bucket prefix zone-x-c-.
    """
    zone: str
    stores: str = 'zone'
    temporal: str = 'zone'
    manticore: str = 'zone'
    extra_datasets: tuple = ()
    # The value home of a zone entry of an earlier version. Only data_node() reads it, so the data folder of such a zone
    # stays on its node. No pod and no volume of the zone uses it.
    legacy_home: str = ''

    def data_node(self, site):
        """The data node of the NFS data folders of the zone: the legacy home node when it has the role data, else the
        first node with the role data. ../platform/hoover-data/hoover_data.py chooses the same node."""
        data_nodes = [n.name for n in site.with_role('data')]
        return self.legacy_home if self.legacy_home in data_nodes else data_nodes[0]

    @property
    def name(self):
        return self.zone

    @property
    def namespace(self):
        return 'hoover-' + self.zone

    @property
    def clickhouse_database_prefix(self):
        return self.zone.replace('-', '_')

    @property
    def manticore_table_prefix(self):
        return self.zone.replace('-', '_') + '_'

    @property
    def system_bucket(self):
        return f'{self.zone}-system'

    @property
    def collection_bucket_prefix(self):
        return f'{self.zone}-c-'

    def identity(self):
        """The storage identity as the environment variables of storage_identity.json."""
        names = json.loads(STORAGE_IDENTITY.read_text())['settings']
        return {names[IDENTITY[k]]['variable']: getattr(self, k) for k in IDENTITY}


@dataclass
class Site:
    domain: str
    control_plane: str
    nodes: dict
    # {name: Network}, in the order of the site file. The first network is the cluster network (node_address()).
    networks: dict = field(default_factory=dict)
    # {name: cidr or empty}.
    lans: dict = field(default_factory=dict)
    gpu_pool: dict = field(default_factory=dict)
    backup: dict = field(default_factory=dict)
    # vars.stores as given in the site file. store_plan() adds the defaults.
    stores: dict = field(default_factory=dict)
    # vars.deploy as given in the site file.
    deploy: dict = field(default_factory=dict)
    # vars.replicas as given in the site file: {service: count}. A missing service has 1 pod.
    replicas: dict = field(default_factory=dict)
    # The site file that read() parsed, or empty for parse().
    path: str = ''

    @property
    def id(self):
        """The site id: the domain with each . replaced by -, for example k8-example-org."""
        return self.domain.replace('.', '-')

    @property
    def single(self):
        return len(self.nodes) == 1

    def with_role(self, role):
        return [n for n in self.nodes.values() if n.has(role)]

    def state_folder(self):
        """The state folder of the site file. A Site of parse() has no file, so it has no state folder."""
        if not self.path:
            raise SiteError('this site has no site file, so it has no state folder.')
        return state_folder(self.path)

    def operator_state(self):
        """The folder of the operator state: operator/ of the state folder."""
        return self.state_folder() / 'operator'

    def zone_state(self):
        """The zone state file of the site: zone-state.json of the state folder (../zones/zonestate.py)."""
        return self.state_folder() / 'zone-state.json'


# ----------------------------------------------------------------------------------------------------------------------
# Zones
# ----------------------------------------------------------------------------------------------------------------------

def zone_host(zone, app, domain):
    """The host name of an application of a zone: <zone>-<app>.<domain>, for example zone-a-portal.example.org.

    A zone id has one - (ZONE), so the first two parts of the first label always name the zone. The certificate of
    *.<domain> covers every zone host, so a zone add or delete changes no certificate and no DNS record.
    """
    return f'{zone}-{app}.{domain}'


def zone_domain(zone, domain):
    """The mail domain and the Matrix server name of a zone: <zone>.<domain>. *.<domain> covers it too."""
    return f'{zone}.{domain}'


def zone_problems(zone, entry, site=None):
    """The problems of the Hoover values of one zone entry of the zone state, as messages. With a site, the check
    also needs a data node for each extra dataset. A zone has no home node: the scheduler places its pods, and an old
    value home has no effect on the placement."""
    label = f'the zone {zone}'
    problems = []
    if not ZONE.fullmatch(zone):
        problems.append(f'{label} must be zone- and 1 to 12 characters from a-z and 0-9.')
    for key, choices in ZONE_VALUES.items():
        if entry.get(key, choices[0]) not in choices:
            problems.append(f'{label} has {key} = {entry.get(key)}, which is not one of {", ".join(choices)}.')
    datasets = _value(f'{label} extra_datasets', 'datasets', _raw(entry.get('extra_datasets') or ''), problems) or ()
    if site is None:
        return problems
    for name, node_name, _ in datasets:
        if node_name not in site.nodes or not site.nodes[node_name].has('data'):
            problems.append(f'{label} extra_datasets names {node_name}, which is not a node with the role data.')
        if name in ('testdata', 'uploads'):
            problems.append(f'{label} extra_datasets uses the reserved name {name}.')
    if datasets and site.single:
        problems.append(f'{label} has extra_datasets, which only a site with NFS data folders reads.')
    return problems


def zone_hoover(zone, entry, site=None):
    """The Hoover installation of one zone entry of the zone state. A value outside ZONE_VALUES raises SiteError."""
    problems = zone_problems(zone, entry, site)
    if problems:
        raise SiteError(f'the zone state has {len(problems)} problem{"s" if len(problems) != 1 else ""}:\n    '
                        + '\n    '.join(problems))
    datasets = _value('extra_datasets', 'datasets', _raw(entry.get('extra_datasets') or ''), []) or ()
    return Hoover(zone=zone, legacy_home=entry.get('home', ''), extra_datasets=datasets,
                  **{k: entry.get(k, choices[0]) for k, choices in ZONE_VALUES.items()})


def hoovers(site, data=None):
    """{zone: Hoover} of every zone of the zone state of a site, in the order of the file.

    data is the parsed zone state. Without it, the function reads the zone state file of the site. A site without a
    file or without a zone state has no zone. The function checks the values of each entry, and zones_problems()
    checks them against the nodes of the site.
    """
    return {zone: zone_hoover(zone, entry) for zone, entry in _zone_entries(site, data).items()}


def zones_problems(site, data=None):
    """The problems of every zone of the zone state of a site, with the checks against its nodes, as messages."""
    return [p for zone, entry in _zone_entries(site, data).items() for p in zone_problems(zone, entry, site)]


def _zone_entries(site, data):
    if data is None:
        if not site.path or not site.zone_state().exists():
            return {}
        try:
            data = json.loads(site.zone_state().read_text())
        except (OSError, ValueError) as error:
            raise SiteError(f'the zone state {site.zone_state()} is unreadable: {error}') from None
    zones = data.get('zones') if isinstance(data, dict) else None
    if not isinstance(zones, dict):
        raise SiteError('the zone state has no zone table.')
    return zones


# ----------------------------------------------------------------------------------------------------------------------
# Values
# ----------------------------------------------------------------------------------------------------------------------

def _value(label, kind, raw, problems):
    """The typed value of one raw text, or None after a problem."""
    raw = raw.strip()
    if isinstance(kind, tuple) and kind[0] == 'choice':
        if raw not in kind[1]:
            problems.append(f'{label} = {raw} is not one of {", ".join(kind[1])}.')
            return None
        return raw
    if kind == 'wgkey':
        # A WireGuard key is base64 text. A space in it comes from a copy of a wrapped line, and wg refuses it.
        if raw and not re.fullmatch(r'[A-Za-z0-9+/=_-]+', raw):
            problems.append(f'{label} is not a WireGuard public key: it has a space or another character outside base64.')
            return None
        return raw
    if kind == 'interface':
        # A Linux interface name has at most 15 characters.
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', raw):
            problems.append(f'{label} = {raw} is not a network interface name.')
            return None
        return raw
    if kind == 'alias':
        # The alias of a Host entry of the SSH configuration. An address belongs to that configuration.
        try:
            ipaddress.ip_address(raw)
        except ValueError:
            pass
        else:
            problems.append(f'{label} = {raw} is an address. Name a Host alias of the SSH configuration instead.')
            return None
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', raw):
            problems.append(f'{label} = {raw} is not an SSH host alias.')
            return None
        return raw
    if kind in ('text', 'name_any'):
        if kind == 'name_any' and raw and not re.fullmatch(r'[A-Za-z0-9_.+-]+', raw):
            problems.append(f'{label} = {raw} is not a valid name.')
            return None
        return raw
    if kind == 'name':
        if not NAME.fullmatch(raw):
            problems.append(f'{label} = {raw} must start with a-z and have at most 32 characters from a-z, 0-9 and -.')
            return None
        return raw
    if kind == 'zone':
        if not ZONE.fullmatch(raw):
            problems.append(f'{label} = {raw} must be zone- and 1 to 12 characters from a-z and 0-9.')
            return None
        return raw
    if kind == 'domain':
        if not re.fullmatch(r'[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+', raw):
            problems.append(f'{label} = {raw} is not a domain name.')
            return None
        return raw
    if kind == 'bool':
        if raw.lower() in ('true', 'yes', '1', 'on'):
            return True
        if raw.lower() in ('false', 'no', '0', 'off'):
            return False
        problems.append(f'{label} = {raw} must be true or false.')
        return None
    if kind == 'count':
        if not raw.isdigit() or int(raw) < 1:
            problems.append(f'{label} = {raw} must be a whole number of at least 1.')
            return None
        return int(raw)
    if kind == 'port':
        if not raw.isdigit() or not 0 < int(raw) < 65536:
            problems.append(f'{label} = {raw} is not a port number.')
            return None
        return int(raw)
    if kind == 'address':
        try:
            ipaddress.ip_address(raw)
        except ValueError:
            problems.append(f'{label} = {raw} is not an IP address.')
            return None
        return raw
    if kind == 'cidr':
        try:
            ipaddress.ip_network(raw)
        except ValueError:
            problems.append(f'{label} = {raw} is not an address range such as 10.0.0.0/24.')
            return None
        return raw
    if kind in ('path', 'secret'):
        if not os.path.isabs(raw) or os.path.normpath(raw) != raw.rstrip('/') or '\n' in raw:
            problems.append(f'{label} = {raw} must be an absolute, normalized path.')
            return None
        return raw
    if kind in ('roles', 'names'):
        items = tuple(p.strip() for p in raw.split(',') if p.strip())
        if kind == 'roles':
            if items == ('single',):
                return SINGLE
            unknown = [i for i in items if i not in ROLES]
            if unknown or not items:
                problems.append(f'{label} = {raw} must be single or a list of {", ".join(ROLES)}.')
                return None
            return tuple(r for r in ROLES if r in items)
        return items
    if kind == 'reserved':
        if raw and not re.fullmatch(r'(memory|cpu)=[0-9]+[A-Za-z]*(,(memory|cpu)=[0-9]+[A-Za-z]*)*', raw):
            problems.append(f'{label} = {raw} must look like memory=6Gi,cpu=2.')
            return None
        return raw
    if kind == 'datasets':
        # name:node:/absolute/path, separated by commas. Each is a read-only dataset folder of a data node.
        items = []
        for part in (p.strip() for p in raw.split(',') if p.strip()):
            pieces = part.split(':', 2)
            if len(pieces) != 3 or not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', pieces[0]) or not NAME.fullmatch(pieces[1]) \
                    or not os.path.isabs(pieces[2]) or os.path.normpath(pieces[2]) != pieces[2].rstrip('/'):
                problems.append(f'{label} has {part}, which is not name:node:/absolute/path.')
                return None
            items.append(tuple(pieces))
        return tuple(items)
    raise AssertionError(kind)


def _raw(value):
    """The text form of a YAML value: a list is a comma-separated text, a boolean is true or false."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (list, tuple)):
        return ', '.join(_raw(v) for v in value)
    if value is None:
        return ''
    return str(value)


def _section(label, values, keys, defaults, problems):
    """The typed values of one mapping of the site file. Unknown keys and missing required keys are problems."""
    out = {}
    for key in sorted(set(values) - set(keys)):
        problems.append(f'{label} {key} is not a known key. The keys are {", ".join(keys)}.')
    for key, (required, kind) in keys.items():
        name = f'{label} {key}'
        if key in values:
            if isinstance(values[key], dict):
                problems.append(f'{name} is a mapping. It needs a value.')
                continue
            raw = _raw(values[key])
            if raw.strip() == '' and not required:
                continue
            if raw.strip() == '':
                problems.append(f'{name} is empty.')
                continue
            value = _value(name, kind, raw, problems)
            if value is not None:
                out[key] = value
        elif required:
            problems.append(f'{label} has no {key}.')
        elif key in defaults:
            out[key] = _value(name, kind, defaults[key], problems)
    return out


# ----------------------------------------------------------------------------------------------------------------------
# The site file
# ----------------------------------------------------------------------------------------------------------------------

def _load(text):
    """The document of a site file text. JSON needs no PyYAML, because a JSON document is also a YAML document."""
    try:
        import yaml
    except ImportError:
        try:
            return json.loads(text)
        except ValueError:
            raise SiteError('the site file is YAML, and this Python has no PyYAML. Install PyYAML, or give the site '
                            'file in JSON form.') from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise SiteError(f'the site file cannot be parsed: {error}') from None


def _mapping(value, label, problems):
    """value when it is a mapping or empty, else a problem and an empty mapping."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.append(f'{label} is not a mapping.')
        return {}
    return value


def _members(label, value, networks, problems):
    """{network name: Member} of hosts.<node>.networks. Each value is an address or a mapping of MEMBER_KEYS."""
    out = {}
    for name, entry in _mapping(value, f'{label} networks', problems).items():
        name = str(name)
        where = f'{label} networks.{name}'
        if name not in networks:
            problems.append(f'{where}: the site has no network {name} in vars.networks.')
            continue
        values = _section(where, _mapping(entry, where, problems) if isinstance(entry, dict) else {'address': entry},
                          MEMBER_KEYS, {}, problems)
        if 'address' not in values:
            continue
        network = networks[name]
        out[name] = Member(address=values['address'], public_key=values.get('public_key', ''),
                           interface=values.get('interface', network.interface), port=values.get('port', network.port),
                           managed=values.get('managed', network.managed))
    # The order of vars.networks, so the first network of a node is its first network of the site.
    return {name: out[name] for name in networks if name in out}


def _lan(label, value, lans, problems):
    """{LAN name: address} of hosts.<node>.lan."""
    out = {}
    for name, address in _mapping(value, f'{label} lan', problems).items():
        name = str(name)
        if name not in lans:
            problems.append(f'{label} lan.{name}: the site has no LAN {name} in vars.lans.')
            continue
        typed = _value(f'{label} lan.{name}', 'address', _raw(address), problems)
        if typed:
            out[name] = typed
    return out


def _storage(label, value, problems):
    """{tier: volume group} of hosts.<node>.storage."""
    out = {}
    for tier, group in _mapping(value, f'{label} storage', problems).items():
        tier = str(tier)
        if tier not in TIERS:
            problems.append(f'{label} storage.{tier} is not a storage tier. The tiers are {", ".join(TIERS)}.')
            continue
        typed = _value(f'{label} storage.{tier}', 'name_any', _raw(group), problems)
        if typed:
            out[tier] = typed
        elif typed == '':
            problems.append(f'{label} storage.{tier} names no volume group.')
    return out


def parse(text, check_files=False):
    """The Site of a site file text. check_files also checks that the secret files of the local node exist."""
    document = _load(text)
    problems = []
    if not isinstance(document, dict) or GROUP not in document:
        raise SiteError(f'the site file has no group {GROUP}. It needs {GROUP}: with vars: and hosts:.')
    for name in sorted(set(document) - {GROUP}):
        problems.append(f'the group {name} is not known. The site file has one group, {GROUP}.')
    group = _mapping(document[GROUP], GROUP, problems)
    for name in sorted(set(group) - {'vars', 'hosts'}):
        problems.append(f'{GROUP}.{name} is not known. The group has vars and hosts.')
    variables = _mapping(group.get('vars'), 'vars', problems)
    site_values = _section('vars', {k: v for k, v in variables.items() if k not in SITE_MAPPINGS},
                           dict(SITE_KEYS, **{k: (False, 'mapping') for k in SITE_MAPPINGS}), {}, problems)
    gpu_pool = _section('vars.gpu_pool', _mapping(variables.get('gpu_pool'), 'vars.gpu_pool', problems), GPU_POOL_KEYS,
                        {}, problems)
    backup = {}
    if variables.get('backup') is not None:
        backup = _section('vars.backup', _mapping(variables['backup'], 'vars.backup', problems), BACKUP_KEYS, {}, problems)
    deploy = _section('vars.deploy', _mapping(variables.get('deploy'), 'vars.deploy', problems), DEPLOY_KEYS, {}, problems)
    replicas = _section('vars.replicas', _mapping(variables.get('replicas'), 'vars.replicas', problems), REPLICA_KEYS, {}, problems)
    raw_stores = _mapping(variables.get('stores'), 'vars.stores', problems)
    stores = _section('vars.stores', {k: v for k, v in raw_stores.items() if k not in STORE_PARTS},
                      dict(STORES_KEYS, **{k: (False, 'mapping') for k in STORE_PARTS}), {}, problems)
    for part, keys in STORE_PARTS.items():
        if part in raw_stores:
            values = _section(f'vars.stores.{part}', _mapping(raw_stores[part], f'vars.stores.{part}', problems), keys, {}, problems)
            if values:
                stores[part] = values
    networks, lans = {}, {}
    for name, values in _mapping(variables.get('networks'), 'vars.networks', problems).items():
        name = str(name)
        label = f'vars.networks.{name}'
        if not NAME.fullmatch(name):
            problems.append(f'{label} has an invalid network name. Use a-z, 0-9 and -, starting with a-z.')
            continue
        values = _section(label, _mapping(values, label, problems), NETWORK_KEYS, DEFAULTS['network'], problems)
        if 'cidr' in values:
            networks[name] = Network(name=name, **values)
    for name, values in _mapping(variables.get('lans'), 'vars.lans', problems).items():
        name = str(name)
        label = f'vars.lans.{name}'
        if not NAME.fullmatch(name):
            problems.append(f'{label} has an invalid LAN name. Use a-z, 0-9 and -, starting with a-z.')
            continue
        lans[name] = _section(label, _mapping(values, label, problems), LAN_KEYS, {}, problems).get('cidr', '')
    nodes = {}
    for name, values in _mapping(group.get('hosts'), 'hosts', problems).items():
        name = str(name)
        if not NAME.fullmatch(name):
            problems.append(f'hosts.{name} has an invalid node name. Use a-z, 0-9 and -, starting with a-z.')
            continue
        label = f'hosts.{name}'
        raw = _mapping(values, label, problems)
        values = _section(label, {k: v for k, v in raw.items() if k not in NODE_MAPPINGS},
                          dict(NODE_KEYS, **{k: (False, 'mapping') for k in NODE_MAPPINGS}), DEFAULTS['node'], problems)
        values['networks'] = _members(label, raw.get('networks'), networks, problems)
        values['lan'] = _lan(label, raw.get('lan'), lans, problems)
        values['storage'] = _storage(label, raw.get('storage'), problems)
        if 'node_roles' in values:
            values['roles'] = values.pop('node_roles')
            # The host firewall of a public or calls node with a public address is on unless the site file turns it off.
            values.setdefault('public_firewall', bool(values.get('public_address'))
                              and ('public' in values['roles'] or 'calls' in values['roles']))
            nodes[name] = Node(name=name, **values)
    if problems:
        raise SiteError(_message(problems))
    site = Site(nodes=nodes, networks=networks, lans=lans, gpu_pool=gpu_pool, backup=backup, stores=stores, deploy=deploy, replicas=replicas, **site_values)
    problems = check(site, check_files=check_files)
    if problems:
        raise SiteError(_message(problems))
    return site


def read(path, check_files=False):
    """The Site of the site file at path. Site.path is the absolute path of the file."""
    if not path:
        raise SiteError('no site file is given. Give --site FILE, or set HOOVER4_SITE.')
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as error:
        raise SiteError(f'the site file {path} is unreadable: {error}') from None
    site = parse(text, check_files=check_files)
    site.path = str(path.resolve())
    return site


def _message(problems):
    return f'the site file has {len(problems)} problem{"s" if len(problems) != 1 else ""}:\n    ' + '\n    '.join(problems)


def check(site, check_files=False):
    """Every resource and role problem of a parsed site, as messages."""
    problems = []
    nodes = site.nodes
    if not nodes:
        problems.append('the site has no node in hosts.')
        return problems
    single = site.single
    for role in ('control-plane', 'registry'):
        holders = [n.name for n in site.with_role(role)]
        if len(holders) != 1:
            problems.append(f'the site needs exactly one node with the role {role}. It has {len(holders)}: {", ".join(holders) or "none"}.')
    if site.control_plane not in nodes:
        problems.append(f'vars control_plane = {site.control_plane} is not a node of the site.')
    elif not nodes[site.control_plane].has('control-plane'):
        problems.append(f'vars control_plane = {site.control_plane} does not have the role control-plane.')
    if not site.with_role('public'):
        problems.append('the site needs at least one node with the role public.')
    if not site.with_role('worker'):
        problems.append('the site needs at least one node with the role worker.')
    if not site.with_role('data'):
        problems.append('the site needs at least one node with the role data.')
    locals_ = [n.name for n in nodes.values() if n.local]
    if len(locals_) > 1:
        problems.append(f'only one node can be local. These nodes are: {", ".join(locals_)}.')
    cluster = next(iter(site.networks.values()), None)
    for node in nodes.values():
        label = f'hosts.{node.name}'
        if node.has('gpu') and len(node.roles) > 1:
            problems.append(f'{label} combines gpu with {", ".join(r for r in node.roles if r != "gpu")}. A GPU node runs only the GPU services.')
        if not single:
            if cluster and cluster.name not in node.networks:
                problems.append(f'{label} has no address in the network {cluster.name}. The first network of vars.networks '
                                'holds the node addresses of the cluster, so every node needs one.')
            elif not cluster and not node.lan:
                problems.append(f'{label} has no lan address. A site with more than one node and without vars.networks '
                                'connects its nodes at their LAN addresses.')
            for role in ('public', 'calls'):
                if node.has(role) and not node.public_address:
                    problems.append(f'{label} has the role {role} and no public_address.')
        if len(node.lan) > 1:
            problems.append(f'{label} lan names {len(node.lan)} LANs. A node has at most one LAN address.')
        for name, address in node.lan.items():
            if site.lans.get(name) and ipaddress.ip_address(address) not in ipaddress.ip_network(site.lans[name]):
                problems.append(f'{label} lan.{name} = {address} is outside vars.lans.{name} cidr = {site.lans[name]}.')
        if (node.has('worker') or node.has('data') or node.has('registry')) and not node.storage:
            problems.append(f'{label} has the role {"worker" if node.has("worker") else "data" if node.has("data") else "registry"} '
                            'and no storage. Map a tier to a volume group, for example storage: {hdd: vg-hdd}.')
        shared = sorted({g for g in node.storage.values() if list(node.storage.values()).count(g) > 1})
        for group in shared:
            problems.append(f'{label} storage gives the volume group {group} to more than one tier. Each tier needs its '
                            'own volume group, else the faster class has the speed of the slower disks.')
        if node.public_firewall and not ((node.has('public') or node.has('calls')) and node.public_address):
            problems.append(f'{label} public_firewall belongs to a node with the role public or calls and a public_address.')
        for key, role in SECRET_ROLES.items():
            if getattr(node, key) and not node.has(role):
                problems.append(f'{label} {key} belongs to a node with the role {role}.')
        if node.tls_mode and not node.has('public'):
            problems.append(f'{label} tls_mode belongs to a node with the role public.')
    problems += tls_problems(site)
    problems += network_problems(site)
    pool = site.gpu_pool
    if pool:
        for name in pool.get('nodes', ()):
            if name not in nodes or not nodes[name].has('gpu'):
                problems.append(f'vars.gpu_pool nodes names {name}, which is not a node with the role gpu.')
        if bool(pool.get('nodes')) == bool(pool.get('address')):
            problems.append('vars.gpu_pool needs either nodes (GPU nodes of the site) or address (a shared pool), not both.')
    elif site.with_role('gpu'):
        problems.append('the site has GPU nodes and no vars.gpu_pool.')
    if site.backup:
        node = nodes.get(site.backup.get('node'))
        if node is None:
            problems.append(f'vars.backup node = {site.backup.get("node")} is not a node of the site.')
        elif node.has('gpu'):
            problems.append('vars.backup node is a GPU node. Choose a node that holds application data.')
    problems += store_problems(site)
    if check_files:
        problems += missing_files(site)
    return problems


def parallel_zones(site):
    """The count of zone steps that deploy-k3s up runs at the same time."""
    return site.deploy.get('parallel_zones') or PARALLEL_ZONES


def store_plan(site):
    """The shared Hoover stores of a site with the defaults of STORES_KEYS and STORE_PARTS: {'nodes', 'history_shards',
    'garage', 'cassandra', 'cassandra_data_gib', 'opensearch', 'temporal', 'zones'}. garage, cassandra and opensearch are
    node counts, temporal is the Temporal pod count, and zones is the planned zone count (0 without the key).

    The default nodes are the nodes with the role worker and a storage tier, in the order of the site file.
    """
    s = site.stores
    nodes = tuple(s.get('nodes') or (n.name for n in site.nodes.values() if n.has('worker') and n.storage))
    return {'nodes': nodes, 'history_shards': s.get('history_shards', HISTORY_SHARDS), 'zones': s.get('zones', 0),
            'garage': s.get('garage', {}).get('nodes', max(1, min(len(nodes), 3))),
            'cassandra': s.get('cassandra', {}).get('nodes', 1), 'cassandra_data_gib': s.get('cassandra', {}).get('data_gib', 2),
            'opensearch': s.get('opensearch', {}).get('nodes', 1), 'temporal': s.get('temporal', {}).get('pods', 1)}


# The stores that shard their data with one pod on each node, and their key in the recorded plan of the cluster.
SHARDED_STORES = {'garage': 'garage_nodes', 'cassandra': 'cassandra_nodes', 'opensearch': 'opensearch_nodes'}


def store_problems(site):
    """The problems of vars.stores, as messages."""
    plan = store_plan(site)
    problems = []
    for name in plan['nodes']:
        node = site.nodes.get(name)
        if node is None:
            problems.append(f'vars.stores nodes names {name}, which is not a node of the site.')
        elif node.has('gpu') or not node.storage:
            problems.append(f'vars.stores nodes names {name}, which has no storage tier or is a GPU node.')
    if not plan['nodes']:
        problems.append('vars.stores has no node. Give nodes, or give a node the role worker and a storage tier.')
    else:
        for store in SHARDED_STORES:
            if plan[store] > len(plan['nodes']):
                problems.append(f'vars.stores.{store} nodes = {plan[store]} is more than the {len(plan["nodes"])} store nodes. '
                                'Each pod needs its own node.')
    return problems


def store_change_problems(before, plan):
    """The problems of a store plan against the plan that the cluster recorded at the last apply (before), as messages.

    Stores of an earlier version that keep several copies are refused, Temporal keeps the history shard count of its
    creation, and a store node count cannot become smaller.
    """
    if not before:
        return []
    copies = max(before.get('replicas', 1), before.get('garage_replication_factor', 1))
    if copies > 1:
        return [f'the shared stores of hoover-stores keep {copies} copies of their data, from an earlier version. '
                'This version keeps one copy. Delete every zone, delete the namespace hoover-stores, run deploy-k3s up '
                '--steps stores, and create the zones again. The data of the zones does not move.']
    out = []
    if before.get('temporal_history_shards') not in (None, plan['history_shards']):
        out.append(f'Temporal keeps the history shard count {before["temporal_history_shards"]} of its creation. '
                   f'Set vars.stores history_shards to {before["temporal_history_shards"]}.')
    for store, key in SHARDED_STORES.items():
        found = before.get(key)
        count = len(found) if isinstance(found, dict) else found
        if count and plan[store] < count:
            out.append(f'the shared {store} has {count} nodes, and each node holds a part of its data. '
                       f'Set vars.stores.{store} nodes to {count} or more.')
    return out


def tls_mode(node):
    """The TLS mode of the HTTPS frontend on node: tls_mode of the site file, else internal on the local node and
    cloudflare on another node."""
    return node.tls_mode or ('internal' if node.local else 'cloudflare')


def tls_problems(site):
    """The problems of the TLS settings of the frontend node, the first public node, as messages that name the keys."""
    public = site.with_role('public')
    if not public:
        return []
    node = public[0]
    label = f'hosts.{node.name}'
    mode = tls_mode(node)
    shown = f'tls_mode = {mode}' if node.tls_mode else f'tls_mode (default {mode})'
    problems = []
    if node.local and mode != 'internal':
        problems.append(f'{label} {shown}: the frontend of the local node uses the local CA only. Remove tls_mode.')
        return problems
    for key in TLS_MODES[mode]:
        if not getattr(node, key):
            alternatives = ', '.join(m for m in TLS_MODES if m != mode)
            problems.append(f'{label} {shown} needs {key}. Set {key}, or set tls_mode to one of {alternatives}.')
    for key in TLS_KEYS:
        if getattr(node, key) and key not in TLS_MODES[mode]:
            problems.append(f'{label} {key} is not used with {shown}. Remove it, or change tls_mode.')
    for other in public[1:]:
        for key in ('tls_mode',) + TLS_KEYS:
            if getattr(other, key):
                problems.append(f'hosts.{other.name} {key}: only the first public node, {node.name}, runs the HTTPS '
                                'frontend. Move the key there.')
    return problems


def secret_files(site, node_name):
    """The secret file references that one node reads, as {label: path}."""
    node = site.nodes[node_name]
    return {f'node.{node_name}.{k}': getattr(node, k) for k in SECRET_ROLES if getattr(node, k)}


def missing_files(site):
    """The secret files of the local node that do not exist, as messages."""
    problems = []
    for node in (n for n in site.nodes.values() if n.local):
        for label, path in secret_files(site, node.name).items():
            if not os.path.isfile(path):
                problems.append(f'{label} = {path} is not an existing file on this host.')
    return problems


# ----------------------------------------------------------------------------------------------------------------------
# Writing and projection
# ----------------------------------------------------------------------------------------------------------------------

def _text(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, tuple):
        return ', '.join(':'.join(v) if isinstance(v, tuple) else v for v in value)
    return str(value)


def document(site):
    """The site file document of a Site, as a dict. parse(json.dumps(document(site))) gives an equal Site."""
    variables = {k: getattr(site, k) for k in SITE_KEYS if getattr(site, k)}
    if site.networks:
        variables['networks'] = {n.name: {'interface': n.interface, 'cidr': n.cidr, 'port': n.port, 'managed': n.managed,
                                          **({'hubs': list(n.hubs)} if n.hubs else {})} for n in site.networks.values()}
    if site.lans:
        variables['lans'] = {name: ({'cidr': cidr} if cidr else {}) for name, cidr in site.lans.items()}
    for title, values, keys in (('gpu_pool', site.gpu_pool, GPU_POOL_KEYS), ('backup', site.backup, BACKUP_KEYS),
                                ('stores', site.stores, STORES_KEYS), ('deploy', site.deploy, DEPLOY_KEYS),
                                ('replicas', site.replicas, REPLICA_KEYS)):
        if values:
            variables[title] = {k: _text(values[k]) for k in keys if values.get(k) not in (None, '', ())}
    for part, keys in STORE_PARTS.items():
        if site.stores.get(part):
            variables.setdefault('stores', {})[part] = {k: _text(v) for k, v in site.stores[part].items() if k in keys}
    hosts = {}
    for node in site.nodes.values():
        values = {'node_roles': _text(node.roles)}
        for key in NODE_KEYS:
            if key != 'node_roles' and getattr(node, key) not in ('', ()):
                values[key] = _text(getattr(node, key))
        if node.networks:
            values['networks'] = {name: {k: v for k, v in asdict(m).items() if v != ''}
                                  for name, m in node.networks.items()}
        for key in ('lan', 'storage'):
            if getattr(node, key):
                values[key] = dict(getattr(node, key))
        hosts[node.name] = values
    return {GROUP: {'vars': variables, 'hosts': hosts}}


def dump(site):
    """The site file text of a Site in JSON form, which is also YAML."""
    return json.dumps(document(site), indent=1) + '\n'


def project(site, node_name):
    """The part of the site that one node receives, as a dict.

    Every node gets the site values and the addresses, roles and storage of every node, which its host scripts need
    for the VPN peers and the k3s join. A node gets only its own secret file references. The control plane also gets
    the GPU pool and the backup destination, because it creates the Secrets and runs the operator. No projection holds
    a secret value.
    """
    if node_name not in site.nodes:
        raise SiteError(f'{node_name} is not a node of the site.')
    public = {k: v for k, v in asdict(site).items() if k in SITE_KEYS}
    nodes = {}
    for name, node in site.nodes.items():
        values = {k: v for k, v in asdict(node).items() if k not in SECRET_ROLES}
        if name == node_name:
            values.update({k: getattr(node, k) for k in SECRET_ROLES if getattr(node, k)})
        nodes[name] = values
    out = {'site': public, 'this': node_name, 'nodes': nodes, 'secret_files': secret_files(site, node_name)}
    pool = {k: v for k, v in site.gpu_pool.items() if not k.endswith('_file')}
    if pool:
        out['gpu_pool'] = pool
    if node_name == site.control_plane:
        out['gpu_pool'] = dict(site.gpu_pool)
        out['backup'] = dict(site.backup)
    elif site.backup.get('node') == node_name:
        out['backup'] = dict(site.backup)
    return out


def ssh_host(node):
    """The SSH destination of a node: ssh_host of the site file, else localhost for the local node, else the node name.

    The SSH configuration of the current user gives the address, port, user and key of that name.
    """
    return node.ssh_host or ('localhost' if node.local else node.name)


def node_address(site, node):
    """The address that the other nodes and the pods use for a node: its address in the cluster network (the first
    network of vars.networks), else its LAN address, else the fixed local address of a single-node site."""
    cluster = next(iter(site.networks.values()), None)
    if cluster and cluster.name in node.networks:
        return node.networks[cluster.name].address
    if node.lan:
        return next(iter(node.lan.values()))
    if site.single and node.local:
        return LOCAL_ADDRESS
    raise SiteError(f'hosts.{node.name} has no address in a network and no lan address.')


def node_interface(site, node):
    """The interface of the node address, which flannel uses: hoover4 on the local node of a single-node site, the
    interface of the cluster network, or empty for a LAN address. With an empty value the k3s role of ../ansible/ uses
    the interface that holds the address, and the facts of the node name it (facts/<node>.json addresses)."""
    if site.single and node.local:
        return 'hoover4'
    cluster = next(iter(site.networks.values()), None)
    if cluster and cluster.name in node.networks:
        return node.networks[cluster.name].interface
    return ''


def admin_ranges(site):
    """The address ranges that reach the admin routes of the HTTPS frontend: the cidr of each network and of each LAN
    that states one."""
    return [n.cidr for n in site.networks.values()] + [c for c in site.lans.values() if c]


def legacy_settings(site):
    """The values of the earlier private/settings.json, which the scripts of platform/, zones/ and tools/ read through
    settings.py. Each value comes from the site file."""
    public = site.with_role('public')[0]
    registry = site.with_role('registry')[0]
    # A LAN node can have one address as its VPN and public address. Caddy and coturn get each address once.
    binds = list(dict.fromkeys(a for a in (node_address(site, public), public.public_address) if a))
    out = {
        'suffix': site.domain,
        'registry_node': registry.name,
        'registry_endpoint': f'{node_address(site, registry)}:{REGISTRY_PORT}',
        'ingress_node': public.name,
        'ingress_address': INGRESS_ADDRESS,
        'frontend_bind': binds,
        'turn_listen': binds,
        'frontend_local': public.local,
        **calls_settings(site),
        'hoover_data': {'roots': {n.name: n.data_root for n in site.with_role('data')},
                        'extra': {h.zone: [{'name': n, 'node': node, 'path': path} for n, node, path in h.extra_datasets]
                                  for h in hoovers(site).values() if h.extra_datasets}},
    }
    if admin_ranges(site):
        out['admin_ranges'] = admin_ranges(site)
    if not public.local:
        out['frontend_ssh'] = ssh_host(public)
    out['frontend_tls_mode'] = tls_mode(public)
    if out['frontend_tls_mode'] == 'cloudflare':
        out['frontend_tls'] = f'/etc/letsencrypt/live/{site.domain}'
        out['frontend_tls_certificate'] = f'/etc/letsencrypt/live/{site.domain}/fullchain.pem'
        out['frontend_tls_key'] = f'/etc/letsencrypt/live/{site.domain}/privkey.pem'
        out['frontend_dns_credentials'] = public.tls_dns_credentials_file
    elif out['frontend_tls_mode'] == 'files':
        out['frontend_tls_certificate'] = public.tls_certificate_file
        out['frontend_tls_key'] = public.tls_key_file
    return out


def calls_node(site):
    """The node of the call media services: the first node with the role calls, else the first public node (D9)."""
    calls = site.with_role('calls')
    return calls[0] if calls else site.with_role('public')[0]


def calls_settings(site):
    """The placement and the public media address of the call services (../platform/calls/install-calls.py).

    A media node with a public address advertises it, so a client sends its media straight to the JVB and LiveKit of
    that node. A media node without one, such as the local node of a single-node site, advertises the pod addresses.
    """
    node = calls_node(site)
    turn = list(dict.fromkeys(a for a in (node_address(site, node), node.public_address) if a))
    return {'calls_node': node.name, 'calls_public_address': node.public_address, 'calls_turn_listen': turn}


def local_ca(site):
    """The root certificate of the local CA of the HTTPS frontend, when the frontend uses the TLS mode internal.

    ../platform/frontend/install-local-frontend.sh (local node) or install-frontend.sh (another node) writes it into
    frontend/local-ca.crt of the state folder. The pods that call the zone names over HTTPS trust it.
    """
    public = site.with_role('public')
    if not public or tls_mode(public[0]) != 'internal' or not site.path:
        return ''
    path = site.state_folder() / 'frontend' / 'local-ca.crt'
    return path.read_text() if path.exists() else ''


# ----------------------------------------------------------------------------------------------------------------------
# Networks
# ----------------------------------------------------------------------------------------------------------------------

def members(site, network):
    """The nodes of a network, in the order of the site file."""
    return [n for n in site.nodes.values() if network.name in n.networks]


def shared_lan(a, b):
    """The name of a LAN that holds nodes a and b, or empty."""
    return next((name for name in a.lan if name in b.lan), '')


def direct_peers(site, network, node):
    """The nodes of network that node peers with directly.

    Without hubs, every node peers with every other node. A hub peers with every node. Another node peers with each
    hub, and with each node of the network that is on one of its LANs.
    """
    if network.name not in node.networks:
        return []
    others = [n for n in members(site, network) if n.name != node.name]
    if not network.hubs or node.name in network.hubs:
        return others
    return [n for n in others if n.name in network.hubs or shared_lan(node, n)]


def endpoint(network, node, peer):
    """The WireGuard endpoint of peer as node sees it: the LAN address when they share a LAN, else the public address
    of peer, else empty. A peer without an endpoint waits for the other node to start the handshake."""
    port = peer.networks[network.name].port
    lan = shared_lan(node, peer)
    address = peer.lan[lan] if lan else peer.public_address
    if not address:
        return ''
    return f'[{address}]:{port}' if ':' in address else f'{address}:{port}'


def routed(site, network, node):
    """{hub name: [addresses]}: the addresses of the network that node reaches through a hub.

    A node that is no hub reaches each node of the network without a direct peer through the first hub. Both nodes
    must be managed, so both add the route. A node that the installer does not manage keeps the routes of its VPN.
    """
    if not network.hubs or node.name in network.hubs or not node.networks[network.name].managed:
        return {}
    hub = network.hubs[0]
    direct = {n.name for n in direct_peers(site, network, node)}
    out = [f'{n.networks[network.name].address}/32' for n in members(site, network)
           if n.name not in direct and n.name != node.name and n.networks[network.name].managed]
    return {hub: out} if out else {}


def wireguard(site, node):
    """The WireGuard interfaces that the installer manages on node, as a list for the role hoover4_wireguard.

    A peer without a public key in the site file is left out. Its node gets the key when the role writes its interface,
    and the next run adds the peer.
    """
    out = []
    for network in site.networks.values():
        member = node.networks.get(network.name)
        if not member or not member.managed:
            continue
        routes = routed(site, network, node)
        peers = []
        for peer in direct_peers(site, network, node):
            other = peer.networks[network.name]
            if not other.public_key:
                continue
            peers.append({'name': peer.name, 'key': other.public_key, 'endpoint': endpoint(network, node, peer),
                          'allowed_ips': [f'{other.address}/32'] + routes.get(peer.name, [])})
        prefix = ipaddress.ip_network(network.cidr).prefixlen
        out.append({'network': network.name, 'interface': member.interface, 'port': member.port,
                    'address': f'{member.address}/{prefix}', 'public_key': member.public_key, 'peers': peers})
    return out


def peer_table(site):
    """Each direct peer of each network, as rows for the check: who adds it, its endpoint and its addresses.

    by is installer for a managed node, and hand for a node that keeps its own interface. The person adds those peers.
    """
    rows = []
    for network in site.networks.values():
        for node in members(site, network):
            member = node.networks[network.name]
            routes = routed(site, network, node)
            for peer in direct_peers(site, network, node):
                rows.append({'network': network.name, 'node': node.name, 'interface': member.interface,
                             'peer': peer.name, 'endpoint': endpoint(network, node, peer),
                             'allowed_ips': [f'{peer.networks[network.name].address}/32'] + routes.get(peer.name, []),
                             'by': 'installer' if member.managed else 'hand',
                             'key': 'present' if peer.networks[network.name].public_key else 'missing'})
    return rows


def network_problems(site):
    """The problems of the networks and LANs of a site, as messages."""
    problems = []
    for network in site.networks.values():
        label = f'vars.networks.{network.name}'
        cidr = ipaddress.ip_network(network.cidr)
        nodes = members(site, network)
        names = [n.name for n in nodes]
        for hub in network.hubs:
            if hub not in names:
                problems.append(f'{label} hubs names {hub}, which has no address in this network.')
        seen = {}
        for node in nodes:
            member = node.networks[network.name]
            where = f'hosts.{node.name} networks.{network.name}'
            if ipaddress.ip_address(member.address) not in cidr:
                problems.append(f'{where} address = {member.address} is outside {label} cidr = {network.cidr}.')
            if member.address in seen:
                problems.append(f'hosts.{node.name} and hosts.{seen[member.address]} have the same address in {network.name}.')
            seen[member.address] = node.name
            for peer in direct_peers(site, network, node):
                other = peer.networks[network.name]
                if member.managed and not other.managed and not other.public_key:
                    problems.append(f'hosts.{peer.name} networks.{network.name} has no public_key. The installer does not '
                                    f'write its interface, and {node.name} needs the key for its peer.')
                if (member.managed and other.managed and node.name < peer.name and not endpoint(network, node, peer)
                        and not endpoint(network, peer, node)):
                    problems.append(f'hosts.{node.name} and hosts.{peer.name} peer in {network.name}, and neither can '
                                    'start the handshake: give one of them a public_address, or put both on one LAN.')
    for node in site.nodes.values():
        interfaces = [m.interface for m in node.networks.values()]
        for interface in sorted({i for i in interfaces if interfaces.count(i) > 1}):
            problems.append(f'hosts.{node.name} uses the interface {interface} in more than one network.')
    return problems


def switches(node):
    """The host changes of a node that the site file turns on or off, for the summary of the check."""
    return {'stop_docker': node.stop_docker, 'k3s_volume_group': node.k3s_volume_group or None,
            'public_firewall': node.public_firewall,
            'wireguard': {name: 'managed' if m.managed else 'kept' for name, m in node.networks.items()}}


# ----------------------------------------------------------------------------------------------------------------------
# Host facts
# ----------------------------------------------------------------------------------------------------------------------

ARCHITECTURES = {'x86_64': 'amd64', 'aarch64': 'arm64'}


def node_facts(site, name):
    """The facts of a node that the facts play wrote into facts/<node>.json of the state folder, or an empty dict."""
    if not site.path:
        return {}
    path = site.state_folder() / 'facts' / f'{name}.json'
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def architecture(site, name, facts=None):
    """The Kubernetes architecture of a node (amd64 or arm64) from its facts. A node without facts is a problem."""
    facts = node_facts(site, name) if facts is None else facts
    machine = facts.get('architecture', '')
    if machine not in ARCHITECTURES:
        raise SiteError(f'the facts of {name} name no supported architecture ({machine or "no facts"}). Run '
                        f'deploy-k3s check --target {name}. Its facts play writes facts/{name}.json of the state folder.')
    return ARCHITECTURES[machine]


def storage_reserve(node, facts):
    """{tier: spare GiB or None}: the TopoLVM spare-gb of each tier of node, STORAGE_RESERVE of its volume group.

    The k3s data volumes in the k3s_volume_group do not count, because they are no part of a tier. None means that the
    facts name no such volume group.
    """
    import math
    groups = facts.get('volume_groups') or {}
    out = {}
    for tier, group in node.storage.items():
        found = groups.get(group)
        if found is None:
            out[tier] = None
            continue
        size = found['size_bytes'] - (found.get('k3s_volumes_bytes', 0) if group == node.k3s_volume_group else 0)
        out[tier] = math.ceil(max(size, 0) * STORAGE_RESERVE / 2 ** 30)
    return out


def legacy_hosts(site, facts=None):
    """The site in the format of hosts.json, which ../cluster/setup.sh and topolvm_values.py read through settings.py
    hosts, with the host facts of each node. facts is {node: facts}, else the facts files of the state folder."""
    hosts = {}
    for node in site.nodes.values():
        known = (facts or {}).get(node.name) if facts is not None else node_facts(site, node.name)
        known = known or {}
        reserve = storage_reserve(node, known)
        gpus = known.get('gpus') or []
        hosts[node.name] = {
            'node_ip': node_address(site, node), 'reserved': node.reserved, 'local': node.local, 'single': site.single,
            'gpu': node.has('gpu'), 'tiers': list(node.tiers), 'facts': bool(known),
            'storage': {t: {'volume_group': node.storage[t], 'spare_gb': reserve[t]} for t in node.tiers},
            'avx2': bool(known.get('avx2')), 'gpu_count': len(gpus),
            'gpu_memory_mib': min((g.get('memory_mib', 0) for g in gpus), default=0),
        }
    return {'server': site.control_plane, 'suffix': site.domain, 'hosts': hosts,
            'backup': {'node': site.backup.get('node', ''), 'path': site.backup.get('path', '')} if site.backup else {}}


# ----------------------------------------------------------------------------------------------------------------------
# The variables of the host plays
# ----------------------------------------------------------------------------------------------------------------------

def _memory_gib(text):
    """GiB of a Kubernetes quantity such as 69Gi or 4096Mi."""
    for suffix, factor in (('Gi', 1), ('Mi', 1 / 1024), ('G', 1), ('M', 1 / 1024)):
        if text.endswith(suffix):
            return float(text[:-len(suffix)]) * factor
    return float(text) / 2 ** 30


def _cpus(text):
    """CPUs of a Kubernetes quantity such as 2 or 700m."""
    return float(text[:-1]) / 1000 if text.endswith('m') else float(text)


# The step of the speed factor of a node. Each node is measured once at rest, so the factor stays the same until an
# operator measures the node again (deploy-k3s measure-speed).
SPEED_STEP = 0.05
# The CPU table of the workloads. runtimeOverhead.node holds the measured base CPU of k3s on a node.
CPU_TABLE = HERE / 'zones' / 'cpu-requests.json'
# The memory table of the workloads. node holds the measured memory of k3s and the system beside the pods of a node.
MEMORY_TABLE = HERE / 'zones' / 'memory-requests.json'


def node_speed(folder, name):
    """The stored speed of a node: speed/<node>.json of the state folder folder, or an empty dict.

    The role hoover4_speed writes {measured, threads, load, cpu_speed, disks}. A value that adopt_facts_speed() took
    from the facts of an earlier version has source facts.
    """
    try:
        return json.loads((Path(folder) / 'speed' / f'{name}.json').read_text())
    except (OSError, ValueError):
        return {}


def adopt_facts_speed(folder):
    """Keep the cpu_speed of the facts of an earlier version as the stored speed of a node without one.

    An earlier version measured cpu_speed in the facts play at each run, also under load. This version measures a
    node only at rest, so a running site keeps its last facts value until an operator measures the node. Return the
    adopted nodes.
    """
    folder = Path(folder)
    adopted = []
    for path in sorted((folder / 'facts').glob('*.json')):
        try:
            facts = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        target = folder / 'speed' / path.name
        if facts.get('cpu_speed') and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({'cpu_speed': facts['cpu_speed'], 'source': 'facts'}, indent=1) + '\n')
            target.chmod(0o600)
            adopted.append(path.stem)
    return adopted


def speed_factors(site, folder=None):
    """{node: factor}: the stored cpu_speed of each node divided by the highest cpu_speed of the site.

    One thread of a node with the factor 0.5 does half the work of one thread of the fastest node. A node without the
    value has the factor 1. folder is the state folder, else the state folder of the site file.
    """
    folder = folder or (site.state_folder() if site.path else None)
    speeds = {n: node_speed(folder, n).get('cpu_speed') if folder else None for n in site.nodes}
    speeds = {n: v for n, v in speeds.items() if v}
    fastest = max(speeds.values(), default=0)
    return {n: max(SPEED_STEP, round(speeds[n] / fastest / SPEED_STEP) * SPEED_STEP) if n in speeds else 1.0
            for n in site.nodes}


def speed_report(site, folder=None):
    """{node: {cpu_speed, factor, threads, measured, disks, note}} for deploy-k3s check. note says how to measure a
    node without a value measured at rest."""
    folder = folder or site.state_folder()
    factors = speed_factors(site, folder)
    out = {}
    for name in site.nodes:
        stored = node_speed(folder, name)
        entry = {'cpu_speed': stored.get('cpu_speed'), 'factor': factors[name], 'threads': stored.get('threads'),
                 'measured': stored.get('measured'), 'disks': stored.get('disks', {})}
        how = (f'Stop k3s and every container on {name}, run deploy-k3s measure-speed --target {name}, and start k3s '
               'again. Then run deploy-k3s up.')
        if not stored:
            entry['note'] = f'{name} has no speed value and counts as a node of the fastest speed. {how}'
        elif stored.get('source') == 'facts':
            entry['note'] = f'{name} keeps the speed of an earlier facts probe, which ran under load. {how}'
        out[name] = entry
    return out


def base_cpu(table=None):
    """{'agent': millicores, 'server': millicores}: the measured CPU of k3s on a node without pods, in threads of the
    fastest node (runtimeOverhead.node of the CPU table). server holds the kubelet and the control plane."""
    node = (table or json.loads(CPU_TABLE.read_text()))['runtimeOverhead']['node']
    return {k: _cpus(node[k]) * 1000 for k in ('agent', 'server')}


def base_memory(table=None):
    """{'agent': MiB, 'server': MiB}: the memory reserve of a node for k3s, the system and the kernel (node of the
    memory table), or {} without a measurement. server holds the control plane."""
    try:
        node = (table or json.loads(MEMORY_TABLE.read_text())).get('node') or {}
    except (OSError, ValueError):
        return {}
    return {k: int(_memory_gib(node[k]) * 1024) for k in ('agent', 'server') if k in node}


def node_threads(folder, name):
    """The threads of a node: the stored value of its speed measurement, else the facts value cpus. The facts value
    counts two threads for each core, also for the cores without Hyper-Threading of a hybrid CPU."""
    stored = node_speed(folder, name).get('threads')
    if stored:
        return stored
    try:
        return json.loads((Path(folder) / 'facts' / f'{name}.json').read_text()).get('cpus', 0)
    except (OSError, ValueError):
        return 0


def kubelet_reserved(node, factor, threads, server=False, base=None, memory=None):
    """The system-reserved value of the kubelet of a node: the memory reserve and the CPU reserve.

    The memory reserve is the memory of the site value reserved, else memory['server' or 'agent'] (base_memory()), the
    measured peak of k3s, the system and the kernel beside the pods of a node under load. Without the reserve the
    kubelet counts that memory as allocatable, and pods that use their requests bring the node to memory pressure.

    The allocatable CPU of the node counts threads of the fastest node: factor x threads - base, where base is the
    measured CPU of k3s without pods (base_cpu(), the server value on the control plane). k3s needs base / factor
    threads of a slower node. So the reserve in threads of the node is threads x (1 - factor) + base, rounded up to
    100m. A site value reserved with cpu= replaces base, in threads of the node: threads - factor x (threads - cpu).
    """
    parts = dict(part.split('=', 1) for part in node.reserved.split(',') if '=' in part)
    if 'cpu' in parts:
        own = _cpus(parts['cpu'])
        reserve = threads - factor * (threads - own) if factor < 1 and threads else own
    else:
        reserve = (threads * (1 - factor) if threads else 0) + (base or base_cpu())['server' if server else 'agent'] / 1000
    role = 'server' if server else 'agent'
    if 'memory' not in parts and memory and role in memory:
        parts['memory'] = f'{memory[role]}Mi'
    parts['cpu'] = f'{int(math.ceil(reserve * 10 - 1e-9)) * 100}m'
    return ','.join(f'{k}={v}' for k, v in parts.items())


def ansible_variables(site, private):
    """The extra variables of the host plays, as a dict. private is the state folder.

    The site file is the inventory of the plays. These variables add what the driver derives from it: the paths of the
    state folder, the domain, and hoover4_nodes with the values of each node. ../ansible/playbooks/group_vars/
    hoover4.yml gives each value of hoover4_nodes to its node as a hoover4_* variable, which the roles of
    ../ansible/roles/hoover4_* read. ansible_host of a node is ssh_host().
    """
    private = Path(private)
    registry = site.with_role('registry')
    media = calls_node(site) if site.with_role('public') else None
    nodes = {}
    factors = speed_factors(site, private)
    base, memory = base_cpu(), base_memory()
    for node in site.nodes.values():
        reserved = dict(part.split('=', 1) for part in node.reserved.split(',') if '=' in part)
        single_local = site.single and node.local
        nodes[node.name] = {
            'ssh_host': ssh_host(node),
            'node_address': node_address(site, node),
            'flannel_iface': node_interface(site, node),
            'server': node.name == site.control_plane,
            'server_address': node_address(site, site.nodes[site.control_plane]),
            'gpu': node.has('gpu'),
            'single_local': single_local,
            'reserved': node.reserved,
            # The kubelet value system-reserved, with the CPU reserve of the speed factor and of k3s (kubelet_reserved()).
            'kubelet_reserved': kubelet_reserved(node, factors[node.name], node_threads(private, node.name),
                                                 node.name == site.control_plane, base, memory),
            # The host step measures the speed of a node without a stored value (role hoover4_speed).
            'speed_stored': bool(node_speed(private, node.name)),
            'reserved_memory_gib': _memory_gib(reserved.get('memory', '8Gi')),
            'reserved_cpus': _cpus(reserved.get('cpu', '2')),
            'storage': dict(node.storage),
            'k3s_volume_group': node.k3s_volume_group,
            'stop_docker': node.stop_docker,
            'public_firewall': node.public_firewall,
            'public_address': node.public_address,
            # The media node with a public address gets the chain coturn_peers (../platform/calls/turn_peers.py).
            'coturn_peers': bool(media and media.name == node.name and node.public_address),
            'wireguard_ports': sorted({m.port for m in node.networks.values()}),
            'backup_path': site.backup.get('path', '') if site.backup.get('node') == node.name else '',
            'registry_endpoint': f'{node_address(site, registry[0])}:{REGISTRY_PORT}' if registry else '',
            'convert_sqlite': node.name == site.control_plane,
            'wireguard': wireguard(site, node),
        }
    # The delegated tasks write into the state folder from the operator container, whose home folder is read-only.
    return {'hoover4_state_dir': str(private), 'hoover4_tokens_dir': str(private / 'staging' / 'tokens'),
            'hoover4_kubeconfig': str(private / 'kubeconfig'), 'hoover4_facts_dir': str(private / 'facts'),
            'hoover4_speed_dir': str(private / 'speed'),
            'hoover4_domain': site.domain, 'hoover4_nodes': nodes}


def main(argv):
    if len(argv) >= 2 and argv[0] == 'check':
        site = read(argv[1], check_files=True)
        problems = zones_problems(site)
        if problems:
            raise SiteError(f'the zone state {site.zone_state()} has {len(problems)} problem'
                            f'{"s" if len(problems) != 1 else ""}:\n    ' + '\n    '.join(problems))
        print(json.dumps({'site': site.id, 'site_file': site.path, 'state': str(site.state_folder()),
                          'nodes': {n.name: list(n.roles) for n in site.nodes.values()},
                          'switches': {n.name: switches(n) for n in site.nodes.values()},
                          'peers': peer_table(site), 'zones': sorted(hoovers(site))}, indent=1))
    elif len(argv) == 3 and argv[0] == 'project':
        print(json.dumps(project(read(argv[1]), argv[2]), indent=1, default=list))
    elif len(argv) == 2 and argv[0] == 'ansible':
        site = read(argv[1])
        print(json.dumps(ansible_variables(site, site.state_folder()), indent=1))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except SiteError as error:
        raise SystemExit(str(error))
