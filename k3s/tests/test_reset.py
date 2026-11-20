"""deploy-k3s reset (../driver/reset.py): the reset marker of the site lock, the zone definitions, the image
classification, the plan and the refusal of a stale resume. The tests change no host and no cluster."""
import json
import subprocess
import sys

import pytest

from conftest import K3S

sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'driver'))
sys.path.insert(0, str(K3S / 'images'))
import oplock  # noqa: E402
import reclaim  # noqa: E402
import reset  # noqa: E402
from test_clusterstate import FakeLease, lease_lock  # noqa: E402


class PatchedLease(FakeLease):
    """FakeLease with kubectl patch --type merge of the annotations."""

    def __call__(self, *args, data=None):
        if args[0] != 'patch':
            return super().__call__(*args, data=data)
        patch = json.loads(args[-1])
        if patch['metadata']['resourceVersion'] != self.lease['metadata']['resourceVersion']:
            return subprocess.CompletedProcess(args, 1, '', 'the object has been modified')
        annotations = self.lease['metadata'].setdefault('annotations', {})
        for key, value in patch['metadata']['annotations'].items():
            if value is None:
                annotations.pop(key, None)
            else:
                annotations[key] = value
        self.version += 1
        self.lease['metadata']['resourceVersion'] = str(self.version)
        return subprocess.CompletedProcess(args, 0, '', '')


@pytest.mark.parametrize('kind', ['up', 'down', 'apply', 'zone-operation', 'backup', 'restore', 'import'])
def test_an_incomplete_reset_refuses_every_other_operation_on_the_lease(monkeypatch, kind):
    monkeypatch.delenv(oplock.ENV, raising=False)
    fake = PatchedLease()
    holder = lease_lock(fake)
    holder.acquire('reset', 'reset-1')
    holder.set_reset({'record': 'R1', 'started': 't'})
    holder.release()
    # The marker stays after the release of the reset.
    assert lease_lock(fake).reset_marker()['record'] == 'R1'
    with pytest.raises(oplock.Busy, match='reset --resume R1'):
        lease_lock(fake).acquire(kind, f'{kind}-1')
    resumed = lease_lock(fake)
    resumed.acquire('reset', 'reset-2')
    # The renewal of the holder keeps the marker.
    resumed.write(resumed.lease(), resumed.owner)
    assert resumed.reset_marker()['record'] == 'R1'
    resumed.set_reset(None)
    resumed.release()
    monkeypatch.delenv(oplock.ENV, raising=False)
    other = lease_lock(fake)
    assert other.acquire(kind, f'{kind}-2')['id'] == f'{kind}-2'
    other.release()


def test_an_incomplete_reset_refuses_every_other_operation_on_the_file_lock(tmp_path, monkeypatch):
    monkeypatch.delenv(oplock.ENV, raising=False)
    lock = oplock.SiteLock(tmp_path)
    lock.acquire('reset', 'reset-1')
    lock.set_reset({'record': 'R1'})
    lock.release()
    with pytest.raises(oplock.Busy, match='reset --resume R1'):
        oplock.SiteLock(tmp_path).acquire('up', 'up-1')
    again = oplock.SiteLock(tmp_path)
    again.acquire('reset', 'reset-2')
    again.set_reset(None)
    again.release()
    up = oplock.SiteLock(tmp_path)
    assert up.acquire('up', 'up-2')['id'] == 'up-2'
    up.release()


class Ctx:
    def __init__(self, tmp_path):
        self.private = tmp_path
        self.state = tmp_path / 'operator'
        self.state.mkdir(exist_ok=True)


