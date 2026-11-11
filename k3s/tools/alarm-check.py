#!/usr/bin/env python3
"""Fill a volume, a volume group and the containerd volume, and check that each alarm fires.

  pvc <node>         fills an ext4 volume until 3 % of it is free. Alarm VolumeAlmostFull.
  vg <node>          takes the free space of the volume group of the first tier of the node with one block volume.
                     Alarm VolumeGroupAlmostFull. TopoLVM keeps 10 GB free, so the group never reaches 0 bytes.
  containerd <node>  fills /var/lib/rancher of the node with one file until 17 % of it is free. The kubelet removes
                     images above 85 % use and pods below 5 % free space, so the fill stays above both limits.
                     Alarm ContainerVolumeAlmostFull.
  oom <node>         a container that stops at its memory limit again and again. Alarms ContainerOutOfMemory and
                     PodRestarts.
Each check writes and reads 16 MiB on a second volume of the same node during the fill, so the other volumes are
shown to work. It removes the fill, deletes the namespace alarm-check and prints JSON lines. It exits with 1 when an
alarm does not fire within 6 minutes or the second volume fails.
The containerd check writes a file into /var/lib/rancher of the node from a privileged pod, and removes it at the end.
Usage: alarm-check.py pvc|vg|containerd|oom <node>
"""
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'zones'))
import settings  # noqa: E402
import zonestate  # noqa: E402

K = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG)]
NS = 'alarm-check'
IMAGE = 'docker.io/library/alpine:3.22'
ALERTS = '/api/v1/namespaces/monitoring/services/http:monitor-kube-prometheus-st-prometheus:9090/proxy/api/v1/alerts'
FILL = '/var/lib/rancher/hoover-alarm-check.fill'


def kubectl(*args, input=None, check=True):
    r = subprocess.run(K + list(args), input=input, capture_output=True, text=True, timeout=900)
    if check and r.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:5])}: {r.stderr.strip()[-500:]}')
    return r.stdout


def report(**row):
    print(json.dumps({'at': time.strftime('%H:%M:%S'), **row}), flush=True)


def apply(obj):
    obj.setdefault('metadata', {})['namespace'] = NS
    kubectl('apply', '-f', '-', input=json.dumps(obj))


def claim(name, size, storage_class, block=False):
    spec = {'accessModes': ['ReadWriteOnce'], 'storageClassName': storage_class, 'resources': {'requests': {'storage': size}}}
    if block:
        spec['volumeMode'] = 'Block'
    apply({'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name}, 'spec': spec})


def pod(name, node, command, claim_name=None, block=False, privileged=False, memory='64Mi', restart='Never'):
    container = {'name': 'main', 'image': IMAGE, 'command': ['sh', '-c', command],
                 'resources': {'requests': {'memory': '16Mi'}, 'limits': {'memory': memory}}}
    # A node selector, not nodeName: TopoLVM binds a WaitForFirstConsumer volume only through the scheduler.
    spec = {'nodeSelector': {'kubernetes.io/hostname': node}, 'restartPolicy': restart, 'containers': [container], 'volumes': []}
    if claim_name:
        spec['volumes'].append({'name': 'data', 'persistentVolumeClaim': {'claimName': claim_name}})
        container['volumeDevices' if block else 'volumeMounts'] = [{'name': 'data', 'devicePath': '/dev/data'} if block else
                                                                   {'name': 'data', 'mountPath': '/data'}]
    if privileged:
        container['securityContext'] = {'privileged': True}
        spec['volumes'].append({'name': 'rancher', 'hostPath': {'path': '/var/lib/rancher'}})
        container['volumeMounts'] = [{'name': 'rancher', 'mountPath': '/var/lib/rancher'}]
    apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name}, 'spec': spec})


def wait_running(name, seconds=300):
    deadline = time.time() + seconds
    while time.time() < deadline:
        phase = kubectl('-n', NS, 'get', 'pod', name, '-o', 'jsonpath={.status.phase}', check=False)
        if phase in ('Running', 'Succeeded', 'Failed'):
            return phase
        time.sleep(2)
    raise SystemExit(f'{name} did not start')


def run(name, command):
    return kubectl('-n', NS, 'exec', name, '--', 'sh', '-c', command).strip()


