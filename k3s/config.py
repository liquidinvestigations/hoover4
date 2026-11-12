#!/usr/bin/env python3
"""Read and check the site file of a cluster installation, hoover4-site.ini, and the Compose ini of an earlier install.

The site file names the resources of the installation and the roles of its nodes. It holds no port, no tuning, no
feature switch, no backup schedule and no secret value. Tunings, switches and schedules are operator settings
(platform/operator/settings.py). A secret is a reference to a private file on the node that reads it.

Sections:
  [site]             name, suffix, control_plane, operator_user, vpn_cidr, state_path
  [node.<name>]      one node: roles, local, ssh_address, architecture, the VPN and public addresses, storage and
                     the secret files of the node
  [gpu_pool]         optional. The GPU services: the GPU nodes of the site, or the address of a shared pool
  [backup]           optional. One node and one host folder that receive the backups
  [hoover.<name>]    one Hoover installation: its zone, home node, store layout, Temporal backend, history source,
                     storage identity, an optional source_ini of an earlier Compose install, and optional
                     extra_datasets: read-only dataset folders of data nodes, as name:node:/path

The node roles are control-plane, worker, public, registry, data, calls and gpu. The value `single` gives one host
every role except calls and gpu. A site with one node needs no VPN address and no public address.
The storage identity of a Hoover installation is independent of its zone name. A migrated installation keeps the
database, table and bucket names of its source install.

parse() refuses an unknown section, an unknown key, a missing resource and an incompatible role combination, and names
every problem in one message. It changes nothing on any host. read_source_ini() reads the hoover4.ini of a Compose
install. It accepts the settings that deploy.py removed, reports them, and checks every path before any copy.

Usage: config.py check <site.ini>             checks the file and prints its summary as JSON
       config.py project <site.ini> <node>    prints the part of the site that one node receives
       config.py source <hoover4.ini>         checks the Compose ini of an earlier install
"""
import configparser
import importlib.util
import ipaddress
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PRIVATE = HERE / 'private'
DEFAULT_SITE = PRIVATE / 'hoover4-site.ini'
STORAGE_IDENTITY = REPO / 'main_services/processing/tasks/storage_identity.json'

# The fixed address of the local node of a single-node site. The host script puts it on the dummy link hoover4, so
# k3s, the registry, the HTTPS frontend and the local DNS server keep one address when the LAN address changes.
LOCAL_ADDRESS = '10.254.54.1'
# The fixed Service address of the cluster ingress, inside the default k3s Service range 10.43.0.0/16.
INGRESS_ADDRESS = '10.43.0.80'
REGISTRY_PORT = 5000

ROLES = ('control-plane', 'worker', 'public', 'registry', 'data', 'calls', 'gpu')
SINGLE = ('control-plane', 'worker', 'public', 'registry', 'data')
TIERS = ('nvme', 'ssd', 'hdd')
ARCHITECTURES = ('amd64', 'arm64')
NAME = re.compile(r'[a-z][a-z0-9-]{0,31}')
ZONE = re.compile(r'zone-[a-z0-9]{1,12}')

