"""The cluster copy of the state (k3s/clusterstate.py) and the Lease of the site lock (k3s/oplock.py).

A store in memory with resourceVersions stands in for the API server. The Lease tests replace the kubectl call of the
lock with a fake Lease object. No test contacts a cluster.
"""
import json
import subprocess
import sys

import pytest

from conftest import K3S

sys.path.insert(0, str(K3S))
import clusterstate  # noqa: E402
import oplock  # noqa: E402


class Store:
    """The objects of the cluster copy, with the conflict rules of the API server."""

    def __init__(self):
        self.objects = {}
        self.counter = 0

    def list(self, kind):
        return {p: dict(o) for (k, p), o in self.objects.items() if k == kind}

    def put(self, kind, path, data, version=None):
        current = self.objects.get((kind, path))
        if version is None and current is not None:
            raise clusterstate.Conflict(f'{path} already exists')
        if version is not None and (current is None or current['version'] != version):
            raise clusterstate.Conflict(f'{path}: the object has been modified')
        self.counter += 1
        self.objects[(kind, path)] = {'name': clusterstate.object_name(path), 'version': str(self.counter), 'data': data}
        return str(self.counter)

    def delete(self, kind, path):
        self.objects.pop((kind, path), None)


def write(folder, path, text):
    target = folder / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def test_a_first_push_copies_the_state_and_leaves_the_local_files(tmp_path):
    store = Store()
    write(tmp_path, 'zone-state.json', '{"zones": {}}')
    write(tmp_path, 'operator/desired.json', '{"revision": 1}')
    write(tmp_path, 'operator/deploy/records/1.json', '{}')
    write(tmp_path, 'operator/state.lock', '')
    write(tmp_path, 'operator/site-operation.json', '{}')
    write(tmp_path, 'zones/zone-a/master-password', 'secret')
    write(tmp_path, 'kubeconfig', 'admin')
    write(tmp_path, 'facts/node-a.json', '{}')
    changes = clusterstate.push(tmp_path, store=store)
    assert set(changes) == {'zone-state.json', 'operator/desired.json', 'zones/zone-a/master-password', 'facts/node-a.json'}
    assert store.objects[('secret', 'zones/zone-a/master-password')]['data'] == b'secret'
    assert ('configmap', 'kubeconfig') not in store.objects
    assert clusterstate.push(tmp_path, store=store) == {}


def test_a_new_folder_gets_the_cluster_copy_and_a_cluster_change_replaces_an_unchanged_file(tmp_path):
    store = Store()
    source, pod = tmp_path / 'workstation', tmp_path / 'pod'
    write(source, 'zone-state.json', 'one')
    write(source, 'zones/secrets.json', 's1')
    clusterstate.push(source, store=store)
    assert clusterstate.pull(pod, store=store) == {'zone-state.json': 'written', 'zones/secrets.json': 'written'}
    assert (pod / 'zones/secrets.json').stat().st_mode & 0o777 == 0o600
    write(source, 'zone-state.json', 'two')
    clusterstate.push(source, store=store)
    assert clusterstate.pull(pod, store=store) == {'zone-state.json': 'written'}
    assert (pod / 'zone-state.json').read_text() == 'two'


def test_a_change_in_two_folders_is_a_conflict_and_no_write_is_lost(tmp_path):
    store = Store()
    a, b = tmp_path / 'a', tmp_path / 'b'
    write(a, 'operator/applied.json', 'base')
    clusterstate.push(a, store=store)
    clusterstate.pull(b, store=store)
    write(a, 'operator/applied.json', 'from a')
    write(b, 'operator/applied.json', 'from b')
    clusterstate.push(a, store=store)
    with pytest.raises(clusterstate.Conflict):
        clusterstate.push(b, store=store)
    with pytest.raises(clusterstate.Conflict):
        clusterstate.pull(b, store=store)
    assert store.objects[('configmap', 'operator/applied.json')]['data'] == b'from a'
    assert (b / 'operator/applied.json').read_text() == 'from b'


def test_a_change_of_another_file_does_not_block_a_push(tmp_path):
    store = Store()
    a, b = tmp_path / 'a', tmp_path / 'b'
    write(a, 'operator/desired.json', '1')
    write(a, 'operator/applied.json', '0')
    clusterstate.push(a, store=store)
    clusterstate.pull(b, store=store)
    write(a, 'operator/desired.json', '2')
    write(b, 'operator/applied.json', '1')
    clusterstate.push(a, store=store)
    clusterstate.push(b, store=store)
    clusterstate.pull(b, store=store)
    assert (b / 'operator/desired.json').read_text() == '2'
    assert store.objects[('configmap', 'operator/applied.json')]['data'] == b'1'


def test_a_delete_goes_to_the_cluster_and_to_the_other_folder(tmp_path):
    store = Store()
    a, b = tmp_path / 'a', tmp_path / 'b'
    write(a, 'zones/zone-a/values.yaml', 'v')
    clusterstate.push(a, store=store)
    clusterstate.pull(b, store=store)
    (a / 'zones/zone-a/values.yaml').unlink()
    assert clusterstate.push(a, store=store) == {'zones/zone-a/values.yaml': 'deleted'}
    assert clusterstate.pull(b, store=store) == {'zones/zone-a/values.yaml': 'deleted'}
    assert not (b / 'zones/zone-a/values.yaml').exists()


