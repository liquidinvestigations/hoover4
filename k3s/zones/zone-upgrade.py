#!/usr/bin/env python3
"""Upgrade a zone through zone.py, or record its rendered manifests privately.

A disabled zone is rendered without applying objects or running Helm hooks.
Usage: zone-upgrade.py <zone> [--render-only]
"""
import hashlib, json, sys
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
STORES = HERE.parent / 'hoover' / 'stores'
sys.path.insert(0, str(STORES))
import common  # noqa: E402
import settings  # noqa: E402

import zone as installer  # noqa: E402


def helmfile(zone, command):
    return installer.helmfile(zone, command, check=False)


def started(documents):
    """Return the rendered objects that would run in a disabled zone, and the Helm hooks.

    Helm does not pass hooks to the post-renderer, so a hook Job keeps its chart form. Only an applied release runs
    hooks, and this tool never applies a disabled zone.
    """
    found, hooks = [], []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        kind, name = doc.get('kind'), doc.get('metadata', {}).get('name')
        if 'helm.sh/hook' in (doc['metadata'].get('annotations') or {}):
            hooks.append(f'{kind}/{name}')
            continue
        if kind in ('Deployment', 'StatefulSet', 'ReplicaSet') and doc['spec'].get('replicas', 1):
            found.append(f'{kind}/{name}')
        elif kind in ('CronJob', 'Job') and not doc['spec'].get('suspend'):
            found.append(f'{kind}/{name}')
        elif kind in ('DaemonSet', 'Pod'):
            found.append(f'{kind}/{name}')
    return found, hooks


def render(zone, disabled):
    rendered = helmfile(zone, 'template')
    if rendered.returncode:
        sys.stderr.write(rendered.stderr[-2000:])
        raise SystemExit(rendered.returncode)
    common.PRIVATE.mkdir(parents=True, exist_ok=True)
    # The render holds Secrets, so it stays in the private folder.
    (common.PRIVATE / f'{zone}-render.yaml').write_text(rendered.stdout)
    (common.PRIVATE / f'{zone}-render.yaml').chmod(0o600)
    documents = list(yaml.safe_load_all(rendered.stdout))
    running, hooks = started(documents)
    records = [d for d in documents if isinstance(d, dict) and d.get('kind') in ('Deployment', 'StatefulSet')]
    replicas = {f"{d['kind']}/{d['metadata']['name']}": d['spec'].get('replicas', 1) for d in records}
    common.log('upgrade.jsonl', zone=zone, mode='render-only', disabled=disabled, documents=len(documents),
               render_sha256=hashlib.sha256(rendered.stdout.encode()).hexdigest(), started=running, hooks_not_applied=hooks,
               replicas=replicas)
    if disabled and running:
        raise SystemExit(1)
    return documents


def main():
    zone = sys.argv[1]
    if not common.namespace_enabled(zone) or '--render-only' in sys.argv:
        return render(zone, not common.namespace_enabled(zone))
    installer.apply(zone, None)


if __name__ == '__main__':
    main()