# Each key of a section: (required, kind). Kinds: text, name, bool, address, cidr, path, list, roles, tiers, choice
# values, secret (the absolute path of a private file).
SITE_KEYS = {
    'name': (True, 'name'), 'suffix': (True, 'domain'), 'control_plane': (True, 'name'),
    'operator_user': (False, 'text'), 'vpn_cidr': (False, 'cidr'), 'state_path': (False, 'path'),
}
NODE_KEYS = {
    'roles': (True, 'roles'), 'local': (False, 'bool'), 'ssh_address': (False, 'text'),
    'architecture': (False, ('choice', ARCHITECTURES)), 'vpn_address': (False, 'address'),
    'wireguard_public_key': (False, 'text'), 'wireguard_port': (False, 'port'), 'vpn_interface': (False, 'interface'),
    'lan_address': (False, 'address'),
    'onprem': (False, 'bool'), 'public_address': (False, 'address'), 'storage_tiers': (False, 'tiers'),
    'lvm_volume_group': (False, 'name_any'), 'lvm_physical_volumes': (False, 'devices'), 'reserved': (False, 'reserved'),
    'avx2': (False, 'bool'), 'data_root': (False, 'path'),
    'tls_dns_credentials_file': (False, 'secret'), 'gpu_api_key_file': (False, 'secret'),
}
GPU_POOL_KEYS = {
    'nodes': (False, 'names'), 'address': (False, 'address'), 'api_key_file': (False, 'secret'),
}
BACKUP_KEYS = {'node': (True, 'name'), 'path': (True, 'path')}
HOOVER_KEYS = {
    'zone': (True, 'zone'), 'home_node': (True, 'name'), 'stores': (True, ('choice', ('local', 'zone'))),
    'temporal_backend': (True, ('choice', ('cassandra', 'postgresql'))),
    'history_source': (False, ('choice', ('compose', 'k3s-branch'))),
    'clickhouse_database_prefix': (True, 'identity'), 'manticore_table_prefix': (True, 'identity'),
    'system_bucket': (True, 'identity'), 'collection_bucket_prefix': (True, 'identity'),
    'source_ini': (False, 'path'), 'chat_control_dir': (False, 'path'), 'extra_datasets': (False, 'datasets'),
}
# The defaults of the optional keys. A key without a default here is empty.
DEFAULTS = {
    'node': {'local': 'false', 'architecture': 'amd64', 'wireguard_port': '51820', 'vpn_interface': 'wg0', 'onprem': 'false',
             'avx2': 'true', 'data_root': '/srv/hoover-data'},
    'hoover': {'history_source': 'compose'},
}
# The secret files that each role reads. The control plane reads the files of the GPU pool, because it creates the
# Secrets of the cluster.
SECRET_ROLES = {'tls_dns_credentials_file': 'public', 'gpu_api_key_file': 'gpu'}
# The storage identity keys of a Hoover section and the names in storage_identity.json.
IDENTITY = {'clickhouse_database_prefix': 'clickhouse_database_prefix', 'manticore_table_prefix': 'manticore_table_prefix',
            'system_bucket': 'system_bucket', 'collection_bucket_prefix': 'collection_bucket_prefix'}


class SiteError(ValueError):
    """The site file or a source ini has problems. The message names each problem."""


@dataclass
class Node:
    name: str
    roles: tuple
    local: bool = False
    ssh_address: str = ''
    architecture: str = 'amd64'
    vpn_address: str = ''
    wireguard_public_key: str = ''
    wireguard_port: int = 51820
    vpn_interface: str = 'wg0'
    lan_address: str = ''
    onprem: bool = False
    public_address: str = ''
    storage_tiers: tuple = ()
    lvm_volume_group: str = ''
    lvm_physical_volumes: tuple = ()
    reserved: str = ''
    avx2: bool = True
    data_root: str = '/srv/hoover-data'
    tls_dns_credentials_file: str = ''
    gpu_api_key_file: str = ''

    def has(self, role):
        return role in self.roles


@dataclass
class Hoover:
    name: str
    zone: str
    home_node: str
    stores: str
    temporal_backend: str
    clickhouse_database_prefix: str
    manticore_table_prefix: str
    system_bucket: str
    collection_bucket_prefix: str
    history_source: str = 'compose'
    source_ini: str = ''
    chat_control_dir: str = ''
    extra_datasets: tuple = ()

    @property
    def namespace(self):
        return 'hoover-' + self.zone

    def identity(self):
        """The storage identity as the environment variables of storage_identity.json."""
        names = json.loads(STORAGE_IDENTITY.read_text())['settings']
        return {names[IDENTITY[k]]['variable']: getattr(self, k) for k in IDENTITY}