def test_the_definitions_keep_the_intended_zones_without_their_state(tmp_path):
    ctx = Ctx(tmp_path)
    (tmp_path / 'zone-state.json').write_text(json.dumps({'schemaVersion': 1, 'zones': {
        'zone-a': {'enabled': True, 'namespaces': ['zone-a', 'hoover-zone-a'], 'bootstrapped': True, 'stores': 'site',
                   'temporal': 'site', 'manticore': 'site', 'objectstore': 'garage', 'postgresql': 'site'},
        'zone-b': {'enabled': False, 'stores': 'local', 'extra_datasets': 'archive:node-b:/srv/archive',
                   'tiers': {'default': ['hdd']}, 'bootstrapped': True}}}))
    defined = reset.keep_definitions(ctx)
    assert defined == {'zone-a': {'enabled': True, 'stores': 'site'},
                       'zone-b': {'enabled': False, 'stores': 'local', 'extra_datasets': 'archive:node-b:/srv/archive',
                                  'tiers': {'default': ['hdd']}}}
    # An existing definition stays as the operator wrote it.
    data = json.loads((tmp_path / 'zone-definitions.json').read_text())
    data['zones']['zone-a']['tiers'] = {'default': ['ssd']}
    (tmp_path / 'zone-definitions.json').write_text(json.dumps(data))
    assert reset.keep_definitions(ctx)['zone-a'] == {'enabled': True, 'stores': 'site', 'tiers': {'default': ['ssd']}}
    text = (tmp_path / 'zone-definitions.json').read_text()
    assert 'bootstrapped' not in text and 'objectstore' not in text


def test_the_up_plan_creates_each_defined_zone_that_the_zone_state_lacks(tmp_path):
    import config
    import deploy
    ctx = deploy.Context(K3S / 'tests/fixtures/remote.yml', config.read(K3S / 'tests/fixtures/remote.yml'), private=tmp_path)
    (tmp_path / 'zone-state.json').write_text(json.dumps({'schemaVersion': 1, 'zones': {
        'zone-a': {'enabled': True, 'namespaces': ['zone-a', 'hoover-zone-a'], 'stores': 'site', 'temporal': 'site',
                   'manticore': 'site'}}}))
    (tmp_path / 'zone-definitions.json').write_text(json.dumps({'schemaVersion': 1, 'zones': {
        'zone-a': {'enabled': True, 'stores': 'site'}, 'zone-c': {'enabled': True, 'stores': 'site'}}}))
    assert ctx.zone_names() == ['zone-a', 'zone-c']
    steps = deploy.cluster_steps(ctx)
    assert 'zone:zone-a' in steps and 'zone:zone-c' in steps


def test_the_reset_plan_runs_its_steps_in_order(monkeypatch):
    steps = list(reset.plan(None, ['zone-a', 'zone-b']))
    assert steps == ['reset:inventory', 'reset:suspend', 'reset:zone:zone-a', 'reset:zone:zone-b', 'reset:storage',
                     'reset:data', 'reset:backups', 'reset:state', 'reset:images', 'reset:verify']
    import deploy
    needs = deploy.prerequisites(steps)
    assert needs['reset:storage'] == steps[:4]


def test_a_node_error_fails_the_step_with_its_message():
    def broken(ctx):
        raise reset.nodepod.Unreachable('the node muc did not start the command pod in 180 s')
    with pytest.raises(reset.Incomplete, match='muc did not start'):
        reset.checked(broken)(None)


class Lock:
    def __init__(self, marker=None):
        self.marker = marker

    def reset_marker(self):
        return self.marker


def test_a_stale_reset_record_is_refused(tmp_path):
    ctx = Ctx(tmp_path)
    record = {'id': 'R1', 'generation': 1, 'status': 'interrupted'}
    assert reset.refuse_resume(ctx, record, Lock({'record': 'R1'})) is None
    assert 'replaced' in reset.refuse_resume(ctx, record, Lock({'record': 'R2'}))
    assert 'complete' in reset.refuse_resume(ctx, dict(record, status='done'), Lock())
    reset.save_installation(ctx, {'generation': 2, 'resets': []})
    assert 'generation 1' in reset.refuse_resume(ctx, record, Lock({'record': 'R1'}))


def test_the_end_raises_the_generation_and_removes_the_marker(tmp_path):
    ctx = Ctx(tmp_path)
    cleared = []

    class Holder(Lock):
        def set_reset(self, marker):
            cleared.append(marker)
    reset.finish(ctx, {'id': 'R1', 'generation': 1, 'inventory': {'zones': ['zone-a']}}, Holder())
    assert reset.installation(ctx)['generation'] == 2 and cleared == [None]
    assert reset.installation(ctx)['resets'][-1]['zones'] == ['zone-a']