def test_a_large_log_keeps_its_last_lines_in_the_cluster(tmp_path):
    store = Store()
    lines = ''.join(f'line {i}\n' for i in range(60000))
    write(tmp_path, 'operations/op-1.log', lines)
    clusterstate.push(tmp_path, store=store)
    data = store.objects[('configmap', 'operations/op-1.log')]['data']
    assert len(data) <= clusterstate.LOG_LIMIT and data.endswith(b'line 59999\n') and data.startswith(b'line ')
    assert clusterstate.push(tmp_path, store=store) == {}
    assert clusterstate.pull(tmp_path, store=store) == {}


def test_the_objects_name_their_path_and_keep_secrets_out_of_configmaps():
    kube = clusterstate.Kubectl('/nonexistent')
    secret = kube.body('secret', 'zones/zone-a/master-password', b'pw')
    assert secret['kind'] == 'Secret' and secret['data'] == {'content': 'cHc='}
    assert secret['metadata']['annotations'] == {clusterstate.PATH_ANNOTATION: 'zones/zone-a/master-password'}
    config = kube.body('configmap', 'operator/desired.json', b'{}', version='7')
    assert config['data'] == {'content': '{}'} and config['metadata']['resourceVersion'] == '7'
    assert kube.body('configmap', 'facts/x.json', b'\xff')['binaryData'] == {'content': '/w=='}


def test_checkpoint_pushes_only_with_the_environment_variable(tmp_path, monkeypatch):
    monkeypatch.delenv(clusterstate.ENV, raising=False)
    write(tmp_path, 'zone-state.json', 'x')
    assert clusterstate.checkpoint(tmp_path) == {}


# The Lease of the site lock ---------------------------------------------------------------------------------------

class FakeLease:
    """kubectl get, create and replace of one Lease, with resourceVersions."""

    def __init__(self):
        self.lease = None
        self.version = 0

    def __call__(self, *args, data=None):
        verb = args[0]
        if verb == 'get':
            if self.lease is None:
                return subprocess.CompletedProcess(args, 1, '', 'Error from server (NotFound): leases not found')
            return subprocess.CompletedProcess(args, 0, json.dumps(self.lease), '')
        body = json.loads(data)
        if verb == 'create' and self.lease is not None:
            return subprocess.CompletedProcess(args, 1, '', 'AlreadyExists')
        if verb == 'replace' and body['metadata'].get('resourceVersion') != self.lease['metadata']['resourceVersion']:
            return subprocess.CompletedProcess(args, 1, '', 'the object has been modified')
        self.version += 1
        body['metadata']['resourceVersion'] = str(self.version)
        self.lease = body
        return subprocess.CompletedProcess(args, 0, '', '')


def lease_lock(fake):
    lock = oplock.LeaseLock('/nonexistent')
    lock.kubectl = fake
    return lock


def test_the_lease_admits_one_holder_and_names_it(monkeypatch):
    monkeypatch.delenv(oplock.ENV, raising=False)
    fake = FakeLease()
    first = lease_lock(fake)
    first.acquire('up', 'up-1')
    monkeypatch.delenv(oplock.ENV)
    with pytest.raises(oplock.Busy, match='the site operation up up-1'):
        lease_lock(fake).acquire('zone-operation', 'op-1')
    assert lease_lock(fake).busy()['id'] == 'up-1'
    first.release()
    assert lease_lock(fake).busy() is None
    assert lease_lock(fake).holder()['state'] == 'released'
    second = lease_lock(fake)
    assert second.acquire('zone-operation', 'op-1')['id'] == 'op-1'
    second.release()


def test_an_expired_lease_is_free_and_the_next_holder_records_it(monkeypatch):
    monkeypatch.delenv(oplock.ENV, raising=False)
    fake = FakeLease()
    first = lease_lock(fake)
    first.acquire('backup', 'backup-1')
    first.stop.set()
    monkeypatch.delenv(oplock.ENV)
    fake.lease['spec']['renewTime'] = '2020-01-01T00:00:00.000000Z'
    second = lease_lock(fake)
    owner = second.acquire('up', 'up-2')
    assert owner['recovered']['id'] == 'backup-1'
    second.release()
    first.renewer.join(timeout=5)


def test_a_child_of_the_holder_runs_inside_its_operation(monkeypatch):
    monkeypatch.delenv(oplock.ENV, raising=False)
    fake = FakeLease()
    holder = lease_lock(fake)
    holder.acquire('up', 'up-3')
    child = lease_lock(fake)
    monkeypatch.setattr(oplock.os, 'getpid', lambda: -1)
    assert child.acquire('zone', 'x')['id'] == 'up-3' and child.inherited
    child.release()
    assert fake.lease['spec']['holderIdentity'] == 'up-3'
    monkeypatch.undo()
    holder.release()


def test_site_lock_is_the_file_lock_without_a_cluster(tmp_path):
    assert isinstance(oplock.site_lock(tmp_path / 'operator', tmp_path / 'missing-kubeconfig'), oplock.SiteLock)