@dataclass
class Site:
    name: str
    suffix: str
    control_plane: str
    nodes: dict
    hoovers: dict = field(default_factory=dict)
    operator_user: str = ''
    vpn_cidr: str = ''
    state_path: str = ''
    gpu_pool: dict = field(default_factory=dict)
    backup: dict = field(default_factory=dict)

    @property
    def single(self):
        return len(self.nodes) == 1

    def with_role(self, role):
        return [n for n in self.nodes.values() if n.has(role)]

    def operator_state(self):
        """The folder of the operator state on the control-plane host."""
        return Path(self.state_path) if self.state_path else PRIVATE / 'operator'


# ----------------------------------------------------------------------------------------------------------------------
# Values
# ----------------------------------------------------------------------------------------------------------------------

def _identity_patterns():
    settings = json.loads(STORAGE_IDENTITY.read_text())['settings']
    return {k: re.compile(settings[v]['pattern']) for k, v in IDENTITY.items()}


def _value(label, kind, raw, problems):
    """The typed value of one raw text, or None after a problem."""
    raw = raw.strip()
    if isinstance(kind, tuple) and kind[0] == 'choice':
        if raw not in kind[1]:
            problems.append(f'{label} = {raw} is not one of {", ".join(kind[1])}.')
            return None
        return raw
    if kind == 'interface':
        # A Linux interface name has at most 15 characters.
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', raw):
            problems.append(f'{label} = {raw} is not a network interface name.')
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
    if kind == 'devices':
        items = tuple(p.strip() for p in raw.split(',') if p.strip())
        for item in items:
            if not item.startswith('/dev/'):
                problems.append(f'{label} has {item}, which is not a device path below /dev.')
                return None
        return items
    if kind in ('roles', 'names', 'tiers'):
        items = tuple(p.strip() for p in raw.split(',') if p.strip())
        if kind == 'roles':
            if items == ('single',):
                return SINGLE
            unknown = [i for i in items if i not in ROLES]
            if unknown or not items:
                problems.append(f'{label} = {raw} must be single or a list of {", ".join(ROLES)}.')
                return None
            return tuple(r for r in ROLES if r in items)
        if kind == 'tiers':
            unknown = [i for i in items if i not in TIERS]
            if unknown:
                problems.append(f'{label} = {raw} must be a list of {", ".join(TIERS)}.')
                return None
        return items
    if kind == 'reserved':
        if raw and not re.fullmatch(r'(memory|cpu)=[0-9]+[A-Za-z]*(,(memory|cpu)=[0-9]+[A-Za-z]*)*', raw):
            problems.append(f'{label} = {raw} must look like memory=6Gi,cpu=2.')
            return None
        return raw
    if kind == 'identity':
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


def _section(parser, section, keys, defaults, problems):
    """The typed values of one section. Unknown keys and missing required keys are problems."""
    out = {}
    present = set(parser.options(section))
    for key in sorted(present - set(keys)):
        problems.append(f'[{section}] {key} is not a known key. The keys are {", ".join(keys)}.')
    for key, (required, kind) in keys.items():
        label = f'[{section}] {key}'
        if key in present:
            raw = parser.get(section, key)
            if re.search(r'(?:^|\s)[;#]', raw):
                problems.append(f'{label} has a comment after its value. Move the comment to its own line.')
                continue
            if raw.strip() == '' and kind == 'identity':
                out[key] = ''
                continue
            if raw.strip() == '' and not required:
                continue
            if raw.strip() == '':
                problems.append(f'{label} is empty.')
                continue
            value = _value(label, kind, raw, problems)
            if value is not None:
                out[key] = value
        elif required:
            problems.append(f'[{section}] has no {key}.')
        elif key in defaults:
            out[key] = _value(label, kind, defaults[key], problems)
    return out


# ----------------------------------------------------------------------------------------------------------------------
# The site file
# ----------------------------------------------------------------------------------------------------------------------

def _parser(text):
    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None, default_section='\n',
                                       strict=True)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as error:
        raise SiteError(f'the site file cannot be parsed: {error}') from None
    return parser


