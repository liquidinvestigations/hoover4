"""Shared paths and cluster access for the zone tools and the Kata store tools."""
import json, subprocess, sys, time
from pathlib import Path

LAB = Path(__file__).resolve().parent
SOURCE = LAB.parents[1]
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / 'zones'))
import settings  # noqa: E402
import zonestate  # noqa: E402

PRIVATE = settings.PRIVATE / 'stores'
# The JSON lines of each store operation. They hold no credential.
EVIDENCE = settings.PRIVATE / 'logs'
K = ['kubectl', '--kubeconfig', settings.KUBECONFIG]
LABEL = 'hoover.dev/kata-stores'


def namespace_enabled(namespace):
    """Return False for a namespace of a disabled zone. An unreadable zone state disables every zone namespace."""
    try:
        return zonestate.namespace_enabled(namespace)
    except zonestate.ZoneStateError:
        return zonestate.zone_of(namespace, {'zones': {}}) is None


def kubectl(*args, input=None, check=True):
    result = subprocess.run(K + list(args), check=False, capture_output=True, text=True, input=input)
    if check and result.returncode:
        sys.stderr.write(result.stderr)
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    return result.stdout


def kubectl_json(*args):
    return json.loads(kubectl(*args, '-o', 'json'))


def apply(obj):
    kubectl('apply', '-f', '-', input=json.dumps(obj))


def log(name, **row):
    """Append one JSON line to a log file in the private folder and print it."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    row = {'at': round(time.time(), 3), **row}
    with (EVIDENCE / name).open('a') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row)[:800], flush=True)