def alert(names, seconds=360):
    """Wait until every alert in names fires for an object of this check. Return the seconds or None."""
    start = time.time()
    while time.time() - start < seconds:
        alerts = json.loads(kubectl('get', '--raw', ALERTS))['data']['alerts']
        firing = {a['labels']['alertname'] for a in alerts if a['state'] == 'firing' and match(a['labels'])}
        if set(names) <= firing:
            return round(time.time() - start)
        time.sleep(10)
    return None


def match(labels):
    # The check objects are in its namespace. The node alarms name the node or its exporter address.
    return labels.get('namespace') == NS or labels.get('node') == NODE or NODE_ADDRESS in labels.get('instance', '')


def fill_command(folder, path, keep):
    """Return a shell command that fills the file system of folder with one file until keep % of it is free."""
    # The available space excludes the blocks that ext4 keeps for root. printf %d, because awk prints a large number in
    # exponent form. df -P keeps each file system on one line.
    size = f"df -kP {folder} | awk 'NR==2{{printf \"%d\", $4-$2*{keep}/100}}'"
    return f'fallocate -l "$({size})k" {path} && df -kP {folder} | tail -1'


def other_volume_works(storage_class):
    """Write and read 16 MiB on a second volume of the node."""
    out = run('other', 'head -c 16777216 /dev/urandom > /data/check && sync && sha256sum /data/check | cut -c1-64 && '
                       'echo 3 > /proc/sys/vm/drop_caches 2>/dev/null; sha256sum /data/check | cut -c1-64')
    lines = out.splitlines()
    return len(lines) == 2 and lines[0] == lines[1]


def main():
    global NODE, NODE_ADDRESS
    if len(sys.argv) != 3 or sys.argv[1] not in ('pvc', 'vg', 'containerd', 'oom'):
        raise SystemExit(__doc__)
    check, NODE = sys.argv[1:]
    NODE_ADDRESS = kubectl('get', 'node', NODE, '-o', 'jsonpath={.status.addresses[?(@.type=="InternalIP")].address}')
    tier = zonestate.node_tiers(NODE, settings.KUBECONFIG)[0]
    kubectl('create', 'namespace', NS)
    ok = True
    try:
        claim('other', '1Gi', f'{tier}-ext4')
        pod('other', NODE, 'sleep 3600', 'other')
        wait_running('other')
        if check == 'pvc':
            claim('full', '1Gi', f'{tier}-ext4')
            pod('full', NODE, 'sleep 3600', 'full')
            wait_running('full')
            run('full', fill_command('/data', '/data/fill', 3))
            names = ['VolumeAlmostFull']
        elif check == 'vg':
            capacity = int(kubectl('get', 'node', NODE, '-o', f'jsonpath={{.metadata.annotations.capacity\\.topolvm\\.io/{tier}}}'))
            size = capacity - 512 * 1024 ** 2
            claim('full', str(size), f'{tier}-block', block=True)
            pod('full', NODE, 'sleep 3600', 'full', block=True)
            wait_running('full')
            report(check=check, step='fill', bytes=size, left=capacity - size)
            names = ['VolumeGroupAlmostFull']
        elif check == 'containerd':
            pod('full', NODE, 'sleep 3600', privileged=True)
            wait_running('full')
            out = run('full', fill_command('/var/lib/rancher', FILL, 17))
            report(check=check, step='fill', df=out)
            names = ['ContainerVolumeAlmostFull']
        else:
            # tail keeps the bytes of a file without line ends, so it grows until the memory limit stops it.
            pod('full', NODE, 'tail /dev/zero', memory='32Mi', restart='Always')
            names = ['ContainerOutOfMemory', 'PodRestarts']
        seconds = alert(names)
        works = other_volume_works(tier)
        report(check=check, node=NODE, alarms=names, fired_after_seconds=seconds, other_volume_works=works)
        ok = seconds is not None and works
    finally:
        if check == 'containerd':
            kubectl('-n', NS, 'exec', 'full', '--', 'rm', '-f', FILL, check=False)
        kubectl('delete', 'namespace', NS, '--wait=true')
        report(check=check, step='cleanup', namespace_deleted=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