def parse(text, check_files=False):
    """The Site of a site file text. check_files also checks that the secret files of the local node exist."""
    parser = _parser(text)
    problems = []
    site_values, nodes, hoovers, gpu_pool, backup = None, {}, {}, {}, {}
    for section in parser.sections():
        kind, _, name = section.partition('.')
        if section == 'site':
            site_values = _section(parser, section, SITE_KEYS, {}, problems)
        elif kind == 'node' and name:
            if not NAME.fullmatch(name):
                problems.append(f'[{section}] has an invalid node name. Use a-z, 0-9 and -, starting with a-z.')
                continue
            values = _section(parser, section, NODE_KEYS, DEFAULTS['node'], problems)
            if 'roles' in values:
                nodes[name] = Node(name=name, **values)
        elif section == 'gpu_pool':
            gpu_pool = _section(parser, section, GPU_POOL_KEYS, {}, problems)
        elif section == 'backup':
            backup = _section(parser, section, BACKUP_KEYS, {}, problems)
        elif kind == 'hoover' and name:
            if not NAME.fullmatch(name):
                problems.append(f'[{section}] has an invalid installation name.')
                continue
            values = _section(parser, section, HOOVER_KEYS, DEFAULTS['hoover'], problems)
            if all(k in values for k, (required, _) in HOOVER_KEYS.items() if required):
                hoovers[name] = Hoover(name=name, **values)
        else:
            problems.append(f'[{section}] is not a known section. The sections are [site], [node.<name>], '
                            '[gpu_pool], [backup] and [hoover.<name>].')
    if site_values is None:
        problems.append('the site file has no [site] section.')
    if problems:
        raise SiteError(_message(problems))
    site = Site(nodes=nodes, hoovers=hoovers, gpu_pool=gpu_pool, backup=backup, **site_values)
    problems = check(site, check_files=check_files)
    if problems:
        raise SiteError(_message(problems))
    return site


def read(path=DEFAULT_SITE, check_files=False):
    path = Path(path)
    try:
        text = path.read_text()
    except OSError as error:
        raise SiteError(f'the site file {path} is unreadable: {error}') from None
    return parse(text, check_files=check_files)


def _message(problems):
    return f'the site file has {len(problems)} problem{"s" if len(problems) != 1 else ""}:\n    ' + '\n    '.join(problems)


