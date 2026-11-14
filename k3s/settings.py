#!/usr/bin/env python3
"""Read the site settings and the private paths of the deployment.

HOOVER4_SITE names the site file (../config.py). It has no default. The state folder of the site holds the secrets,
the admin kubeconfig and the generated files. It is the folder beside the site file with the name of the file without
its extension (config.state_folder()), for example k3s/private/demo/ for k3s/private/demo.yml. Git ignores
k3s/private. Every private path of the scripts of platform/, zones/, hoover/ and tools/ is in PRIVATE. Their comments
write it as <state folder>/<path>.
config.legacy_settings() gives these values:
  suffix          the domain of the site, below which each zone has its names, for example <app>.<zone>.<suffix>
  frontend_bind   the addresses where the HTTPS frontend listens, for example a VPN address and a public address
  frontend_local  true when the HTTPS frontend runs on this host with a local CA
  frontend_ssh    the SSH destination of the public node (config.ssh_host())
  frontend_tls_mode  the TLS mode of the frontend: cloudflare, internal or files (config.TLS_MODES)
  frontend_tls    the certbot folder of the public certificate of the mode cloudflare
  frontend_tls_certificate, frontend_tls_key  the certificate files of the modes cloudflare and files
  turn_listen     the addresses where coturn listens
  other keys      values that install scripts read with `get`
A site file that does not exist gives the values of settings.json of its state folder, and the defaults below apply.
The admin kubeconfig is kubeconfig of the state folder, unless KUBECONFIG names another file. A relative KUBECONFIG path
starts at the current folder.
HOOVER4 names the Hoover4 checkout. The default is the repository that holds this folder. The image build, the Hoover
manifests and the browser checks read it.
Usage: settings.py suffix | frontend_bind | private | get <key> <default> | hosts
hosts prints the hosts.json form of the site file, which cluster/setup.sh and the host scripts read.
"""
import json
import os
import pathlib
import sys

SOURCE = pathlib.Path(__file__).resolve().parent
if not os.environ.get('HOOVER4_SITE'):
    raise SystemExit('HOOVER4_SITE names no site file. Set it to the site file of the site, for example '
                     'k3s/private/<site>.yml.')
SITE_FILE = pathlib.Path(os.environ['HOOVER4_SITE']).resolve()
sys.path.insert(0, str(SOURCE))
import config  # noqa: E402
PRIVATE = config.state_folder(SITE_FILE)
PATH = PRIVATE / 'settings.json'


def _site():
    """The parsed site file, or None when the installation has none."""
    if not SITE_FILE.exists():
        return None
    return config.read(SITE_FILE)


SITE = _site()
if SITE is not None:
    HOST = config.legacy_settings(SITE)
else:
    HOST = json.loads(PATH.read_text()) if PATH.exists() else {}
SUFFIX = HOST.get('suffix', 'hoover.test')
FRONTEND_BIND = HOST.get('frontend_bind', [])
# The installers run helmfile and scripts from other folders, so each relative entry becomes an absolute path.
KUBECONFIG = os.pathsep.join(os.path.abspath(p) for p in os.environ.get('KUBECONFIG', '').split(os.pathsep) if p) \
    or str(PRIVATE / 'kubeconfig')
HOOVER4 = pathlib.Path(os.environ.get('HOOVER4') or SOURCE.parent)


def use_kubeconfig():
    """Set KUBECONFIG for kubectl and helm in this process and its children."""
    os.environ['KUBECONFIG'] = KUBECONFIG


if __name__ == '__main__':
    if sys.argv[1] == 'get':
        value = HOST.get(sys.argv[2], sys.argv[3])
        print(json.dumps(value) if isinstance(value, (dict, list, bool)) else value)
    elif sys.argv[1] == 'hosts':
        if SITE is None:
            print((PRIVATE / 'hosts.json').read_text(), end='')
        else:
            print(json.dumps(config.legacy_hosts(SITE), indent=1))
    else:
        print({'suffix': SUFFIX, 'frontend_bind': ' '.join(FRONTEND_BIND), 'private': str(PRIVATE)}[sys.argv[1]])
