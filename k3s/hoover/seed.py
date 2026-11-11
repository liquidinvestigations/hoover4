#!/usr/bin/env python3
"""Load the upstream fixture corpus into the demo collection of one zone. Each step is idempotent.

The corpus is the revision of the hoover-testdata checkout that fetch-testdata.sh pins. The script reads that revision
with git archive, so the commit of the working tree does not matter. It copies the corpus with tar through the NFS
server pod of the data node into <zone>/testdata of the data root (../platform/hoover-data/hoover_data.py). The Hoover
pods see it below /data/testdata. The script writes the size and SHA-256 of each file of the selected datasets to the
output file. It then creates the collection `demo` and adds each dataset of qa/datasets.json that the upstream verifier
ingests, with --wait. An existing collection or dataset stays.
Usage: seed.py <zone> [output.json]
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'platform' / 'hoover-data'))
import settings  # noqa: E402
import hoover_data  # noqa: E402
K = ['kubectl', '--kubeconfig', settings.KUBECONFIG]
CORPUS = settings.HOOVER4 / 'testdata/hoover-testdata'
REVISION = '75f446b724b4e3b514ddb9966067afcf2fbe0a5a'
# The datasets that main_services/verify-stack.sh ingests, with the dataset name in the demo collection.
DATASETS = {'testdata_testfiles': 'testfiles', 'testdata_emails': 'emails', 'testdata_zips': 'zips',
            'testdata_shapes': 'shapes', 'testdata_filenames': 'filenames'}
ZONE = sys.argv[1]
NS = 'hoover-' + ZONE
MOUNT = '/data/testdata/hoover-testdata'


def kubectl(*args, check=True):
    r = subprocess.run(K + ['-n', NS, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:6])} failed: {(r.stderr or r.stdout).strip()[-600:]}')
    return r


def worker(*args, check=True):
    return kubectl('exec', 'deploy/hoover-workers', '-c', 'hoover-workers', '--', '/opt/pysetup/.venv/bin/python3', 'main.py', *args, check=check)


def manifest(tree, roots):
    rows = []
    for root in roots:
        for path in sorted((tree / root).rglob('*')):
            if path.is_file():
                rows.append({'path': str(path.relative_to(tree)), 'bytes': path.stat().st_size,
                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return rows


def copy(tree, roots):
    """Copy the exported corpus into the data directory of the zone, and return its manifest."""
    node = hoover_data.data_node(ZONE)
    target = f'/exports/{ZONE}/testdata/hoover-testdata'
    server = K + ['-n', hoover_data.NS, 'exec', '-i', f'deploy/nfs-{node}', '--', 'sh', '-c']
    # The server pod runs as root, and the copy gives the worker user read access.
    tar = subprocess.Popen(['tar', '-C', str(tree), '-cf', '-', 'qa', *roots.values()], stdout=subprocess.PIPE)
    subprocess.run(server + [f'mkdir -p {target} && tar -C {target} -xf - && chmod -R a+rX {target}'], stdin=tar.stdout,
                   check=True)
    tar.stdout.close()
    if tar.wait():
        raise SystemExit('tar of the corpus failed')
    return manifest(tree, roots.values())


def main():
    found = subprocess.run(['git', '-C', str(CORPUS), 'show', f'{REVISION}:qa/datasets.json'], capture_output=True, text=True)
    if found.returncode:
        raise SystemExit(f'the corpus checkout has no revision {REVISION}. Run main_services/fetch-testdata.sh.')
    listed = {d['name']: d['root'] for d in json.loads(found.stdout)['datasets']}
    roots = {name: listed[name] for name in DATASETS}
    with tempfile.TemporaryDirectory(prefix='hoover-testdata-') as tree:
        archive = subprocess.Popen(['git', '-C', str(CORPUS), 'archive', REVISION, 'qa', *roots.values()], stdout=subprocess.PIPE)
        subprocess.run(['tar', '-x', '-C', tree], stdin=archive.stdout, check=True)
        if archive.wait():
            raise SystemExit(f'git archive of {REVISION} failed')
        files = copy(Path(tree), roots)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps({'revision': REVISION, 'datasets': roots, 'files': len(files),
                                                 'bytes': sum(f['bytes'] for f in files), 'manifest': files}, indent=1))
    collections = worker('list-collections').stdout
    if 'demo' not in collections.split():
        worker('create-collection', 'demo')
    for source, name in DATASETS.items():
        r = worker('add-disk-dataset', 'demo', name, f'{MOUNT}/{roots[source]}', '--wait', check=False)
        print(json.dumps({'dataset': name, 'root': roots[source], 'exit': r.returncode, 'tail': (r.stdout + r.stderr).strip()[-300:]}), flush=True)
    print(json.dumps({'files': len(files), 'bytes': sum(f['bytes'] for f in files)}))


if __name__ == '__main__':
    main()