def check(site, check_files=False):
    """Every resource and role problem of a parsed site, as messages."""
    problems = []
    nodes = site.nodes
    if not nodes:
        problems.append('the site has no [node.<name>] section.')
        return problems
    single = site.single
    for role in ('control-plane', 'registry'):
        holders = [n.name for n in site.with_role(role)]
        if len(holders) != 1:
            problems.append(f'the site needs exactly one node with the role {role}. It has {len(holders)}: {", ".join(holders) or "none"}.')
    if site.control_plane not in nodes:
        problems.append(f'[site] control_plane = {site.control_plane} is not a node of the site.')
    elif not nodes[site.control_plane].has('control-plane'):
        problems.append(f'[site] control_plane = {site.control_plane} does not have the role control-plane.')
    if not site.with_role('public'):
        problems.append('the site needs at least one node with the role public.')
    if not site.with_role('worker'):
        problems.append('the site needs at least one node with the role worker.')
    if not site.with_role('data'):
        problems.append('the site needs at least one node with the role data.')
    locals_ = [n.name for n in nodes.values() if n.local]
    if len(locals_) > 1:
        problems.append(f'only one node can be local. These nodes are: {", ".join(locals_)}.')
    network = ipaddress.ip_network(site.vpn_cidr) if site.vpn_cidr else None
    if not single and not network:
        problems.append('[site] vpn_cidr is required for a site with more than one node.')
    for node in nodes.values():
        label = f'[node.{node.name}]'
        if node.has('gpu') and len(node.roles) > 1:
            problems.append(f'{label} combines gpu with {", ".join(r for r in node.roles if r != "gpu")}. A GPU node runs only the GPU services.')
        if not node.local and not node.ssh_address:
            problems.append(f'{label} has no ssh_address. Only the local node needs none.')
        if not single:
            if not node.vpn_address:
                problems.append(f'{label} has no vpn_address, which a site with more than one node needs.')
            elif network and ipaddress.ip_address(node.vpn_address) not in network:
                problems.append(f'{label} vpn_address = {node.vpn_address} is outside [site] vpn_cidr = {site.vpn_cidr}.')
            for role in ('public', 'calls'):
                if node.has(role) and not node.public_address:
                    problems.append(f'{label} has the role {role} and no public_address.')
        if node.storage_tiers and not node.lvm_volume_group:
            problems.append(f'{label} has storage_tiers and no lvm_volume_group.')
        if (node.has('worker') or node.has('data') or node.has('registry')) and not node.storage_tiers:
            problems.append(f'{label} has the role {"worker" if node.has("worker") else "data" if node.has("data") else "registry"} and no storage_tiers.')
        for key, role in SECRET_ROLES.items():
            if getattr(node, key) and not node.has(role):
                problems.append(f'{label} {key} belongs to a node with the role {role}.')
        if node.has('gpu') and not node.gpu_api_key_file:
            problems.append(f'{label} has the role gpu and no gpu_api_key_file.')
    addresses = {}
    for node in nodes.values():
        for key in ('vpn_address', 'public_address'):
            value = getattr(node, key)
            if value and key == 'vpn_address':
                if value in addresses:
                    problems.append(f'[node.{node.name}] and [node.{addresses[value]}] have the same vpn_address.')
                addresses[value] = node.name
    pool = site.gpu_pool
    if pool:
        for name in pool.get('nodes', ()):
            if name not in nodes or not nodes[name].has('gpu'):
                problems.append(f'[gpu_pool] nodes names {name}, which is not a node with the role gpu.')
        if bool(pool.get('nodes')) == bool(pool.get('address')):
            problems.append('[gpu_pool] needs either nodes (GPU nodes of the site) or address (a shared pool), not both.')
        if not pool.get('api_key_file'):
            problems.append('[gpu_pool] has no api_key_file, the key of the model server.')
    elif site.with_role('gpu'):
        problems.append('the site has GPU nodes and no [gpu_pool] section.')
    if site.backup:
        node = nodes.get(site.backup.get('node'))
        if node is None:
            problems.append(f'[backup] node = {site.backup.get("node")} is not a node of the site.')
        elif node.has('gpu'):
            problems.append('[backup] node is a GPU node. Choose a node that holds application data.')
    patterns = _identity_patterns()
    seen = {}
    for hoover in site.hoovers.values():
        label = f'[hoover.{hoover.name}]'
        home = nodes.get(hoover.home_node)
        if home is None:
            problems.append(f'{label} home_node = {hoover.home_node} is not a node of the site.')
        elif not home.has('worker'):
            problems.append(f'{label} home_node = {hoover.home_node} does not have the role worker.')
        for key, pattern in patterns.items():
            if not pattern.fullmatch(getattr(hoover, key)):
                problems.append(f'{label} {key} = {getattr(hoover, key)} does not match {pattern.pattern}.')
        if hoover.stores == 'zone' and hoover.clickhouse_database_prefix != hoover.zone.replace('-', '_'):
            problems.append(f'{label} has stores = zone, whose service users and grants use the zone name. '
                            f'Set clickhouse_database_prefix = {hoover.zone.replace("-", "_")}, or use stores = local.')
        if hoover.stores == 'zone' and hoover.source_ini:
            problems.append(f'{label} has a source_ini. A migrated Compose install uses stores = local.')
        for name, node_name, _ in hoover.extra_datasets:
            if node_name not in nodes or not nodes[node_name].has('data'):
                problems.append(f'{label} extra_datasets names {node_name}, which is not a node with the role data.')
            if name in ('testdata', 'uploads'):
                problems.append(f'{label} extra_datasets uses the reserved name {name}.')
        if hoover.extra_datasets and (hoover.source_ini or single):
            problems.append(f'{label} has extra_datasets, which only an installation with NFS data folders reads.')
        if hoover.source_ini and hoover.temporal_backend != 'cassandra':
            problems.append(f'{label} has a source_ini. A Compose install keeps Temporal on Cassandra, so temporal_backend = cassandra.')
        # Each installation has its own namespace and its own stores. Two installations of one zone would share them.
        if hoover.zone in seen:
            problems.append(f'{label} and [hoover.{seen[hoover.zone]}] have the same zone = {hoover.zone}.')
        seen[hoover.zone] = hoover.name
    if check_files:
        problems += missing_files(site)
    return problems


