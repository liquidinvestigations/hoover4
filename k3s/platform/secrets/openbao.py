#!/usr/bin/env python3
"""Install OpenBao, the secret store of the site, and move the secrets of an earlier version into it.

OpenBao runs as the StatefulSet openbao of the namespace openbao with one pod in gVisor on the control-plane node. The
pod has the PriorityClass hoover-node-bound and keeps its Raft storage on a claim of the default storage class.
One pod is enough, because the site has one k3s server, so the site already stops when that node stops. The pods read
the Kubernetes Secret copies (../../secretstore.py), so a stopped store stops no service. Only the deployment tools,
the runner and the backups use the store.

OpenBao seals its storage with a static key (seal "static"). The key is secret-store/seal.key of the state folder of
the deploying host and the Secret openbao-seal of the namespace openbao. Only the OpenBao pod mounts the Secret, and
no other ServiceAccount has a right in the namespace. OpenBao unseals itself at each start, also after a power loss,
with no input. A seal key of the state folder that differs from the Secret stops the step. The cluster keeps its
Secrets encrypted at rest (secrets-encryption of the k3s server, ../../ansible/roles/hoover4_k3s).
The first start initializes OpenBao. The recovery key goes to secret-store/recovery-key of the state folder. The root
token stays in secret-store/root-token until it has configured the store, and is then revoked and deleted. Later runs
configure the store with the role deployer.

The listener uses TLS with a certificate of a CA that this step makes once, and the step keeps no CA key. The
certificate and its key are the Secret openbao-tls of the namespace. The ConfigMap openbao-ca of operator-portal holds
the CA certificate, which the clients check.

configure() writes these parts.
  - the KV version 2 mount hoover, with check-and-set on each write
  - the Kubernetes auth method with the roles deployer (ServiceAccount openbao-deployer of openbao), runner and backup
    (ServiceAccount zone-runner of operator-portal)
  - the policies deployer, runner, backup and zone-step, and the token role zone-step
The policy zone-step names the paths of the zone of its token, which is the name of the entity alias of the token.

An earlier version kept the zone secrets as Secrets of operator-portal with the label hoover.dev/state=secret. Each
Secret held one file of zones/ of the state folder (the cluster copy, ../../clusterstate.py). migrate() loads the secrets of these
files into the store and reads each value back. The files are zones/secrets.json, zones/fixture-user-passwords.json,
zones/<zone>/test-user-password, zones/<zone>/imported-users.json and the records of zones/<zone>/. A value that the
store holds with another value stops the step before any write. zones.py generates the other files from these values
(../../zones/zones.py), and passwords.md is a view (../../tools/write-password-table.py). finish() runs in the step
operator, after the operator pod of this version runs. It checks each value again, and then deletes the earlier
Secrets, the manifest of the earlier cluster copy and the earlier source files of the state folder. A second run finds
no earlier Secret and changes nothing.

Usage: openbao.py apply      install or update OpenBao, initialize and configure it, run migrate, and then keep the
                             site secrets that the zone steps read
       openbao.py migrate    load the secrets of the earlier cluster copy into the store and check them
       openbao.py finish     check them again and delete the earlier copy
       openbao.py status     print the seal state, the version and the paths of the store
The script prints no secret.
"""
import base64
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K3S = HERE.parents[1]
sys.path.insert(0, str(K3S))
import settings  # noqa: E402
import secretstore  # noqa: E402

NS = secretstore.NAMESPACE
IMAGE = 'quay.io/openbao/openbao:2.7.2@sha256:5046911075e137e154ce49ab051502f4ec7cf367d484ae4a4dce665d9b90561f'
FOLDER = settings.PRIVATE / 'secret-store'
SEAL_FILE = FOLDER / 'seal.key'
RECOVERY_FILE = FOLDER / 'recovery-key'
ROOT_FILE = FOLDER / 'root-token'
SEAL_ID = 'hoover4-1'
CLAIM_SIZE = '2Gi'
# The working set of an idle OpenBao with a few hundred paths is about 60 MiB.
RESOURCES = {'requests': {'cpu': '20m', 'memory': '128Mi'}, 'limits': {'cpu': '1', 'memory': '512Mi'}}
TOKEN_TTL = '8h'
LEGACY_LABEL = 'hoover.dev/state=secret'
LEGACY_NAMESPACE = 'operator-portal'
# The records of a zone folder of the earlier cluster copy (../../zones/zone.py, objectstore.py, postgresql.py).
RECORDS = ('opendesk-applied.json', 'objectstore-move.json', 'postgresql-move.json')
# The source files of the earlier version in the state folder. finish deletes them after the check.
LEGACY_SOURCES = ('zones/secrets.json', 'zones/passwords.md', 'zones/.cluster-state.json', 'zones/.cluster-state.lock')

