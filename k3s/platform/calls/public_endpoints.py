#!/usr/bin/env python3
"""Print the public DNS records and the firewall rules of a site, from its site file. It changes nothing.

DNS: every name below the suffix that a browser or a call client uses, and the address that it must have.
- The HTTPS names of each zone (portal, id, hoover, the openDesk applications, sfu) and the operator portal point to
  the public address of the first public node, where the HTTPS frontend runs.
- turn.<suffix> points to the public address of the media node (the calls node, else the public node), because a call
  client sends its TURN traffic there.
A node without a public address gets its VPN address, and the record is marked internal: a client outside the VPN
cannot use it.
Firewall: the ports that each public or calls node admits on its public interface. The media ports of the media node
are UDP 10000 (JVB), TCP 7881 and UDP 7882 (LiveKit) and UDP and TCP 3478 (TURN).
../../hosts/root-install-public-firewall.sh admits these ports. Run it on each node of the table.
Usage: public_endpoints.py dns|firewall|show [--site FILE]
"""
import argparse
import json
import os
import sys
from pathlib import Path

K3S = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(K3S))
import config as site_config  # noqa: E402


def zone_names():
    """The host names of each zone below <zone>.<suffix>: HOSTS of ../../zones/zones.py and hoover."""
    import ast
    tree = ast.parse((K3S / 'zones/zones.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'HOSTS' for t in node.targets):
            return list(ast.literal_eval(node.value)) + ['hoover']
    raise SystemExit('zones/zones.py has no HOSTS list.')


FRONTEND_PORTS = [('tcp', 22, 'SSH'), ('tcp', 80, 'HTTP of the frontend'), ('tcp', 443, 'HTTPS of the frontend'),
                  ('udp', 443, 'HTTP/3 of the frontend')]
MEDIA_PORTS = [('udp', 3478, 'TURN'), ('tcp', 3478, 'TURN over TCP'), ('udp', 10000, 'JVB media'),
               ('tcp', 7881, 'LiveKit media over TCP'), ('udp', 7882, 'LiveKit media')]


def address(node):
    return node.public_address or node.vpn_address


def dns(site):
    frontend = site.with_role('public')[0]
    media = site_config.calls_node(site)
    rows = [{'name': f'operator.{site.suffix}', 'address': address(frontend), 'internal': not frontend.public_address}]
    for zone in sorted({h.zone for h in site.hoovers.values()}):
        rows += [{'name': name, 'address': address(frontend), 'internal': not frontend.public_address}
                 for name in [f'{zone}.{site.suffix}'] + [f'{n}.{zone}.{site.suffix}' for n in zone_names()]]
    rows.append({'name': f'turn.{site.suffix}', 'address': address(media), 'internal': not media.public_address})
    return rows


def firewall(site):
    frontend = site.with_role('public')[0]
    media = site_config.calls_node(site)
    out = {}
    for node in (frontend, media):
        rules = out.setdefault(node.name, [])
        if node is frontend:
            rules += [r for r in FRONTEND_PORTS if r not in rules]
        if node is media:
            rules += [r for r in MEDIA_PORTS if r not in rules]
        if node.vpn_address and ('udp', node.wireguard_port, 'WireGuard') not in rules:
            rules.append(('udp', node.wireguard_port, 'WireGuard'))
        if ('tcp', 22, 'SSH') not in rules:
            rules.insert(0, ('tcp', 22, 'SSH'))
    return {name: [{'protocol': p, 'port': port, 'purpose': purpose} for p, port, purpose in rules] for name, rules in out.items()}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('dns', 'firewall', 'show'))
    parser.add_argument('--site', default=os.environ.get('HOOVER4_SITE', str(site_config.DEFAULT_SITE)))
    args = parser.parse_args(argv)
    site = site_config.read(args.site)
    out = {'dns': dns(site), 'firewall': firewall(site), 'media_node': site_config.calls_node(site).name}
    print(json.dumps(out if args.command == 'show' else out[args.command], indent=1))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except site_config.SiteError as error:
        raise SystemExit(str(error))