def secret_files(site, node_name):
    """The secret file references that one node reads, as {label: path}."""
    node = site.nodes[node_name]
    out = {f'node.{node_name}.{k}': getattr(node, k) for k in SECRET_ROLES if getattr(node, k)}
    if node_name == site.control_plane:
        if site.gpu_pool.get('api_key_file'):
            out['gpu_pool.api_key_file'] = site.gpu_pool['api_key_file']
    return out


def missing_files(site):
    """The secret files and source paths of the local node that do not exist, as messages."""
    problems = []
    local = [n for n in site.nodes.values() if n.local]
    for node in local:
        for label, path in secret_files(site, node.name).items():
            if not os.path.isfile(path):
                problems.append(f'{label} = {path} is not an existing file on this host.')
    if local and local[0].name == site.control_plane:
        for hoover in site.hoovers.values():
            if hoover.source_ini and not os.path.isfile(hoover.source_ini):
                problems.append(f'[hoover.{hoover.name}] source_ini = {hoover.source_ini} is not an existing file.')
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


def dump(site):
    """The site file text of a Site. parse(dump(site)) gives an equal Site."""
    lines = ['[site]']
    for key in SITE_KEYS:
        value = getattr(site, key)
        if value:
            lines.append(f'{key} = {_text(value)}')
    for node in site.nodes.values():
        lines += ['', f'[node.{node.name}]']
        for key in NODE_KEYS:
            value = getattr(node, key)
            if value not in ('', ()):
                lines.append(f'{key} = {_text(value)}')
    for title, values, keys in (('gpu_pool', site.gpu_pool, GPU_POOL_KEYS), ('backup', site.backup, BACKUP_KEYS)):
        if values:
            lines += ['', f'[{title}]'] + [f'{k} = {_text(values[k])}' for k in keys if values.get(k) not in (None, '', ())]
    for hoover in site.hoovers.values():
        lines += ['', f'[hoover.{hoover.name}]']
        for key in HOOVER_KEYS:
            value = getattr(hoover, key)
            if value not in ('', ()) or key == 'manticore_table_prefix':
                lines.append(f'{key} = {_text(value)}')
    return '\n'.join(lines) + '\n'