CONFIG = f'''ui = false
disable_mlock = true
api_addr = "https://{secretstore.SERVICE}.{NS}.svc:{secretstore.PORT}"
cluster_addr = "https://127.0.0.1:8201"
listener "tcp" {{
  address = "0.0.0.0:{secretstore.PORT}"
  cluster_address = "127.0.0.1:8201"
  tls_cert_file = "/openbao/tls/tls.crt"
  tls_key_file = "/openbao/tls/tls.key"
}}
storage "raft" {{
  path = "/openbao/data"
  node_id = "openbao-0"
}}
seal "static" {{
  current_key_id = "{SEAL_ID}"
  current_key = "file:///openbao/seal/seal.key"
}}
'''

POLICIES = {
    # The deployer administers the store. Its kubeconfig can read the seal key anyway.
    'deployer': 'path "*" { capabilities = ["create", "read", "update", "patch", "delete", "list", "sudo"] }\n',
    'runner': ('path "hoover/*" { capabilities = ["create", "read", "update", "patch", "delete", "list"] }\n'
               'path "auth/token/create/zone-step" { capabilities = ["update"] }\n'),
    'backup': ('path "hoover/*" { capabilities = ["read", "list"] }\n'
               # A zone restore writes the restored values of the copies (../backups/backups.py restore_secrets()).
               'path "hoover/data/zones/*" { capabilities = ["create", "read", "update", "list"] }\n'
               'path "sys/storage/raft/snapshot" { capabilities = ["read", "sudo"] }\n'
               'path "sys/storage/raft/snapshot-force" { capabilities = ["update", "sudo"] }\n'),
    # ACCESSOR is the accessor of the token auth method. The entity alias of a zone step token is the zone name.
    'zone-step': ('path "hoover/data/zones/{{identity.entity.aliases.ACCESSOR.name}}/*" '
                  '{ capabilities = ["create", "read", "update", "patch", "delete", "list"] }\n'
                  'path "hoover/metadata/zones/{{identity.entity.aliases.ACCESSOR.name}}/*" '
                  '{ capabilities = ["read", "delete", "list"] }\n'
                  'path "hoover/data/site/calls" { capabilities = ["read"] }\n'
                  'path "hoover/data/site/zone-users" { capabilities = ["read"] }\n'),
}


def kubectl(*args, input=None, check=True):
    argv = ['kubectl', '--kubeconfig', settings.KUBECONFIG, *args]
    result = subprocess.run(argv, input=input, capture_output=True, text=True, timeout=300)
    if check and result.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:4])} failed: {(result.stderr or result.stdout).strip()[-400:]}')
    return result.stdout


def apply(objects):
    """Apply each object and return the lines of the changed ones. kubectl apply changes nothing for an equal object."""
    out = kubectl('apply', '-f', '-', input=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects}))
    return [line for line in out.splitlines() if not line.endswith(' unchanged')]


def b64(data):
    return base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()


def secret_data(namespace, name):
    found = kubectl('-n', namespace, 'get', 'secret', name, '--ignore-not-found', '-o', 'json').strip()
    return {k: base64.b64decode(v) for k, v in (json.loads(found).get('data') or {}).items()} if found else None


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'wb') as handle:
        handle.write(data)
    os.replace(tmp, path)


