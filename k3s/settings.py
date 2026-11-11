#!/usr/bin/env python3
"""Read the site settings and the private paths of the deployment.

k3s/private/ holds the site settings, the secrets, the admin kubeconfig and the generated files. Git ignores it.
k3s/private/settings.json holds the values of the site. Without the file, the defaults below apply.
  suffix          the domain below which each zone has its names, for example <app>.<zone>.<suffix>
  frontend_bind   extra addresses where the HTTPS frontend listens, for example a VPN address or a public address
  frontend_tls    a folder with fullchain.pem and privkey.pem of a public certificate for the frontend.
                  A relative path starts at k3s/.
  turn_listen     extra addresses where coturn listens, for example a public address
  other keys      values that install scripts read with `get`
The admin kubeconfig is k3s/private/kubeconfig, unless KUBECONFIG names another file. A relative KUBECONFIG path
starts at the current folder.
HOOVER4 names the Hoover4 checkout. The default is the repository that holds this folder. The image build, the Hoover
manifests and the browser checks read it.
Usage: settings.py suffix | frontend_bind | private | get <key> <default>
"""
import json
import os
import pathlib
import sys

SOURCE = pathlib.Path(__file__).resolve().parent
PRIVATE = SOURCE / 'private'
PATH = PRIVATE / 'settings.json'
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
        print(HOST.get(sys.argv[2], sys.argv[3]))
    else:
        print({'suffix': SUFFIX, 'frontend_bind': ' '.join(FRONTEND_BIND), 'private': str(PRIVATE)}[sys.argv[1]])