def project(site, node_name):
    """The part of the site that one node receives, as a dict.

    Every node gets the site values and the addresses, roles and storage of every node, which its host scripts need
    for the VPN peers and the k3s join. A node gets only its own secret file references. The control plane also gets
    the GPU pool keys, the backup destination and the Hoover installations, because it creates the Secrets and runs
    the operator. No projection holds a secret value.
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
        out['hoovers'] = {name: asdict(h) for name, h in site.hoovers.items()}
    elif site.backup.get('node') == node_name:
        out['backup'] = dict(site.backup)
    return out


def node_address(site, node):
    """The address that the other nodes and the pods use for a node: the VPN address, else the LAN address, else the
    fixed local address of a single-node site."""
    if node.vpn_address:
        return node.vpn_address
    if node.lan_address:
        return node.lan_address
    if site.single and node.local:
        return LOCAL_ADDRESS
    raise SiteError(f'[node.{node.name}] has no vpn_address and no lan_address.')


def legacy_settings(site):
    """The values of the earlier private/settings.json, which the scripts of platform/, zones/ and tools/ read through
    settings.py. Each value comes from the site file."""
    public = site.with_role('public')[0]
    registry = site.with_role('registry')[0]
    binds = [a for a in (public.vpn_address, public.public_address) if a] or [node_address(site, public)]
    out = {
        'suffix': site.suffix,
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
                                  for h in site.hoovers.values() if h.extra_datasets}},
    }
    if site.vpn_cidr:
        out['vpn_cidr'] = site.vpn_cidr
    if not public.local:
        out['frontend_ssh'] = public.ssh_address
    if public.tls_dns_credentials_file:
        out['frontend_tls'] = f'/etc/letsencrypt/live/{site.suffix}'
        out['frontend_dns_credentials'] = public.tls_dns_credentials_file
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
    turn = [a for a in (node.vpn_address, node.public_address) if a] or [node_address(site, node)]
    return {'calls_node': node.name, 'calls_public_address': node.public_address, 'calls_turn_listen': turn}


def local_ca(site):
    """The root certificate of the local CA of the HTTPS frontend, when the frontend runs on the local node of the site.

    ../platform/frontend/install-local-frontend.sh writes it. The pods that call the zone names over HTTPS trust it.
    """
    public = site.with_role('public')
    path = PRIVATE / 'frontend' / 'local-ca.crt'
    return path.read_text() if public and public[0].local and path.exists() else ''


def legacy_hosts(site):
    """The site in the format of hosts.json, which the host scripts of hosts/ read."""
    hosts = {}
    for node in site.nodes.values():
        hosts[node.name] = {
            'wg_ip': node.vpn_address or None, 'wg_if': node.vpn_interface, 'key': node.wireguard_public_key,
            'port': node.wireguard_port,
            'public': f'{node.public_address}:{node.wireguard_port}' if node.public_address else None,
            'lan_ip': node.lan_address or None, 'onprem': node.onprem, 'reserved': node.reserved,
            'tiers': list(node.storage_tiers), 'avx2': node.avx2,
            'local': node.local, 'single': site.single, 'architecture': node.architecture,
            'node_ip': node_address(site, node), 'vg': node.lvm_volume_group,
            'physical_volumes': list(node.lvm_physical_volumes), 'gpu': node.has('gpu'),
        }
    return {'server': site.control_plane, 'user': site.operator_user, 'suffix': site.suffix, 'hosts': hosts}


# ----------------------------------------------------------------------------------------------------------------------
# The hoover4.ini of an earlier Compose install
# ----------------------------------------------------------------------------------------------------------------------

@dataclass
class SourceInstall:
    """The resources that an earlier Compose install names, after their checks."""
    path: str
    values: dict
    explicit: list
    dropped: list
    volumes_path: str
    volumes: dict
    dataset_mounts: list
    ops_backup_dir: str
    chat_control_dir: str


def deploy_module():
    spec = importlib.util.spec_from_file_location('hoover_deploy_source', REPO / 'deploy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_source_ini(path, check_paths=True):
    """Read the hoover4.ini of a Compose install for a migration or a one-time settings seed.

    The reader accepts each setting that deploy.py lists as removed, such as the Serena settings, and leaves it out.
    It refuses an unknown section or key and every other problem that `./deploy --check` refuses. With check_paths it
    also refuses a missing volumes folder, a missing store folder, a missing dataset folder and a host folder that two
    mounts share. It reads files only. It writes nothing.
    """
    deploy = deploy_module()
    parser = configparser.ConfigParser(inline_comment_prefixes=None, default_section='\n')
    try:
        with open(path, encoding='utf-8') as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as error:
        raise SiteError(f'the source ini {path} cannot be read: {error}') from None
    cfg = deploy.Config(None)
    problems, dropped = [], []
    for section in parser.sections():
        if (section, None) in deploy.REMOVED_SETTINGS:
            dropped.append(f'[{section}]')
            continue
        problem = deploy.Config._section_problem(section)
        if problem:
            problems.append(problem)
            continue
        cfg.values.setdefault(section, {})
        for key in parser.options(section):
            if (section, key) in deploy.REMOVED_SETTINGS:
                dropped.append(f'[{section}] {key}')
                continue
            problem = deploy.Config._key_problem(section, key)
            if problem:
                problems.append(problem)
                continue
            raw = parser.get(section, key, raw=True)
            if deploy.INLINE_COMMENT.search(raw):
                problems.append(f'[{section}] {key} has a comment after its value.')
                continue
            try:
                cfg.values[section][key] = parser.get(section, key).strip()
            except configparser.InterpolationError:
                problems.append(f'[{section}] {key} has a % sign that is not written as %%.')
                continue
            cfg.explicit.add((section, key))
    if problems:
        raise SiteError(f'the source ini {path} has {len(problems)} problem{"s" if len(problems) != 1 else ""}:\n    '
                        + '\n    '.join(problems))
    problem = deploy.volumes_path_problem(cfg)
    if problem:
        raise SiteError(f'the source ini {path}: {problem}')
    try:
        mounts = deploy.dataset_mounts(cfg)
    except deploy.DeployError as error:
        raise SiteError(f'the source ini {path}: {error}') from None
    root = cfg.get('storage', 'volumes_path').strip()
    volumes = {row.name: os.path.join(root, row.name) for row in deploy.VOLUMES if row.side == 'main'}
    backup = cfg.get('main_services', 'ops_backup_dir').strip() or volumes['ops_backups']
    control = cfg.get('main_services', 'chat_control_dir').strip()
    if check_paths:
        problems = []
        if not os.path.isdir(root):
            problems.append(f'[storage] volumes_path = {root} is not an existing folder.')
        for name in ('clickhouse_data', 'manticore_data_v14', 'garage_meta', 'garage_data', 'temporal_cassandra',
                     'temporal_elasticsearch'):
            if not os.path.isdir(volumes[name]):
                problems.append(f'the store folder {volumes[name]} does not exist.')
        problems += deploy.dataset_mount_refusals(cfg)
        if control and not os.path.isdir(control):
            problems.append(f'[main_services] chat_control_dir = {control} is not an existing folder.')
        real = {}
        for mount in mounts:
            resolved = os.path.realpath(mount.host_path)
            for other, name in real.items():
                if resolved == other or resolved.startswith(other + '/') or other.startswith(resolved + '/'):
                    problems.append(f'[dataset_mount.{mount.name}] and [dataset_mount.{name}] share the host folder {resolved}.')
            real[resolved] = mount.name
        for mount in mounts:
            if os.path.realpath(mount.host_path).startswith(os.path.realpath(root) + '/'):
                problems.append(f'[dataset_mount.{mount.name}] host_path is inside volumes_path, so the copy is ambiguous.')
        if problems:
            raise SiteError(f'the source ini {path} names paths that cannot be copied:\n    ' + '\n    '.join(problems))
    values = {s: dict(k) for s, k in cfg.values.items()}
    return SourceInstall(path=str(path), values=values, explicit=sorted(f'{s}.{k}' for s, k in cfg.explicit),
                         dropped=dropped, volumes_path=root, volumes=volumes,
                         dataset_mounts=[{'name': m.name, 'host_path': m.host_path, 'container_path': m.container_path,
                                          'writable': m.writable} for m in mounts],
                         ops_backup_dir=backup, chat_control_dir=control)


def main(argv):
    if len(argv) >= 2 and argv[0] == 'check':
        site = read(argv[1], check_files=True)
        print(json.dumps({'site': site.name, 'nodes': {n.name: list(n.roles) for n in site.nodes.values()},
                          'hoovers': sorted(site.hoovers)}, indent=1))
    elif len(argv) == 3 and argv[0] == 'project':
        print(json.dumps(project(read(argv[1]), argv[2]), indent=1, default=list))
    elif len(argv) == 2 and argv[0] == 'source':
        print(json.dumps(asdict(read_source_ini(argv[1])), indent=1))
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except SiteError as error:
        raise SystemExit(str(error))
