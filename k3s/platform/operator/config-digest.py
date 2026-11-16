#!/usr/bin/env python3
"""Restart a Deployment of operator-portal only when the configuration that its pods read at start changed.

start-web-tools.sh runs this file after it applied the ConfigMaps and the Secret of the operator login. For each
Deployment of READS, the file computes a SHA-256 of the data of the objects that its pods read at start, and writes it
into the pod template annotation hoover.dev/config. A changed value starts new pods. The same value changes nothing, so
a second run of the operator step restarts no pod. kubectl apply keeps the annotation, because the manifest does not
name it. KUBECONFIG names the admin kubeconfig.
"""
import hashlib
import json
import subprocess

NAMESPACE = 'operator-portal'
ANNOTATION = 'hoover.dev/config'
# {Deployment: [(kind, name, keys)]}. keys None means every key of the object.
READS = {
    'dex': [('configmap', 'dex', None), ('configmap', 'dex-templates', None), ('secret', 'operator-login', ['client-secret'])],
    'gateway': [('configmap', 'gateway', None),
                ('secret', 'operator-login', ['client-secret', 'cookie-secret', 'proxy-secret'])],
    'portal': [('configmap', 'portal-site', None), ('secret', 'operator-login', ['proxy-secret'])],
}


def kubectl(*args):
    return subprocess.run(['kubectl', '-n', NAMESPACE, *args], capture_output=True, text=True, check=True).stdout


def digest(reads, get):
    """The digest of the objects of reads. get(kind, name) returns the data of an object."""
    h = hashlib.sha256()
    for kind, name, keys in reads:
        data = get(kind, name)
        chosen = {k: v for k, v in sorted(data.items()) if keys is None or k in keys}
        h.update(json.dumps([kind, name, chosen], sort_keys=True).encode())
    return h.hexdigest()[:16]


def main():
    cache = {}

    def get(kind, name):
        if (kind, name) not in cache:
            item = json.loads(kubectl('get', kind, name, '-o', 'json'))
            cache[kind, name] = {**(item.get('data') or {}), **(item.get('binaryData') or {})}
        return cache[kind, name]
    for deployment, reads in READS.items():
        value = digest(reads, get)
        found = kubectl('get', 'deployment', deployment, '-o',
                        r'jsonpath={.spec.template.metadata.annotations.hoover\.dev/config}').strip()
        if found == value:
            print(json.dumps({'deployment': deployment, 'config': value, 'restart': False}))
            continue
        kubectl('patch', 'deployment', deployment, '--type', 'merge', '-p',
                json.dumps({'spec': {'template': {'metadata': {'annotations': {ANNOTATION: value}}}}}))
        print(json.dumps({'deployment': deployment, 'config': value, 'restart': True}))


if __name__ == '__main__':
    main()
