#!/usr/bin/env python3
"""Write one copy of each root install script for each host of the site file.

root-install.py and root-install-k3s.py are the sources. Each copy sets THIS to the host name and SITE to
the content of the site file, so the person can copy one file to the host and run it there as root.
The copies go to <out>/<host>/root-install-<host>.py and <out>/<host>/root-install-k3s-<host>.py.

Usage: write-host-copies.py [--site FILE] [--out DIR] [host ...]
The default site file is k3s/private/hosts.json, and the default output folder is k3s/private/hosts.
hosts.example.json shows the format of the site file. The site file and the copies stay out of Git.
"""
import argparse
import json
import pprint
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIVATE = HERE.parent / "private"
SOURCES = {"root-install.py": "root-install-{}.py", "root-install-k3s.py": "root-install-k3s-{}.py"}
REQUIRED = {"wg_ip", "key", "port", "public", "lan_ip", "onprem", "reserved"}


def fill(text, host, site):
    """Return the source text with THIS and SITE set. Fail when a placeholder line is not there exactly once."""
    for line in ("THIS = None\n", "SITE = None\n"):
        if text.count(line) != 1:
            sys.exit(f"the source must hold the line {line.strip()!r} exactly once")
    value = pprint.pformat(site, width=110, sort_dicts=False)
    return text.replace("THIS = None\n", f"THIS = {host!r}\n").replace("SITE = None\n", f"SITE = {value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", type=Path, default=PRIVATE / "hosts.json")
    parser.add_argument("--out", type=Path, default=PRIVATE / "hosts")
    parser.add_argument("hosts", nargs="*", help="write only these hosts")
    args = parser.parse_args()
    site = json.loads(args.site.read_text())
    if site.get("server") not in site.get("hosts", {}):
        sys.exit(f"{args.site}: the server must be one of the hosts")
    for name, host in site["hosts"].items():
        missing = REQUIRED - set(host)
        if missing:
            sys.exit(f"{args.site}: the host {name} has no {', '.join(sorted(missing))}")
    for host in args.hosts or list(site["hosts"]):
        if host not in site["hosts"]:
            sys.exit(f"{host} is not a host of {args.site}")
        folder = args.out / host
        folder.mkdir(parents=True, exist_ok=True)
        for source, pattern in SOURCES.items():
            target = folder / pattern.format(host)
            target.write_text(fill((HERE / source).read_text(), host, site))
            target.chmod(0o755)
            print(target)


if __name__ == "__main__":
    main()
