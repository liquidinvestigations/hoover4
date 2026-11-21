"""The bind step of a restore: replace the values of the source zone in the restored data with the values of the target.

A zone copy and an identity copy hold the data of the source zone. The installer of the target made its own Secrets,
and the restored data still holds the passwords and host names of the source. Each function below reads the value of
the target from a Secret of the target zone, writes it into the restored data, and returns a count for the restore
record. No function prints a value.

The rules come from the prototype restore of one zone into another on a test site:

- keycloak_admin(): the Keycloak database holds the credential of kcadmin, the admin of the Keycloak master, the
  password of ldapsearch_keycloak in the user federation (bindCredential) and the secret of the UMC client
  (<portal host>/univention/oidc/). The Keycloak bootstrap of ums creates the UMC client with its secret, and it does
  not change the secret of a client that exists. The zone installer signs in with the
  password of the Secret keycloak-admin-password, so every later Keycloak step fails without this rule, and Keycloak
  reads no user of the directory without bindCredential.
- directory_accounts(): the directory holds the passwords of its service accounts, of cn=admin and of the onboarding
  account test.user. The applications bind with the passwords of their Secrets, and the UDM REST API, the provisioning
  and the portal fail with 401 without this rule. Administrator and test.user get the passwords of the target, because
  the operator of the target gives the zone to its administrator. Only cn=admin itself may write its entry, so its hash
  is written with slapmodify in the server container.
- rerun_jobs(): the configuration Jobs of the openDesk releases (zones/postrender.py REVISION_JOBS) write the client
  addresses and client secrets of Keycloak, the Nextcloud configuration (host names, Redis, mail and object store
  credentials) and the consumer registrations of the provisioning. They keep their name while their content is the
  same, so zone.py apply does not run them again. The rule creates each Job again from the Helm release record of the
  target under a new name and waits for it.

The database address, user and password in the Nextcloud configuration row are written by
../../zones/postgresql.py nextcloud_config() when the databases are restored. The copy leaves out each credential of
parts.SOURCE_VALUES, and these rules write the value of the target there.
"""
import base64
import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE.parents[1] / 'zones'))

# The Keycloak credential that keycloak_admin() writes. Keycloak checks a stored hash with its own algorithm and
# hashes the password again with its policy at the next sign-in. kcadmin exists only in the Keycloak master.
KEYCLOAK_ITERATIONS = 210000
# psql runs quietly, so each update returns its row count as a query result.
KEYCLOAK_ADMIN_SQL = (
    "WITH changed AS (UPDATE credential SET secret_data = $bind${secret}$bind$, credential_data = $bind${data}$bind$ "
    "WHERE type = 'password' AND user_id IN (SELECT id FROM user_entity WHERE username = 'kcadmin') RETURNING 1) "
    "SELECT count(*) FROM changed;\n")
KEYCLOAK_BIND_SQL = ("WITH changed AS (UPDATE component_config SET value = $bind${value}$bind$ WHERE name = "
                     "'bindCredential' RETURNING 1) SELECT count(*) FROM changed;\n")
KEYCLOAK_LDAP = ('ums-keycloak-bootstrap-ldap-opendesk-credentials', 'password')
KEYCLOAK_UMC_SQL = ("WITH changed AS (UPDATE client SET secret = $bind${value}$bind$ WHERE client_id LIKE "
                    "'%/univention/oidc/' RETURNING 1) SELECT count(*) FROM changed;\n")
KEYCLOAK_UMC = ('ums-keycloak-bootstrap-oidc-rp-umc-server', 'password')
# (account, Secret of the target, key). An account is uid=<account>,cn=users,<base>.
DIRECTORY_ACCOUNTS = [('Administrator', 'ums-nubus-credentials', 'administrator_password'),
                      ('readonly', 'ums-stack-data-ums-readonly-user', 'password'),
                      ('svc-portal-server', 'ums-stack-data-ums-svc-portal-server', 'password'),
                      ('ldapsearch_nextcloud', 'opendesk-nextcloud-management-ldap', 'password'),
                      ('ldapsearch_xwiki', 'nubus-ldap-xwiki-bind', 'password'),
                      ('ldapsearch_keycloak', 'ums-keycloak-bootstrap-ldap-opendesk-credentials', 'password')]