IMAGES = [
    # A retired image of the pinned release, cached without a pod.
    {'id': 'sha256:a1', 'repoTags': [], 'repoDigests': ['registry.example/supplier/element/images-mirror/synapse@sha256:1'], 'size': '100'},
    # A retired image of an earlier release.
    {'id': 'sha256:a2', 'repoTags': ['docker.io/livekit/livekit-server:v1'], 'repoDigests': [], 'size': '50'},
    # A digest that a retired and a retained reference share.
    {'id': 'sha256:a3', 'repoTags': [], 'repoDigests': ['registry.example/images-mirror/matrix-tools@sha256:3',
                                                        'registry.example/nordeck/images-mirror/busybox@sha256:3'], 'size': '5'},
    # A retained image.
    {'id': 'sha256:a4', 'repoTags': ['registry.example/collabora/code:1'], 'repoDigests': [], 'size': '900'},
    # A retired image that a container still uses.
    {'id': 'sha256:a5', 'repoTags': ['registry.example/supplier/openproject/images-mirror/open_desk:16'], 'repoDigests': [],
     'size': '400'},
]


def test_the_images_split_into_removals_aliases_and_images_in_use():
    retained = {'registry.example/nordeck/images-mirror/busybox', 'registry.example/collabora/code'}
    found = reclaim.classify(IMAGES, {'sha256:a5'}, set(), retained)
    assert [i['id'] for i in found['remove']] == ['sha256:a1', 'sha256:a2']
    assert found['aliases'] == [{'id': 'sha256:a3', 'retired': ['registry.example/images-mirror/matrix-tools@sha256:3'],
                                 'kept': ['registry.example/nordeck/images-mirror/busybox@sha256:3']}]
    assert [i['id'] for i in found['in_use']] == ['sha256:a5'] and found['kept'] == 1
    script = reclaim.remove_script(found)
    assert 'k3s crictl rmi sha256:a1' in script and 'k3s crictl rmi sha256:a2' in script
    # The shared digest loses only its retired reference.
    assert 'k3s ctr -n k8s.io images rm registry.example/images-mirror/matrix-tools@sha256:3 ' in script
    assert 'rmi sha256:a3' not in script
    assert 'a4' not in script and 'a5' not in script


def test_the_pods_of_retired_workloads_name_retired_repositories():
    pods = [{'metadata': {'name': 'livekit-abc', 'ownerReferences': [{'name': 'livekit-5d8'}]},
             'spec': {'containers': [{'image': 'example.org/livekit-fork:1'}]}},
            {'metadata': {'name': 'element-synapse-main-0'}, 'spec': {'containers': [{'image': 'example.org/synapse:1'}]}},
            {'metadata': {'name': 'jvb-0'}, 'spec': {'containers': [{'image': 'example.org/jvb:1'}]}}]
    retired, retained = reclaim.pod_repositories(pods)
    assert retired == {'example.org/synapse'} and 'example.org/jvb' in retained
    assert reclaim.repository('a.b/c/d:1@sha256:x') == 'a.b/c/d' and reclaim.repository('host:5000/a/b') == 'host:5000/a/b'


def test_a_node_reports_its_inventory():
    text = (json.dumps({'images': IMAGES[:2]}) + reclaim.SPLIT + json.dumps({'containers': [{'imageRef': 'sha256:a2'}]})
            + reclaim.SPLIT + '1000\n' + reclaim.SPLIT + '700\n')
    images, used, used_bytes, content = reclaim.parse_node(text)
    assert len(images) == 2 and 'sha256:a2' in used and (used_bytes, content) == (1000, 700)


def test_the_registry_names_only_retired_repositories():
    assert reclaim.registry_repositories(['hoover/hoover-website', 'hoover/nextcloud-ai', 'mirror/livekit/livekit-server'],
                                         set()) == []
    assert reclaim.registry_repositories(['livekit/livekit-server', 'hoover/operator'], set()) == ['livekit/livekit-server']
