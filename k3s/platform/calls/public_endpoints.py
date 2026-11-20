#!/usr/bin/env python3
"""Print the public DNS records and the firewall rules of a site, from its site file. It changes nothing.

DNS: the names below the suffix that a browser or a call client uses, and the address that each must have.
- *.<suffix> and <suffix> point to the public address of the first public node, where the HTTPS frontend runs. The
  wildcard covers every zone host <zone>-<app>.<suffix>, each zone domain <zone>.<suffix> and the operator portal, so
  a zone add or delete needs no DNS change.
- turn.<suffix> points to the public address of the media node (the calls node, else the public node), because a call
  client sends its TURN traffic there. The record of this name takes precedence over the wildcard.
A node without a public address gets its node address, and the record is marked internal: a client outside the
networks of the site cannot use it.
Firewall: the ports that each public or calls node admits on its public interface. The media ports of the media node
are UDP 10000 (JVB) and UDP and TCP 3478 (TURN).
The switch public_firewall of each of these nodes installs ../../ansible/roles/hoover4_public_firewall, whose
files/public-firewall.sh admits these ports on a separate public interface.
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


FRONTEND_PORTS = [('tcp', 22, 'SSH'), ('tcp', 80, 'HTTP of the frontend'), ('tcp', 443, 'HTTPS of the frontend'),
                  ('udp', 443, 'HTTP/3 of the frontend')]
MEDIA_PORTS = [('udp', 3478, 'TURN'), ('tcp', 3478, 'TURN over TCP'), ('udp', 10000, 'JVB media')]


def address(site, node):
    return node.public_address or site_config.node_address(site, node)


def dns(site):
    frontend = site.with_role('public')[0]
    media = site_config.calls_node(site)
    rows = [{'name': name, 'address': address(site, frontend), 'internal': not frontend.public_address}
            for name in (f'*.{site.domain}', site.domain)]
    rows.append({'name': f'turn.{site.domain}', 'address': address(site, media), 'internal': not media.public_address})
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
        for port in sorted({m.port for m in node.networks.values()}):
            if ('udp', port, 'WireGuard') not in rules:
                rules.append(('udp', port, 'WireGuard'))
        if ('tcp', 22, 'SSH') not in rules:
            rules.insert(0, ('tcp', 22, 'SSH'))
    return {name: [{'protocol': p, 'port': port, 'purpose': purpose} for p, port, purpose in rules] for name, rules in out.items()}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('dns', 'firewall', 'show'))
    parser.add_argument('--site', default=os.environ.get('HOOVER4_SITE'),
                        required=not os.environ.get('HOOVER4_SITE'))
    args = parser.parse_args(argv)
    site = site_config.read(args.site)
    out = {'dns': dns(site), 'firewall': firewall(site), 'media_node': site_config.calls_node(site).name}
    print(json.dumps(out if args.command == 'show' else out[args.command], indent=1))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except site_config.SiteError as error:
        raise SystemExit(str(error))