DIRECTORY_ADMIN = ('ums-ldap-server-admin', 'password')
# The onboarding account of ../../zones/zone-users.py. Its password is in the secret store of the zone.
ONBOARDING = 'test.user'
LDAP_POD = ('ums-ldap-server-primary-0', 'main')
# The hash of cn=admin, written with slapmodify. The password comes on standard input.
ADMIN_SCRIPT = ('set -o pipefail; h=$(slappasswd -h "{CRYPT}" -c "\\$6\\$%.16s" -T /dev/stdin) && printf '
                '"dn: cn=admin,%s\\nchangetype: modify\\nreplace: userPassword\\nuserPassword: %s\\n" '
                '"$LDAP_BASE_DN" "$h" | slapmodify -f /etc/ldap/slapd.conf -b "$LDAP_BASE_DN" 2>/dev/null')
# The Helm releases whose Jobs rerun_jobs() runs again, in this order. The Keycloak bootstrap of ums needs the
# directory, and the provisioning registrations need the Provisioning API of ums.
JOB_RELEASES = ['ums', 'opendesk-keycloak-bootstrap', 'opendesk-nextcloud-management']
JOB_TIMEOUT = 1800


def _backups():
    import backups
    return backups


def secret_value(zone, name, key):
    data = json.loads(_backups().kubectl('-n', zone, 'get', 'secret', name, '-o', 'json')).get('data') or {}
    if key not in data:
        raise SystemExit(f'the Secret {zone}/{name} has no key {key}.')
    return base64.b64decode(data[key])


def keycloak_credential(password, salt=None):
    """(secret_data, credential_data) of a Keycloak password credential with PBKDF2-SHA512."""
    salt = salt or os.urandom(16)
    value = hashlib.pbkdf2_hmac('sha512', password, salt, KEYCLOAK_ITERATIONS, 64)
    secret = {'value': base64.b64encode(value).decode(), 'salt': base64.b64encode(salt).decode(),
              'additionalParameters': {}}
    data = {'hashIterations': KEYCLOAK_ITERATIONS, 'algorithm': 'pbkdf2-sha512', 'additionalParameters': {}}
    return json.dumps(secret), json.dumps(data)


def updated(out):
    """The row count that a statement of KEYCLOAK_ADMIN_SQL or KEYCLOAK_BIND_SQL returned."""
    words = out.split()
    return int(words[-1]) if words and words[-1].isdigit() else 0


def keycloak_admin(zone):
    """Write the credential of kcadmin from the Secret keycloak-admin-password, bindCredential from the Secret of
    ldapsearch_keycloak and the secret of the UMC client from its Secret. Run it before Keycloak starts, because
    Keycloak keeps the users, components and clients in its cache."""
    import postgresql
    database = postgresql.database_name(zone, 'keycloak')
    secret, data = keycloak_credential(secret_value(zone, 'keycloak-admin-password', 'adminPassword'))
    count = updated(postgresql.server_sql(KEYCLOAK_ADMIN_SQL.format(secret=secret, data=data), database))
    if count != 1:
        raise SystemExit(f'the restored Keycloak database of {zone} has {count} passwords of kcadmin, and the bind '
                         'step needs one.')
    for sql, source in ((KEYCLOAK_BIND_SQL, KEYCLOAK_LDAP), (KEYCLOAK_UMC_SQL, KEYCLOAK_UMC)):
        value = secret_value(zone, *source).decode()
        if '$bind$' in value:
            raise SystemExit(f'the value of the Secret {source[0]} holds the quote mark of the update.')
        count += updated(postgresql.server_sql(sql.format(value=value), database))
    return count


def ldap_exec(zone, script, stdin):
    pod, container = LDAP_POD
    return _backups().kubectl('-n', zone, 'exec', '-i', pod, '-c', container, '--', 'bash', '-c', script,
                              input=stdin)


def set_password(zone, account, value):
    ldap_exec(zone, f'ldappasswd -Q -Y EXTERNAL -H ldapi:/// -T /dev/stdin "uid={account},cn=users,$LDAP_BASE_DN"',
              value)


def wait_ready(zone, pod, timeout=900):
    """Wait until pod exists and is Ready. A restore starts the zone just before, so the pod can be missing."""
    b = _backups()
    end = time.time() + timeout
    while time.time() < end:
        found = b.kubectl('-n', zone, 'get', 'pod', pod, '--ignore-not-found', '-o',
                          'jsonpath={.status.conditions[?(@.type=="Ready")].status}', check=False).strip()
        if found == 'True':
            return
        time.sleep(5)
    raise SystemExit(f'the pod {zone}/{pod} was not ready after {timeout} s.')