def seal_key(initialized):
    """Return the static seal key. The file of the state folder and the Secret openbao-seal hold the same 32 bytes.

    A missing side gets the key of the other side. When neither side has a key, a store that is not initialized gets a
    new key. An initialized store then stops the step, because only its own key opens it."""
    found = secret_data(NS, 'openbao-seal')
    stored = (found or {}).get('seal.key')
    local = SEAL_FILE.read_bytes() if SEAL_FILE.exists() else None
    if stored and local and stored != local:
        raise SystemExit(f'{SEAL_FILE} differs from the Secret openbao-seal of {NS}. Find the key that opens the store '
                         'and write it into both.')
    key = stored or local
    if key is None:
        if initialized:
            raise SystemExit(f'the store is initialized, and neither {SEAL_FILE} nor the Secret openbao-seal holds its '
                             'seal key. Restore the key from the site identity file (deploy-k3s identity export).')
        key = os.urandom(32)
    if len(key) != 32:
        raise SystemExit(f'the seal key has {len(key)} bytes, and the static seal needs 32')
    if local != key:
        write_private(SEAL_FILE, key)
    return key


def tls_material():
    """The certificate and key of the listener and the CA certificate. Present values stay, so a second run changes
    nothing. A certificate that ends in less than 180 days, or that has no authority key identifier, is made again.
    Python 3.13 and later refuse a certificate without that identifier (VERIFY_X509_STRICT)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    found = secret_data(NS, 'openbao-tls') or {}
    ca = kubectl('-n', NS, 'get', 'configmap', 'openbao-ca', '--ignore-not-found', '-o', 'jsonpath={.data.ca\\.crt}')
    now = datetime.datetime.now(datetime.timezone.utc)
    if found.get('tls.crt') and found.get('tls.key') and ca:
        cert = x509.load_pem_x509_certificate(found['tls.crt'])
        try:
            cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
            strict = True
        except x509.ExtensionNotFound:
            strict = False
        if strict and cert.not_valid_after_utc - now > datetime.timedelta(days=180):
            return found['tls.crt'], found['tls.key'], ca
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'hoover4 openbao CA')])
    ca_cert = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
               .not_valid_after(now + datetime.timedelta(days=3650))
               .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
               .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                            key_encipherment=False, data_encipherment=False, key_agreement=False,
                                            encipher_only=False, decipher_only=False), critical=True)
               .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    import ipaddress
    names = [x509.DNSName(n) for n in (secretstore.SERVICE, f'{secretstore.SERVICE}.{NS}', f'{secretstore.SERVICE}.{NS}.svc',
                                       f'{secretstore.SERVICE}.{NS}.svc.cluster.local', 'localhost')]
    names.append(x509.IPAddress(ipaddress.ip_address('127.0.0.1')))
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'openbao')]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5)).not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM)  # noqa: E731
    key_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return pem(cert), key_pem, pem(ca_cert).decode()


def objects(seal, tls_cert, tls_key, ca):
    """The objects of OpenBao. The pod restarts when the configuration, the certificate or the seal key changes."""
    digest = hashlib.sha256(CONFIG.encode() + tls_cert + hashlib.sha256(seal).digest()).hexdigest()[:16]
    labels = {'app.kubernetes.io/name': 'openbao'}
    health = f'/v1/sys/health?standbyok=true&uninitcode=200&sealedcode=503'
    pod = {
        'serviceAccountName': 'openbao',
        'runtimeClassName': 'gvisor',
        'priorityClassName': 'hoover-node-bound',
        'nodeSelector': {'kubernetes.io/hostname': settings.SITE.control_plane},
        'enableServiceLinks': False,
        'terminationGracePeriodSeconds': 30,
        'securityContext': {'runAsNonRoot': True, 'runAsUser': 1000, 'runAsGroup': 1000, 'fsGroup': 1000,
                            'seccompProfile': {'type': 'RuntimeDefault'}},
        'containers': [{
            'name': 'openbao', 'image': IMAGE, 'imagePullPolicy': 'IfNotPresent',
            'command': ['bao', 'server', '-config=/openbao/config/config.hcl'],
            'env': [{'name': 'SKIP_SETCAP', 'value': 'true'}, {'name': 'HOME', 'value': '/tmp'}],
            'ports': [{'name': 'api', 'containerPort': secretstore.PORT}],
            'readinessProbe': {'httpGet': {'scheme': 'HTTPS', 'path': health, 'port': 'api'},
                               'periodSeconds': 5, 'timeoutSeconds': 3, 'failureThreshold': 2},
            'resources': RESOURCES,
            'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                'capabilities': {'drop': ['ALL']}},
            'volumeMounts': [{'name': 'data', 'mountPath': '/openbao/data'},
                             {'name': 'config', 'mountPath': '/openbao/config', 'readOnly': True},
                             {'name': 'seal', 'mountPath': '/openbao/seal', 'readOnly': True},
                             {'name': 'tls', 'mountPath': '/openbao/tls', 'readOnly': True},
                             {'name': 'tmp', 'mountPath': '/tmp'}]}],
        'volumes': [{'name': 'config', 'configMap': {'name': 'openbao-config'}},
                    {'name': 'seal', 'secret': {'secretName': 'openbao-seal', 'defaultMode': 0o400}},
                    {'name': 'tls', 'secret': {'secretName': 'openbao-tls', 'defaultMode': 0o400}},
                    {'name': 'tmp', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '16Mi'}}]}
    return [
        {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': 'openbao', 'namespace': NS}},
        # The deployer logs in with a short token of this account. It has no right in the cluster.
        {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': secretstore.DEPLOYER_ACCOUNT, 'namespace': NS},
         'automountServiceAccountToken': False},
        # The Kubernetes auth method reviews the tokens of a login with the token of the OpenBao pod.
        {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRoleBinding', 'metadata': {'name': 'openbao-token-review'},
         'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': 'system:auth-delegator'},
         'subjects': [{'kind': 'ServiceAccount', 'name': 'openbao', 'namespace': NS}]},
        {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'openbao-seal', 'namespace': NS}, 'type': 'Opaque',
         'data': {'seal.key': b64(seal)}},
        {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'openbao-tls', 'namespace': NS}, 'type': 'Opaque',
         'data': {'tls.crt': b64(tls_cert), 'tls.key': b64(tls_key)}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'openbao-config', 'namespace': NS},
         'data': {'config.hcl': CONFIG}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'openbao-ca', 'namespace': NS}, 'data': {'ca.crt': ca}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': secretstore.CA_CONFIGMAP[1],
                                                                 'namespace': secretstore.CA_CONFIGMAP[0]}, 'data': {'ca.crt': ca}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': secretstore.SERVICE, 'namespace': NS},
         'spec': {'selector': labels, 'ports': [{'name': 'api', 'port': secretstore.PORT, 'targetPort': secretstore.PORT}]}},
        # Only the runner container of the operator pod calls the store in the cluster. The workstation reaches it
        # through the API server on the node of the pod, and a network policy admits the traffic of the node itself.
        {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy', 'metadata': {'name': 'openbao-clients', 'namespace': NS},
         'spec': {'podSelector': {'matchLabels': labels}, 'policyTypes': ['Ingress'],
                  'ingress': [{'from': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'operator-portal'}},
                                         'podSelector': {'matchLabels': {'app.kubernetes.io/name': 'portal'}}}],
                               'ports': [{'port': secretstore.PORT, 'protocol': 'TCP'}]}]}},
        {'apiVersion': 'apps/v1', 'kind': 'StatefulSet', 'metadata': {'name': 'openbao', 'namespace': NS, 'labels': labels},
         'spec': {'replicas': 1, 'serviceName': secretstore.SERVICE, 'selector': {'matchLabels': labels},
                  'template': {'metadata': {'labels': labels, 'annotations': {'hoover.dev/config': digest}}, 'spec': pod},
                  'volumeClaimTemplates': [{'metadata': {'name': 'data'},
                                            'spec': {'accessModes': ['ReadWriteOnce'],
                                                     'resources': {'requests': {'storage': CLAIM_SIZE}}}}]}},
    ]


def store(token=None):
    """A client of the pod through kubectl proxy, with token, or the deployer login of secretstore.client()."""
    if token is None:
        return secretstore.client()
    client = secretstore.OpenBao(None, ca=secretstore.ca_file(), forward=secretstore.KubeProxy(settings.KUBECONFIG))
    client.token = token
    return client


def health():
    """The answer of sys/health, or None when the pod does not answer."""
    client = store('')
    try:
        return client.raw('GET', 'sys/health?standbyok=true&uninitcode=200&sealedcode=200', token=False)
    except secretstore.StoreError:
        return None
    finally:
        client.forward.stop()


def wait_running(timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        phase = kubectl('-n', NS, 'get', 'pod', secretstore.POD, '--ignore-not-found', '-o',
                        'jsonpath={.status.phase} {.metadata.deletionTimestamp}', check=False).strip()
        if phase == 'Running':
            answer = health()
            if answer is not None:
                return answer
        time.sleep(3)
    raise SystemExit(f'the pod {NS}/{secretstore.POD} did not answer within {timeout} s. '
                     f'Read kubectl -n {NS} describe pod {secretstore.POD} and its log.')


def wait_unsealed(timeout=300):
    deadline = time.monotonic() + timeout
    answer = None
    while time.monotonic() < deadline:
        answer = health()
        if answer and answer.get('initialized') and not answer.get('sealed'):
            return answer
        time.sleep(3)
    raise SystemExit(f'OpenBao stayed sealed or not initialized for {timeout} s: {json.dumps(answer)}')


def initialize():
    """Initialize the store and return the root token. The recovery key goes to the state folder. The root token stays
    in secret-store/root-token until configure() finished and revoked it, so a failed first run can continue."""
    client = store('')
    try:
        answer = client.raw('PUT', 'sys/init', {'recovery_shares': 1, 'recovery_threshold': 1}, token=False)
    finally:
        client.forward.stop()
    keys = answer.get('recovery_keys_base64') or answer.get('recovery_keys_b64') or answer.get('recovery_keys') or []
    if not keys:
        raise SystemExit(f'the initialization gave no recovery key. It gave the fields {sorted(answer)}.')
    write_private(RECOVERY_FILE, ('\n'.join(keys) + '\n').encode())
    write_private(ROOT_FILE, answer['root_token'].encode())
    return answer['root_token']


def configure(client):
    """Write the mount, the auth method, the policies and the roles. Equal values change nothing in the store."""
    mounts = client.raw('GET', 'sys/mounts') or {}
    mounts = mounts.get('data', mounts)
    if f'{secretstore.MOUNT}/' not in mounts:
        client.raw('POST', f'sys/mounts/{secretstore.MOUNT}', {'type': 'kv', 'options': {'version': '2'}})
    # A new KV version 2 mount refuses requests while it upgrades its storage, for a few seconds.
    for attempt in range(30):
        try:
            client.raw('POST', f'{secretstore.MOUNT}/config', {'cas_required': True, 'max_versions': 20})
            break
        except secretstore.StoreError as error:
            if 'Upgrading' not in str(error) or attempt == 29:
                raise
            time.sleep(2)
    auths = client.raw('GET', 'sys/auth') or {}
    auths = auths.get('data', auths)
    if 'kubernetes/' not in auths:
        client.raw('POST', 'sys/auth/kubernetes', {'type': 'kubernetes'})
    client.raw('POST', 'auth/kubernetes/config', {'kubernetes_host': 'https://kubernetes.default.svc'})
    accessor = (client.raw('GET', 'sys/auth') or {})
    accessor = accessor.get('data', accessor)['token/']['accessor']
    for name, text in POLICIES.items():
        client.raw('PUT', f'sys/policies/acl/{name}', {'policy': text.replace('ACCESSOR', accessor)})
    roles = {'deployer': ([secretstore.DEPLOYER_ACCOUNT], [NS]),
             'runner': (['zone-runner'], ['operator-portal']), 'backup': (['zone-runner'], ['operator-portal'])}
    for role, (accounts, namespaces) in roles.items():
        client.raw('POST', f'auth/kubernetes/role/{role}', {
            'bound_service_account_names': accounts, 'bound_service_account_namespaces': namespaces,
            'token_policies': [role], 'token_ttl': TOKEN_TTL, 'token_max_ttl': '24h'})
    client.raw('POST', 'auth/token/roles/zone-step', {
        'allowed_policies': ['zone-step'], 'allowed_entity_aliases': ['zone-*'], 'orphan': True,
        'renewable': False, 'token_explicit_max_ttl': '24h'})


def install():
    """Apply the objects, wait for the pod, initialize and configure the store. Return what changed."""
    exists = kubectl('get', 'namespace', NS, '--ignore-not-found', '-o', 'name').strip()
    if not exists:
        kubectl('create', 'namespace', NS)
    claim = kubectl('-n', NS, 'get', 'pvc', 'data-openbao-0', '--ignore-not-found', '-o', 'name').strip()
    cert, key, ca = tls_material()
    # A present claim can hold an initialized store, which only its own seal key opens.
    seal = seal_key(initialized=bool(claim))
    changed = apply(objects(seal, cert, key, ca))
    # A changed template replaces the pod. The StatefulSet uses the default rolling update, so the pod restarts at once.
    kubectl('-n', NS, 'rollout', 'status', 'statefulset/openbao', '--timeout=600s')
    answer = wait_running()
    root = ROOT_FILE.read_text().strip() if ROOT_FILE.exists() else None
    if not answer.get('initialized'):
        root = initialize()
        changed.append('initialized')
    wait_unsealed()
    if root:
        client = store(root)
        try:
            configure(client)
            client.raw('POST', 'auth/token/revoke-self', {})
        finally:
            client.forward.stop()
        ROOT_FILE.unlink()
    else:
        configure(secretstore.client())
    return changed


def site_secrets():
    """The site paths that the zone steps only read: the call secrets and the zone user passwords."""
    sys.path.insert(0, str(K3S / 'zones'))
    import zones
    zones.site_secrets()


# ----------------------------------------------------------------------------------------------------------------------
# Migration of the earlier cluster copy
# ----------------------------------------------------------------------------------------------------------------------

def legacy_objects():
    """{path: (object name, bytes)} of the Secrets of the earlier cluster copy."""
    items = json.loads(kubectl('-n', LEGACY_NAMESPACE, 'get', 'secrets', '-l', LEGACY_LABEL, '-o', 'json'))['items']
    out = {}
    for item in items:
        path = (item['metadata'].get('annotations') or {}).get('hoover.dev/state-path')
        if path:
            out[path] = (item['metadata']['name'], base64.b64decode((item.get('data') or {}).get('content', '')))
    return out


def legacy_values(files):
    """Return [(store path, {key: value}, kind)] of the secret files of the earlier copy. kind is secret or record.

    files is {path of the state folder: bytes}. A master-password file that differs from the zone secrets stops the
    migration, because the zone runs with the value of the file."""
    out = []
    if 'zones/secrets.json' in files:
        data = json.loads(files['zones/secrets.json'])
        if 'calls' in data:
            out.append(('site/calls', data['calls'], 'secret'))
        for zone, entry in data.items():
            if zone == 'calls':
                continue
            out.append((secretstore.zone_path(zone), entry, 'secret'))
            master = files.get(f'zones/{zone}/master-password')
            if master is not None and master.decode().strip() != entry.get('master_password'):
                raise SystemExit(f'zones/{zone}/master-password differs from master_password of {zone} in '
                                 'zones/secrets.json. Find the value that the zone uses before the migration.')
    if 'zones/fixture-user-passwords.json' in files:
        out.append(('site/zone-users', json.loads(files['zones/fixture-user-passwords.json']), 'secret'))
    for path, data in sorted(files.items()):
        parts = path.split('/')
        if len(parts) != 3 or parts[0] != 'zones' or not secretstore.ZONE.fullmatch(parts[1]):
            continue
        zone, name = parts[1], parts[2]
        if name == 'test-user-password':
            out.append((secretstore.zone_path(zone, 'test-user'), {'password': data.decode().strip()}, 'secret'))
        elif name == 'imported-users.json':
            out.append((secretstore.zone_path(zone, 'imported-users'), json.loads(data), 'secret'))
        elif name in RECORDS:
            out.append((secretstore.zone_path(zone, f'records/{name}'), {'content': data.decode()}, 'record'))
    return out


def legacy_files():
    """The files of the earlier copy: the Secrets, checked against the files of the state folder of this host."""
    objects_ = legacy_objects()
    files = {path: data for path, (_, data) in objects_.items()}
    for path, data in files.items():
        local = settings.PRIVATE / path
        if local.is_file() and local.read_bytes() != data and Path(path).name not in RECORDS:
            raise SystemExit(f'{local} differs from its Secret in the cluster copy. Run clusterstate.py pull, or find '
                             'the newer file, before the migration.')
    return objects_, files


def migrate():
    """Load the values of the earlier copy into the store and read each back. Return the counts."""
    objects_, files = legacy_files()
    if not objects_:
        return {'legacy_objects': 0}
    values = legacy_values(files)
    # The check reads every stored value before the first write, so a differing value stops the step with no write.
    client = secretstore.client()
    for path, data, kind in values:
        current, _ = client.read(path)
        if kind == 'secret':
            for key, value in data.items():
                if key in current and current[key] != value:
                    raise SystemExit(f'the key {key} of {secretstore.MOUNT}/{path} differs from the earlier cluster '
                                     'copy. Nothing was written. Find the value that the services use.')
    written = 0
    for path, data, kind in values:
        if kind == 'secret':
            before = client.read(path)[0]
            secretstore.keep(path, copy=data, source='the earlier cluster copy')
            written += before != client.read(path)[0]
        elif not client.read(path)[0]:
            secretstore.update(path, lambda _, data=data: dict(data))
            written += 1
    checked = check(values)
    return {'legacy_objects': len(objects_), 'paths': len(values), 'written': written, 'checked_keys': checked}


def check(values):
    """Read each value of the earlier copy back from the store. A difference stops the step."""
    client = secretstore.client()
    checked = 0
    for path, data, kind in values:
        if kind != 'secret':
            continue
        current = client.read(path)[0]
        for key, value in data.items():
            if current.get(key) != value:
                raise SystemExit(f'the key {key} of {secretstore.MOUNT}/{path} differs from the earlier cluster copy '
                                 'after the migration. The earlier copy stays.')
            checked += 1
    return checked


def finish():
    """Check every value of the earlier copy again, then delete its Secrets and the earlier source files."""
    objects_, files = legacy_files()
    removed = []
    if objects_:
        values = legacy_values(files)
        checked = check(values)
        for path, (name, _) in sorted(objects_.items()):
            kubectl('-n', LEGACY_NAMESPACE, 'delete', 'secret', name, '--ignore-not-found')
        removed = sorted(objects_)
    else:
        checked = 0
    local = []
    for path in LEGACY_SOURCES:
        target = settings.PRIVATE / path
        if target.exists():
            target.unlink()
            local.append(path)
    return {'deleted_objects': len(removed), 'checked_keys': checked, 'deleted_files': local}


def status():
    answer = health()
    out = {'health': {k: answer.get(k) for k in ('initialized', 'sealed', 'version')} if answer else None}
    if answer and answer.get('initialized') and not answer.get('sealed'):
        client = secretstore.client()
        out['site'] = client.list('site')
        out['zones'] = client.list('zones')
    return out


def main(argv):
    if len(argv) != 1:
        raise SystemExit(__doc__)
    settings.use_kubeconfig()
    try:
        if argv[0] == 'apply':
            changed = install()
            # The secrets of an earlier version go in before the site secrets, so no new value takes their place.
            migrated = migrate()
            site_secrets()
            print(json.dumps({'step': 'secret-store', 'changed': changed, 'migration': migrated}))
        elif argv[0] == 'migrate':
            print(json.dumps({'step': 'secret-store-migrate', **migrate()}))
        elif argv[0] == 'finish':
            print(json.dumps({'step': 'secret-store-finish', **finish()}))
        elif argv[0] == 'status':
            print(json.dumps(status()))
        else:
            raise SystemExit(__doc__)
    except secretstore.StoreError as error:
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main(sys.argv[1:])
