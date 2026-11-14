#!/usr/bin/env python3
"""Verify installer retries and check failures locally, without cluster access."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'zones'))
import zone
import postrender
import gate
sys.path.insert(0, str(SOURCE / 'hoover' / 'stores'))
import podspec


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, SOURCE / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load('store_smoke', 'tools/store-checks/smoke.py')
storage = load('storage_checks', 'tools/storage-checks.py')
images = load('image_checks', 'tools/image-start-check.py')
snapshot = load('zone_snapshot', 'tools/zone-snapshot.py')


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.controller = {'metadata': {'uid': 'owner', 'generation': 2},
                           'spec': {'replicas': 1, 'updateStrategy': {'type': 'RollingUpdate'}},
                           'status': {'observedGeneration': 2, 'updateRevision': 'new'}}
        self.pod = {'metadata': {'name': 'store-0', 'labels': {'controller-revision-hash': 'old'},
                                 'ownerReferences': [{'uid': 'owner', 'controller': True}]},
                    'status': {'conditions': [{'type': 'Ready', 'status': 'False'}]}}

    def test_old_failed_pod_is_replaced(self):
        self.assertEqual(zone.stale_pods(self.controller, [self.pod]), ['store-0'])

    def test_current_failed_pod_is_not_deleted_in_a_loop(self):
        self.pod['metadata']['labels']['controller-revision-hash'] = 'new'
        self.assertEqual(zone.stale_pods(self.controller, [self.pod]), [])

    def test_old_ready_pod_follows_update_strategy(self):
        self.pod['status']['conditions'][0]['status'] = 'True'
        self.assertEqual(zone.stale_pods(self.controller, [self.pod]), [])
        self.controller['spec']['updateStrategy']['type'] = 'OnDelete'
        self.assertEqual(zone.stale_pods(self.controller, [self.pod]), ['store-0'])

    def test_stopped_or_unobserved_controller_is_unchanged(self):
        self.controller['spec']['replicas'] = 0
        self.assertEqual(zone.stale_pods(self.controller, [self.pod]), [])
        self.controller['spec']['replicas'] = 1
        self.controller['status']['observedGeneration'] = 1
        self.assertEqual(zone.stale_pods(self.controller, [self.pod]), [])

    def test_other_owner_and_partition_are_preserved(self):
        self.pod['metadata']['ownerReferences'][0]['uid'] = 'another'
        self.assertEqual(zone.stale_pods(self.controller, [self.pod]), [])
        self.pod['metadata']['ownerReferences'][0]['uid'] = 'owner'
        self.controller['spec']['updateStrategy']['rollingUpdate'] = {'partition': 1}
        self.assertEqual(zone.stale_pods(self.controller, [self.pod]), [])

    def test_runc_exception_removes_explicit_runtime(self):
        doc = {'kind': 'StatefulSet', 'metadata': {'name': 'ums-umc-server'},
               'spec': {'template': {'metadata': {}, 'spec': {'runtimeClassName': 'kata', 'containers': []}}}}
        with patch.object(postrender, 'Zone') as state, patch.object(postrender, 'memory'), patch.object(postrender.cpu_policy, 'apply'):
            state.return_value.disabled = False
            result = postrender.overlay([doc], 'zone-test')[0]['spec']['template']
        self.assertNotIn('runtimeClassName', result['spec'])
        self.assertEqual(result['metadata']['labels']['hoover.dev/runtime'], 'runc')

    def test_revision_job_name_ignores_the_revision(self):
        def job(revision):
            name = f'ums-provisioning-register-consumers-{revision}'
            return {'kind': 'Job', 'metadata': {'name': name, 'labels': {'app.kubernetes.io/name': name}},
                    'spec': {'template': {'metadata': {'labels': {'app.kubernetes.io/name': name}}, 'spec': {'containers': []}}}}
        with patch.object(postrender, 'Zone') as state:
            state.return_value.disabled = False
            first, second = (postrender.overlay([job(n)], 'zone-test')[0] for n in (4, 5))
        self.assertEqual(first, second)
        name = first['metadata']['name']
        self.assertNotEqual(name, 'ums-provisioning-register-consumers-4')
        self.assertEqual(first['spec']['template']['metadata']['labels']['app.kubernetes.io/name'], name)

    def test_block_store_may_grow_its_file_system(self):
        # resize2fs of a mounted ext4 file system needs CAP_SYS_RESOURCE in the guest.
        spec = {'containers': [{'name': 'store', 'securityContext': {'capabilities': {'drop': ['ALL']}}}]}
        caps = podspec.blockmount(spec, 'store', ['start'], [('data', None, '/data')])['containers'][0]['securityContext']['capabilities']
        self.assertEqual(caps['add'], ['SYS_ADMIN', 'SYS_RESOURCE'])
        self.assertNotIn('drop', caps)

    def test_gate_cookie_names_its_zone(self):
        # The cookie domain is the site suffix, so the gate of another zone must read another cookie name.
        args = gate.objects('zone-test')['items'][0]['spec']['template']['spec']['containers'][0]['args']
        suffix = gate.settings.SUFFIX
        self.assertIn(f'--cookie-domain=.{suffix}', args)
        self.assertIn('--cookie-name=_hoover_gate_zone-test', args)
        self.assertIn('--cookie-secure=true', args)
        self.assertIn(f'--redirect-url=https://zone-test-auth.{suffix}/oauth2/callback', args)
        allowed = [a.split('=', 1)[1] for a in args if a.startswith('--whitelist-domain=')]
        self.assertIn(f'zone-test-hoover.{suffix}', allowed)
        self.assertTrue(all(h.startswith('zone-test-') or h == f'zone-test.{suffix}' for h in allowed), allowed)

    def test_zone_values_put_the_zone_id_in_front_of_each_host(self):
        import re
        import zones
        data = {'calls': {'jvb_password': 'j'}, 'zone-test': {'turn_secret': 't', 'livekit_secret': 'l'}}
        with patch.object(zones, 'reduced_resources', return_value={}), patch.object(zones, 'ai_values', return_value={}):
            values = zones.zone_values('zone-test', data, 'ssd-ext4')
        suffix = zones.SUFFIX
        self.assertEqual(values['global']['domain'], suffix)
        self.assertEqual(values['global']['hosts']['nubus'], 'zone-test-portal')
        self.assertTrue(all(h.startswith('zone-test-') for h in values['global']['hosts'].values()))
        self.assertEqual(set(values['global']['hosts']), set(zones.OPENDESK_HOSTS))
        # The Matrix IDs and the mail addresses keep the zone domain.
        self.assertEqual(values['global']['mailDomain'], f'zone-test.{suffix}')
        self.assertEqual(values['global']['matrixDomain'], f'zone-test.{suffix}')
        # The home chart would serve the site domain in every zone.
        self.assertEqual(values['apps']['home'], {'enabled': False})
        oidc = values['functional']['authentication']['oidc']['clients']
        self.assertEqual(oidc['opendesk-gate']['redirectUris'], [f'https://zone-test-auth.{suffix}/oauth2/callback'])
        self.assertEqual(oidc['opendesk-hoover']['redirectUris'], [f'https://zone-test-hoover.{suffix}/oauth2/callback'])
        self.assertIn(str(zones.out / 'zone-test' / 'intercom.yaml'), values['customization']['release']['intercomService'])
        origin = re.compile(zones.origin_regex('zone-test'))
        self.assertTrue(origin.search(f'https://zone-test-portal.{suffix}'))
        self.assertTrue(origin.search(f'zone-test-files.{suffix}'))
        for other in (f'https://zone-other-portal.{suffix}', f'https://zone-test-portal.{suffix}.example.net',
                      f'https://xzone-test-portal.{suffix}', f'https://zone-test.{suffix}'):
            self.assertFalse(origin.search(other), other)

    def test_frontend_sync_refuses_an_invalid_suffix(self):
        # The suffix goes into the regular expressions of the Caddyfile, so a value outside the domain pattern stops it.
        with tempfile.TemporaryDirectory() as folder:
            script = (SOURCE / 'platform/frontend/frontend-sync.sh').read_text().replace('here=${HOOVER_FRONTEND_DIR:-/opt/hoover-frontend}', f'here={folder}')
            for value in ('a b', 'x$(id)', '.example.org'):
                Path(folder, 'site.env').write_text(f'suffix={value!r}\ntls_mode=internal\n')
                result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, value)
                self.assertIn('invalid suffix', result.stderr)
            self.assertFalse(Path(folder, 'Caddyfile').exists())

    def test_snapshot_does_not_mutate_input(self):
        obj = {'kind': 'PersistentVolumeClaim', 'spec': {'volumeName': 'volume', 'resources': {}}, 'metadata': {}}
        before = copy.deepcopy(obj)
        self.assertNotIn('volumeName', snapshot.clean(obj)['spec'])
        self.assertEqual(obj, before)

    def test_disabled_apply_only_renders(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(zone, 'PRIVATE', Path(directory)), \
             patch.object(zone, 'register', return_value='test-node'), patch.object(zone, 'run'), \
             patch.object(zone.zonestate, 'enabled', return_value=False), \
             patch.object(zone, 'helmfile', return_value=subprocess.CompletedProcess([], 0, '# render\n', '')) as helm, \
             patch.object(zone, 'images') as build, patch.object(zone, 'cluster') as cluster, patch.object(zone, 'step'):
            zone.apply('zone-test', None)
            helm.assert_called_once_with('zone-test', 'template')
            build.assert_not_called()
            cluster.assert_not_called()
            self.assertEqual((Path(directory) / 'render/zone-test-disabled.yaml').stat().st_mode & 0o777, 0o600)


class CheckTests(unittest.TestCase):
    def test_store_results_require_success(self):
        good = {
            'redis': {'auth': '+OK', 'set_ok': 10000, 'hits': 10000},
            'memcached': {'hits': 10000},
            'nats': {'acks': 10000, 'stream_messages': 10000, 'streams_after': {}},
            'seaweedfs': dict.fromkeys(['put_ok', 'read_back_identical', 'delete_ok', 'other_bucket_list_refused'], True),
            'seaweedfs-load': {'identical': True, 'upload': [0, 1], 'download': [0, 1], 'delete': [0, 1]},
            'garage': {'round_trip': True, 'delete_ok': True, 'anonymous_list_refused': True,
                       'load': {'identical': True, 'upload': [0, 1], 'download': [0, 1], 'delete': [0, 1]}},
        }
        for store, result in good.items():
            with self.subTest(store=store):
                self.assertTrue(smoke.passed(store, result))
                self.assertFalse(smoke.passed(store, {}))
                for key in result:
                    bad = dict(result)
                    bad.pop(key)
                    self.assertFalse(smoke.passed(store, bad))

    def test_failed_store_pod_exits_nonzero(self):
        with patch.object(sys, 'argv', ['smoke.py', 'memcached', 'test', 'zone-test']), \
             patch.object(smoke.common, 'kubectl_json', return_value={'status': {'phase': 'Failed'}}), \
             patch.object(smoke.common, 'kubectl', return_value=json.dumps({'hits': 10000})), \
             patch.object(smoke.common, 'apply'), patch.object(smoke.common, 'log'):
            with self.assertRaises(SystemExit):
                smoke.main()

    def test_checksum_mismatch_fails_and_cleans_up(self):
        values = [('Succeeded', 'a' * 64 + '  /data/upload'),
                  ('Succeeded', 'b' * 64 + '  /data/upload'),
                  ('Succeeded', 'a' * 64 + '  /data/upload')]
        with patch.object(storage, 'kubectl') as command, patch.object(storage, 'claim', return_value={}), \
             patch.object(storage, 'finished', side_effect=values), patch.object(storage, 'report'):
            with self.assertRaises(SystemExit):
                storage.t8('test-node')
            self.assertEqual(command.call_args.args, ('delete', 'namespace', storage.NS, '--wait=true'))

    def test_image_failure_propagates(self):
        def command(*args, **kwargs):
            return 'Failed' if 'get' in args else ''
        with patch.object(sys, 'argv', ['image-start-check.py', 'zone-test', 'test-node']), \
             patch.object(images, 'CHECKS', [('test/image', 'kata', ['true'])]), \
             patch.object(images, 'images', return_value={'test/image:1'}), \
             patch.object(images, 'kubectl', side_effect=command) as call, patch('builtins.print'):
            with self.assertRaises(SystemExit):
                images.main()
            self.assertEqual(call.call_args.args, ('delete', 'namespace', images.NS, '--wait=false'))

    def test_image_status_is_read_after_deadline(self):
        def command(*args, **kwargs):
            return 'Succeeded' if 'get' in args else ''
        with patch.object(sys, 'argv', ['image-start-check.py', 'zone-test', 'test-node']), \
             patch.object(images, 'CHECKS', [('test/image', 'kata', ['true']), ('test/other', 'kata', ['true'])]), \
             patch.object(images, 'images', return_value={'test/image:1', 'test/other:1'}), \
             patch.object(images, 'kubectl', side_effect=command) as call, \
             patch.object(images.time, 'time', side_effect=[0, 1000, 1000]), patch('builtins.print'):
            images.main()
            self.assertEqual(sum('get' in c.args for c in call.call_args_list), 2)

    def test_pg_amcheck_failure_propagates(self):
        results = [subprocess.CompletedProcess([], 0, '', ''),
                   subprocess.CompletedProcess([], 0, 'tps = 1\nnumber of failed transactions: 0', ''),
                   subprocess.CompletedProcess([], 1, '', 'corrupt page'),
                   subprocess.CompletedProcess([], 0, '', '')]
        with patch.object(storage, 'psql'), patch.object(storage, 'report'), \
             patch.object(storage.subprocess, 'run', side_effect=results) as call:
            with self.assertRaises(SystemExit):
                storage.t1('zone-test')
            self.assertNotIn('echo', call.call_args_list[2].args[0][-1])

    def test_every_active_image_version_is_checked(self):
        def command(*args, **kwargs):
            return 'Succeeded' if 'get' in args else ''
        with patch.object(sys, 'argv', ['image-start-check.py', 'zone-test', 'test-node']), \
             patch.object(images, 'CHECKS', [('test/image', 'kata', ['true'])]), \
             patch.object(images, 'images', return_value={'test/image:1', 'test/image:2'}), \
             patch.object(images, 'kubectl', side_effect=command) as call, patch('builtins.print'):
            images.main()
            specs = [json.loads(c.kwargs['input']) for c in call.call_args_list if c.args[0] == 'apply']
            self.assertEqual({s['spec']['containers'][0]['image'] for s in specs}, {'test/image:1', 'test/image:2'})

    def test_relative_kubeconfig_becomes_absolute(self):
        # helmfile runs in the openDesk folder, so a relative path from the repository root must not reach it.
        with tempfile.TemporaryDirectory() as folder:
            out = subprocess.run([sys.executable, '-c', 'import settings; print(settings.KUBECONFIG)'], cwd=folder,
                                 env={'PYTHONPATH': str(SOURCE), 'KUBECONFIG': 'a/config:/b/config',
                                      'HOOVER4_SITE': str(Path(folder) / 'site.yml')},
                                 capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(out, f'{Path(folder).resolve()}/a/config:/b/config')


if __name__ == '__main__':
    unittest.main()