def directory_accounts(zone):
    """Set the password of each account of DIRECTORY_ACCOUNTS, of cn=admin and of the onboarding account from the
    values of the target. The step waits for the directory server. A copy without the onboarding account leaves it
    out."""
    import secretstore
    wait_ready(zone, LDAP_POD[0])
    for account, name, key in DIRECTORY_ACCOUNTS:
        set_password(zone, account, secret_value(zone, name, key).decode())
    # The ACL lets only cn=admin write its own entry. back-mdb lets slapmodify write beside the running server.
    ldap_exec(zone, ADMIN_SCRIPT, secret_value(zone, *DIRECTORY_ADMIN).decode())
    count = len(DIRECTORY_ACCOUNTS) + 1
    found = ldap_exec(zone, f'ldapsearch -LLL -Q -Y EXTERNAL -H ldapi:/// -b "cn=users,$LDAP_BASE_DN" "(uid={ONBOARDING})" dn',
                      '')
    stored = secretstore.read(secretstore.zone_path(zone, 'test-user')) if found.strip() else None
    if stored and stored.get('password'):
        set_password(zone, ONBOARDING, stored['password'])
        count += 1
    return count


def release_jobs(zone, release):
    """The Jobs of the newest Helm release record of release in zone."""
    import yaml
    names = [n.split('/', 1)[1] for n in _backups().kubectl('-n', zone, 'get', 'secrets', '-l',
                                                            f'owner=helm,name={release}', '-o', 'name').split()]
    if not names:
        return []
    newest = max(names, key=lambda n: int(n.rsplit('.v', 1)[1]))
    raw = json.loads(_backups().kubectl('-n', zone, 'get', 'secret', newest, '-o', 'json'))['data']['release']
    record = json.loads(gzip.decompress(base64.b64decode(base64.b64decode(raw))))
    docs = [d for d in yaml.safe_load_all(record['manifest']) if d and d.get('kind') == 'Job']
    return docs + [yaml.safe_load(h['manifest']) for h in record.get('hooks', []) if h.get('kind') == 'Job']


def job_copy(zone, job, suffix):
    """The Job as a new object named <name>-<suffix>, without the fields that the cluster set."""
    job = json.loads(json.dumps(job))
    # The name of a Job is also a label value, so it has at most 63 characters.
    name = f'{job["metadata"]["name"][:62 - len(suffix)]}-{suffix}'
    job['metadata'] = {'name': name, 'namespace': zone, 'labels': job['metadata'].get('labels') or {}}
    job['spec'].pop('selector', None)
    labels = job['spec'].get('template', {}).get('metadata', {}).get('labels') or {}
    for key in ('controller-uid', 'batch.kubernetes.io/controller-uid', 'job-name', 'batch.kubernetes.io/job-name'):
        labels.pop(key, None)
    return job


def wait_job(zone, name, timeout=JOB_TIMEOUT):
    b = _backups()
    end = time.time() + timeout
    while time.time() < end:
        status = json.loads(b.kubectl('-n', zone, 'get', 'job', name, '-o', 'json')).get('status') or {}
        if status.get('succeeded'):
            return
        if any(c['type'] == 'Failed' and c['status'] == 'True' for c in status.get('conditions') or []):
            raise SystemExit(f'the Job {zone}/{name} failed. Read kubectl -n {zone} logs job/{name}.')
        time.sleep(5)
    raise SystemExit(f'the Job {zone}/{name} did not end in {timeout} s.')


def rerun_jobs(zone, suffix):
    """Run the Jobs of JOB_RELEASES again, one release after the other, and wait for each. A restore that continues
    uses the same suffix, so it replaces the Jobs of its earlier run."""
    b = _backups()
    count = 0
    for release in JOB_RELEASES:
        jobs = [job_copy(zone, job, suffix) for job in release_jobs(zone, release)]
        for job in jobs:
            b.kubectl('-n', zone, 'delete', 'job', job['metadata']['name'], '--ignore-not-found', '--wait=true')
            b.kubectl('-n', zone, 'create', '-f', '-', input=json.dumps(job))
        for job in jobs:
            wait_job(zone, job['metadata']['name'])
        count += len(jobs)
    return count
