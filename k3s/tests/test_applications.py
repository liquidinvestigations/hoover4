"""The application profile of a zone (../zones/applications.py): the render of a new zone and of a zone with the
application switches of an earlier version, the operator settings, the waves and the restore of an older copy."""
import json
import sys
from pathlib import Path

import pytest

from conftest import K3S

sys.path.insert(0, str(K3S / 'zones'))
sys.path.insert(0, str(K3S / 'platform' / 'backups'))
import applications  # noqa: E402
import zone  # noqa: E402
import zones  # noqa: E402

RETIRED_HOSTS = ('pad', 'chat', 'matrix', 'mas', 'element-admin', 'projects', 'notes', 'mrtc', 'sfu')
# The application switches of an earlier version, all on, as an operator revision saved them.
LEGACY_SWITCHES = {f'app.{name}': 'true' for name in ('nextcloud', 'collabora', 'cryptpad', 'element', 'jitsi',
                                                     'openproject', 'xwiki', 'notes', 'hoover')}


def operator_settings():
    import importlib.util
    spec = importlib.util.spec_from_file_location('operator_settings_p99', K3S / 'platform/operator/settings.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def render(monkeypatch):
    monkeypatch.setattr(zones, 'reduced_resources', lambda: {})
    monkeypatch.setattr(zones, 'ai_values', lambda: {})
    monkeypatch.setattr(zones, 'local_ca', lambda: {})
    monkeypatch.setattr(zones.settings, 'zone_host', lambda z, app: f'{z}-{app}.test')
    data = {'zone-a': {'master_password': 'm', 'turn_secret': 't', 'objectstore_key': {'access_key': 'GK1', 'secret_key': 's'},
                       'postgresql': {k: 'p' for k in zones.postgresql.DATABASES}},
            'calls': {'jvb_password': 'j', 'livekit_secret': 'l', 'livekit_turn_secret': 'lt'}}
    return lambda entry: zones.zone_values('zone-a', data, 'ssd-ext4', entry)


NEW_ZONE = {'enabled': True, 'stores': 'site', 'temporal': 'site', 'manticore': 'site', 'objectstore': 'garage',
            'postgresql': 'site', 'bootstrapped': False}
# A zone entry of an earlier version: bootstrapped, with the layouts before the moves.
LEGACY_ZONE = {'enabled': True, 'home': 'dev', 'bootstrapped': True}


@pytest.mark.parametrize('entry', [NEW_ZONE, LEGACY_ZONE], ids=['new', 'legacy'])
def test_a_zone_renders_nextcloud_office_and_no_retired_application(render, entry):
    values = render(entry)
    apps = values['apps']
    assert all(apps[name] == {'enabled': True} for name in ('nextcloud', 'collabora', 'jitsi', 'xwiki', 'nubus'))
    assert all(apps[name] == {'enabled': False} for name in ('notes', 'element', 'elementAdmin', 'neoboard', 'openproject',
                                                            'cryptpad'))
    text = json.dumps(values)
    # No customization file, timeout, secret or bucket of a retired application.
    assert not {'opendeskElement', 'openproject', 'notes'} & set(values['customization']['release'])
    assert 'matrixRTC' not in values['secrets'] and 'livekit' not in text.lower()
    assert set(values['deployment']['timeouts']['releases']) == {'opendeskNextcloudManagement', 'xwiki'}
    assert not set(values.get('objectstores', {})) & set(applications.RETIRED_BUCKETS)
    assert not set(values.get('databases', {})) & set(applications.RETIRED_DATABASES)


def test_the_frontend_routes_no_host_of_a_retired_application():
    assert not set(zones.HOSTS) & set(RETIRED_HOSTS)
    assert {'files', 'office', 'wiki', 'meet', 'hoover', 'portal', 'id', 'auth'} <= set(zones.HOSTS)
    sync = (K3S / 'platform/frontend/frontend-sync.sh').read_text()
    assert '_matrix' not in sync and '_synapse' not in sync and 'sfu' not in sync


def test_a_saved_switch_cannot_turn_a_retired_application_on():
    module = operator_settings()
    assert set(module.APPLICATIONS) == {'nextcloud', 'collabora', 'jitsi', 'xwiki', 'hoover'}
    values = module.effective('zone:zone-a', LEGACY_SWITCHES)
    assert not any(f'app.{name}' in values for name in applications.RETIRED_APPLICATIONS)
    assert values['app.collabora'] == 'true'
    with pytest.raises(module.SettingsError, match='retired'):
        module.check_values('zone:zone-a', {'app.openproject': 'true'})


def test_the_post_renderer_renders_the_retained_workloads_and_refuses_a_retired_one(monkeypatch):
    import postrender

    class Zone:
        def __init__(self, namespace):
            self.namespace, self.name, self.disabled = namespace, namespace, False

        def storage_class(self, store, mode):
            return f'ssd-{mode}'
    monkeypatch.setattr(postrender, 'Zone', Zone)
    # The legacy switches are saved, and the profile drops the retired ones (operator settings effective()).
    monkeypatch.setattr(postrender, 'operator_values', lambda z: operator_settings().effective(f'zone:{z}', LEGACY_SWITCHES))

    def deployment(name, container='c'):
        return {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': name},
                'spec': {'replicas': 1, 'template': {'metadata': {}, 'spec': {'containers': [{'name': container, 'image': 'i'}]}}}}
    out = postrender.overlay([deployment('collabora', 'collabora-online'), deployment('opendesk-nextcloud-aio', 'aio')], 'zone-a')
    assert [d['spec']['replicas'] for d in out] == [1, 1]
    for name in ('openproject-web', 'element-synapse-main', 'impress-backend', 'cryptpad', 'opendesk-matrix-user-verification-service'):
        with pytest.raises(RuntimeError, match='retired application'):
            postrender.overlay([deployment(name)], 'zone-a')
    job = {'apiVersion': 'batch/v1', 'kind': 'Job', 'metadata': {'name': 'impress-backend-init'}, 'spec': {}}
    with pytest.raises(RuntimeError, match='retired application'):
        postrender.overlay([job], 'zone-a')


def test_the_post_renderer_leaves_the_retired_secrets_of_the_secrets_release_out(monkeypatch):
    import postrender
    monkeypatch.setattr(postrender, 'Zone', lambda namespace: type('Z', (), {'disabled': False})())
    monkeypatch.setattr(postrender, 'operator_values', lambda z: {})

    def secret(name, release='opendesk-secrets'):
        return {'apiVersion': 'v1', 'kind': 'Secret',
                'metadata': {'name': name, 'labels': {'app.kubernetes.io/instance': release}}}
    names = ['matrix-rtc-livekit-auth-secret', 'database-notes-password', 'keycloak-client-secret-openproject',
             'synapse-signing-key', 'element-auditbot-password', 'cache-matrix-rtc-password',
             'matrix-intercom-synapse-as-token', 'database-xwiki-password', 'turn-shared-secret',
             'keycloak-client-secret-ncoidc', 'jitsi-jvb-auth']
    out = postrender.overlay([secret(n) for n in names] + [secret('notes-x', release='other')], 'zone-a')
    assert [d['metadata']['name'] for d in out] == ['matrix-intercom-synapse-as-token', 'database-xwiki-password',
                                                   'turn-shared-secret', 'keycloak-client-secret-ncoidc',
                                                   'jitsi-jvb-auth', 'notes-x']


def test_every_entry_release_and_image_of_the_pinned_release_has_a_class():
    if not (zone.OPENDESK / 'helmfile-defaults.yaml.gotmpl').exists():
        pytest.skip('the openDesk release is not unpacked in this checkout')
    assert applications.problems(zone.OPENDESK, zone.entry_releases) == []


def test_an_unclassified_entry_release_or_image_is_named(tmp_path):
    (tmp_path / 'helmfile/environments/default').mkdir(parents=True)
    (tmp_path / 'helmfile-defaults.yaml.gotmpl').write_text(
        'helmfiles:\n  - path: "helmfile/apps/nextcloud/helmfile-defaults.yaml.gotmpl"\n'
        '  - path: "helmfile/apps/newapp/helmfile-defaults.yaml.gotmpl"\n')
    (tmp_path / 'helmfile/environments/default/images.yaml.gotmpl').write_text(
        'images:\n  nextcloud:\n    registry: "r"\n    repository: "a/nextcloud"\n    tag: "1"\n'
        '  newImage:\n    registry: "r"\n    repository: "a/new"\n    tag: "1"\n')
    releases = {'nextcloud': ['opendesk-nextcloud', 'opendesk-nextcloud-whiteboard']}
    found = applications.problems(tmp_path, lambda entry: releases.get(entry, []))
    assert any('entry newapp' in p for p in found)
    assert any('release opendesk-nextcloud-whiteboard' in p for p in found)
    assert any('image newImage' in p for p in found)
    assert len(found) == 3


@pytest.mark.parametrize('installed,expected', [({}, []), ({'openproject': 'deployed'}, ['sync'])])
def test_a_retired_entry_runs_only_to_uninstall_its_releases(monkeypatch, installed, expected):
    ran = []
    monkeypatch.setattr(zone, 'helm_releases', lambda z: installed)
    monkeypatch.setattr(zone, 'entry_releases', lambda entry: ['openproject'])
    monkeypatch.setattr(zone, 'run_entry', lambda z, entry, command: ran.append(command) or (0, ''))
    monkeypatch.setattr(zone, 'step', lambda *a, **kw: None)
    zone.install_entry('zone-a', 'openproject')
    # helmfile apply also removes a release that the values mark as not installed.
    assert [c in ('sync', 'apply') for c in ran] == [True] * len(expected)


def test_the_retained_entries_run_as_before(monkeypatch):
    ran = []
    monkeypatch.setattr(zone, 'helm_releases', lambda z: {})
    monkeypatch.setattr(zone, 'entry_releases', lambda entry: ['xwiki'])
    monkeypatch.setattr(zone, 'run_entry', lambda z, entry, command: ran.append(command) or (0, ''))
    monkeypatch.setattr(zone, 'step', lambda *a, **kw: None)
    zone.install_entry('zone-a', 'xwiki')
    assert ran == ['sync']


def test_the_profile_is_an_input_of_the_zone_and_of_the_prepull():
    assert 'zones/applications.py' in zone.INPUT_SOURCES
    assert 'applications' in (K3S / 'driver/deploy.py').read_text()


def test_the_prepull_leaves_out_the_images_of_a_retired_application():
    sys.path.insert(0, str(K3S / 'images'))
    import prepull
    pods = [{'spec': {'containers': [{'image': 'docker.io/livekit/livekit-server:v1.9.0'},
                                     {'image': 'registry.opencode.de/bmi/opendesk/components/supplier/element/images-mirror/synapse:1'},
                                     {'image': 'docker.io/library/busybox:1.37.0-musl'}]}}]
    assert prepull.pod_images(pods) == {'docker.io/library/busybox:1.37.0-musl'}
