"""A second up without a change of its inputs changes nothing, up --rebalance moves running pods, the call services
read the zone secrets while they run, and the exec helper moves complete data into and out of a container."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

import pytest

from conftest import K3S

sys.path.insert(0, str(K3S))
sys.path.insert(0, str(K3S / 'driver'))
import deploy  # noqa: E402
import placement  # noqa: E402
import podexec  # noqa: E402


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def load_compose():
    os.environ.setdefault('HOOVER4_SITE', '/nonexistent/site.yml')
    spec = importlib.util.spec_from_file_location('compose_tags', K3S / 'hoover/compose.py')
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pytest.skip('compose.py needs a site file in this environment')
    return module


@pytest.fixture
def image_repo(tmp_path):
    repo = tmp_path / 'repo'
    for path, text in (('web/Dockerfile', 'FROM a\n'), ('web/app.txt', 'one\n'), ('worker/Dockerfile', 'FROM b\n'),
                       ('docs/user-manual/a.md', 'manual\n'), ('Readme.md', 'readme\n')):
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git(tmp_path, 'init', '-q', str(repo))
    for key, value in (('user.email', 't@example.org'), ('user.name', 't')):
        git(repo, 'config', key, value)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'one')
    return repo


def test_an_image_tag_changes_only_with_the_inputs_of_its_image(image_repo, monkeypatch):
    compose = load_compose()
    monkeypatch.setattr(compose, 'IMAGES', {'website': ('web/Dockerfile', 'web'), 'processing': ('worker/Dockerfile', 'worker')})
    monkeypatch.setattr(compose, 'GPU_IMAGES', {})
    first = compose.image_tags('HEAD', image_repo)
    (image_repo / 'Readme.md').write_text('changed readme\n')
    git(image_repo, 'commit', '-qam', 'docs only')
    assert compose.image_tags('HEAD', image_repo) == first
    (image_repo / 'web/app.txt').write_text('two\n')
    git(image_repo, 'commit', '-qam', 'web')
    second = compose.image_tags('HEAD', image_repo)
    assert second['processing'] == first['processing'] and second['website'] != first['website']
    # The manuals are an input of the website image (build-hoover.py copies them into its context).
    (image_repo / 'docs/user-manual/a.md').write_text('new manual\n')
    git(image_repo, 'commit', '-qam', 'manual')
    third = compose.image_tags('HEAD', image_repo)
    assert third['processing'] == first['processing'] and third['website'] != second['website']
    with pytest.raises(ValueError):
        compose.image_tags('0' * 40, image_repo)


def test_the_render_and_the_driver_use_the_image_tags_of_the_deployment(monkeypatch):
    sys.path.insert(0, str(K3S / 'hoover'))
    os.environ.setdefault('HOOVER4_SITE', '/nonexistent/site.yml')
    try:
        import manifests
    except SystemExit:
        pytest.skip('manifests.py needs a site file in this environment')
    monkeypatch.setenv('HOOVER4_IMAGE_TAGS', json.dumps({'website': 'aaaa', 'garage-init': 'bbbb'}))
    assert manifests.image_tag('f' * 40, 'website') == 'aaaa'
    monkeypatch.delenv('HOOVER4_IMAGE_TAGS')
    assert manifests.image_tags(manifests.NO_REVISION) == {}
    keys = ('website', 'processing', 'regex', 'tesseract', 'ocr-pdf', 'clamav', 'pdf-search', 'garage-init',
            'mcp-collections', 'mcp-todo', 'mcp-whois', 'mcp-metasearch', 'mcp-browser', 'web-tor', 'research-agent')
    assert 'hoover/hoover-website:tag-website' in deploy.zone_image_names({k: f'tag-{k}' for k in keys})


def test_the_operator_image_ignores_the_documentation():
    files = deploy.operator_tree()
    assert files and not any(f.endswith('.md') for f in files)
    assert 'k3s/driver/deploy.py' in files


def test_the_operator_step_restarts_a_deployment_only_for_a_changed_configuration():
    text = (K3S / 'platform/operator/start-web-tools.sh').read_text()
    assert 'rollout restart' not in text
    # The proxy secret and the bcrypt hash of the admin password stay the same across runs.
    # The secret store keeps them, and a stored value never changes (../secretstore.py keep()).
    assert 'secretstore.py" files site/operator-login' in text and 'proxy-secret:hex32' in text
    assert 'admin-password.bcrypt' in text
    spec = importlib.util.spec_from_file_location('config_digest', K3S / 'platform/operator/config-digest.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = {('configmap', 'dex'): {'config.yaml': 'a'}, ('configmap', 'dex-templates'): {'password.html': 'p'},
            ('secret', 'operator-login'): {'client-secret': 'c', 'cookie-secret': 'k', 'proxy-secret': 'x'}}
    one = module.digest(module.READS['dex'], lambda kind, name: data[kind, name])
    data['secret', 'operator-login']['proxy-secret'] = 'y'
    # Dex does not read the proxy secret, so it keeps its pod.
    assert module.digest(module.READS['dex'], lambda kind, name: data[kind, name]) == one
    data['configmap', 'dex']['config.yaml'] = 'b'
    assert module.digest(module.READS['dex'], lambda kind, name: data[kind, name]) != one
    # The pods read the commit from a ConfigMap, so a new commit changes no template.
    login = (K3S / 'platform/operator/operator-login.yaml').read_text()
    assert 'value: OPERATOR_REVISION' not in login and login.count('configMapKeyRef: {name: operator-revision') == 2


def test_a_zone_apply_restarts_the_portal_server_only_at_the_first_install():
    text = (K3S / 'zones/zone.py').read_text()
    body = text[text.index('def opendesk(zone):'):text.index('def hoover(zone):')]
    assert 'first = first_bootstrap(zone)' in body
    restart = body.index("'rollout', 'restart', 'deployment/ums-portal-server'")
    assert body.rfind('if first:', 0, restart) > body.index('mark_bootstrapped(zone)')


def test_the_cluster_manifests_name_the_defaults_of_the_api_server():
    import yaml
    for path in ('cluster/placement-policy.yaml', 'zones/manifests/zone-pods.yaml'):
        for doc in yaml.safe_load_all((K3S / path).read_text()):
            rules = ((doc or {}).get('spec') or {}).get('matchConstraints', {}).get('resourceRules') or []
            assert all(r.get('scope') == '*' for r in rules), path


def test_the_call_services_read_the_zone_secrets_while_they_run():
    text = (K3S / 'platform/calls/install-calls.py').read_text()
    # coturn keeps no zone secret in its configuration file. The sidecar copies them into its database.
    assert 'static-auth-secret' not in text and "'userdb=/var/lib/coturn/turndb'" in text
    assert "secret('coturn-secrets'" in text and "'restartPolicy':'Always'" in text
    # The LiveKit SFU of the retired chat calls is not installed, and an earlier one is removed.
    assert 'LIVEKIT' not in text and "n.split('/',1)[1]=='livekit'" in text
    # The bridge starts without XMPP connections and the sidecar adds one per zone.
    assert "'JVB_DISABLE_XMPP':'1'" in text and "values.pop(key,None)" in text and '/colibri/muc-client/add' in text
    zones_text = (K3S / 'zones/zones.py').read_text()
    assert 'livekitAuth' not in zones_text and "data['calls']['livekit_secret']" not in zones_text
    # The probe of the host rule runs again only when its inputs change.
    assert "record.get('inputs')==inputs" in text


def test_the_coturn_sidecar_copies_the_secrets_into_the_database(tmp_path):
    text = (K3S / 'platform/calls/install-calls.py').read_text()
    script = text.split('COTURN_SECRETS=r"""', 1)[1].split('"""', 1)[0]
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    store = tmp_path / 'store'
    # The fake turnadmin keeps one secret per line, and -S prints each with its domain in brackets.
    (bin_dir / 'turnadmin').write_text(f'''#!/bin/sh
case "$1" in
  -S) [ -f {store} ] && sed "s/$/[$3]/" {store} ;;
  -s) echo "$2" >> {store} ;;
  -X) grep -vxF "$2" {store} > {store}.n; mv {store}.n {store} ;;
esac
''')
    (bin_dir / 'turnadmin').chmod(0o755)
    folder = tmp_path / 'secrets'
    folder.mkdir()
    (folder / 'secrets').write_text('a1\nb2\n')
    store.write_text('old\nb2\n')
    root = tmp_path / 'root'
    for path in ('var/lib/coturn', 'var/tmp'):
        (root / path).mkdir(parents=True)
    script = (script.replace('/var/lib/coturn', str(root / 'var/lib/coturn')).replace('/var/tmp', str(root / 'var/tmp'))
              .replace('/etc/coturn-secrets', str(folder)).replace('sleep 5', 'exit 0'))
    result = subprocess.run(['sh', '-c', script], capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, TURN_REALM='turn.test', PATH=f"{bin_dir}:{os.environ['PATH']}"))
    assert result.returncode == 0, result.stderr
    assert sorted(store.read_text().split()) == ['a1', 'b2']
    assert (root / 'var/lib/coturn/synced').exists()
    assert 'a1' not in result.stdout and 'secrets: 1 added, 1 removed' in result.stdout


FAKE_KUBECTL = '''#!/bin/sh
# The fake runs the command after -- on this host, as kubectl exec runs it in the container.
while [ "$1" != "--" ]; do shift; done
shift
exec "$@"
'''


def test_the_exec_helper_moves_more_than_one_mebibyte_in_both_directions(tmp_path):
    fake = tmp_path / 'kubectl'
    fake.write_text(FAKE_KUBECTL)
    fake.chmod(0o755)
    payload = os.urandom(3 << 20)
    path = tmp_path / 'part'
    path.write_bytes(payload[1 << 20:])
    out = tmp_path / 'out'
    command = [sys.executable, '-c', 'import hashlib,sys; d=sys.stdin.buffer.read(); '
               'sys.stdout.buffer.write(hashlib.sha256(d).hexdigest().encode() + b"a" * (2 << 20))']
    with open(out, 'wb') as f:
        code = podexec.run([str(fake), 'exec', '-i', 'pod'], command, [payload[:1 << 20], path], stdout=f)
    data = out.read_bytes()
    assert code == 0 and len(data) == 64 + (2 << 20)
    assert data[:64].decode() == hashlib.sha256(payload).hexdigest()
    # A chunk iterator needs its size.
    with open(out, 'wb') as f:
        code = podexec.run([str(fake), 'exec', '-i', 'pod'], command, iter([b'ab', b'c']), stdout=f, size=3)
    assert code == 0 and out.read_bytes()[:64].decode() == hashlib.sha256(b'abc').hexdigest()


def test_the_users_of_exec_with_input_keep_the_input_open():
    for path in ('hoover/stores/garage_client.py', 'platform/backups/backups.py'):
        assert 'podexec.run(' in (K3S / path).read_text(), path


def test_a_rebalance_moves_running_pods_only_when_the_flag_asks_for_it():
    nodes = [placement.Node('slow', 32000, 2000), placement.Node('fast', 32000, 12000)]
    pods = [placement.Pod(((f'zone-a/deployment/w{i}', 0),), 512, 400, current='slow', names=(f'w{i}-x',))
            for i in range(4)]
    pods.append(placement.Pod((('zone-a/statefulset/db', 0),), 512, 400, fixed='slow', current='slow', names=('db-0',)))
    kept = placement.solve(nodes, pods)
    assert kept.where == ['slow'] * 5 and placement.moves(kept) == []
    moved = placement.solve(nodes, pods, rebalance=True)
    found = placement.moves(moved)
    assert found and all(m[3] == 'slow' and m[4] == 'fast' for m in found)
    # A pod with a fixed node never moves.
    assert moved.where[-1] == 'slow' and not any(m[1] == 'db-0' for m in found)
    # The same inputs give the same moves.
    assert placement.moves(placement.solve(nodes, pods, rebalance=True)) == found


def test_the_rebalance_stops_at_a_pod_that_starts_on_another_node(monkeypatch):
    plan = placement.Plan(1.0, ['fast'], [], [placement.Pod((('zone-a/deployment/w', 0),), 100, 10, current='slow',
                                                           names=('w-old',))])
    old = {'metadata': {'name': 'w-old', 'namespace': 'zone-a', 'uid': 'u1'}, 'spec': {'nodeName': 'slow', 'containers': []}}
    new = {'metadata': {'name': 'w-new', 'namespace': 'zone-a', 'uid': 'u2'}, 'spec': {'nodeName': 'other', 'containers': []},
           'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
    state = {'evicted': False}
    monkeypatch.setattr(placement, 'runtime_overhead', lambda: {})
    monkeypatch.setattr(placement, 'free_room', lambda nodes, pods: {'fast': [1000, 1000], 'slow': [0, 0]})
    monkeypatch.setattr(placement, 'kubectl_json', lambda *a: {'items': [old]} if 'pods' in a else {'items': []})
    monkeypatch.setattr(placement, 'workload_pods', lambda key: [new] if state['evicted'] else [old])

    class Done:
        returncode, stdout, stderr = 0, '', ''

    def kubectl(*args, **kw):
        state['evicted'] = True
        return Done()
    monkeypatch.setattr(placement, 'kubectl', kubectl)
    result = placement.rebalance(plan, timeout=5, pause=0)
    assert result['moved'] == [] and 'started on other, not on its planned node fast' in result['error']


def test_up_deletes_the_pods_that_a_kubelet_refused(monkeypatch, tmp_path):
    class Ctx:
        kubeconfig = tmp_path / 'kubeconfig'
        deleted = []

        def kubectl(self, *args, check=True):
            self.deleted.append(args)
            return ''
    Ctx.kubeconfig.write_text('')
    pods = {'items': [
        {'metadata': {'namespace': 'operator-portal', 'name': 'portal-x', 'ownerReferences': [{'kind': 'ReplicaSet'}]},
         'status': {'phase': 'Failed', 'reason': 'OutOfmemory'}},
        {'metadata': {'namespace': 'zone-a', 'name': 'job-x', 'ownerReferences': [{'kind': 'Job'}]},
         'status': {'phase': 'Failed', 'reason': 'OutOfmemory'}},
        {'metadata': {'namespace': 'zone-a', 'name': 'crash', 'ownerReferences': [{'kind': 'ReplicaSet'}]},
         'status': {'phase': 'Failed', 'reason': 'Error'}}]}
    monkeypatch.setattr(deploy, 'read', lambda argv, **kw: (0, json.dumps(pods)))
    ctx = Ctx()
    assert deploy.delete_rejected_pods(ctx) == ['operator-portal/portal-x']
    assert ctx.deleted[0][:4] == ('-n', 'operator-portal', 'delete', 'pod')
