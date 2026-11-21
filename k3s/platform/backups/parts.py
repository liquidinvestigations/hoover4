"""The class of each part of a zone: a claim, a database, a bucket, a Secret or a ConfigMap.

A zone copy (backups.py run_zone()) holds only the parts of the class data. The identity copy (run_identity()) holds
the parts of the class people: the directory claim and the Keycloak database. The installer and the running services
of the target zone make the parts of the classes identity and derived again, so no copy holds them. A part of the
class off belongs to an application that the zones do not install.

classify() raises for a part without a class, so a new openDesk release cannot add a part that no copy and no rule
names. The copy job classifies every part of the namespace before its first read. The names of the claims hold the
release names, so the patterns use fnmatch. The retired applications of ../../zones/applications.py have the class off.
"""
import fnmatch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'zones'))
import applications  # noqa: E402

CLASSES = ('data', 'people', 'derived', 'identity', 'off')

# {kind: [(name pattern, class)]}. The first matching pattern gives the class.
COPY_PARTS = {
    'claim': [
        # The directory: users, groups, memberships and password hashes.
        ('shared-data-ums-ldap-server-primary-*', 'people'),
        ('xwiki-data-xwiki-*', 'data'),
        ('shared-run-ums-ldap-server-primary-*', 'derived'),
        ('redis-data-redis-master-*', 'derived'),
        ('nats-data-ums-provisioning-nats-*', 'derived'),
        ('data-ums-provisioning-udm-listener-*', 'derived'),
        ('group-membership-cache-ums-portal-consumer-*', 'derived'),
        # The Hoover namespace: the export folders, which a collection copy removes, and uploads that are not complete.
        ('ops-backups', 'derived'),
        ('upload-tmp', 'derived'),
    ],
    # The openDesk databases on the shared PostgreSQL (../../zones/postgresql.py DATABASES).
    'database': [
        ('keycloak', 'people'),
        ('nextcloud', 'data'),
        ('xwiki', 'data'),
        ('keycloak_extensions', 'derived'),
        ('nubus_authsession', 'derived'),
        ('selfservice', 'derived'),
        ('guardianmanagementapi', 'derived'),
        ('oxconnector', 'off'),
    ],
    # The openDesk buckets of the zone, by their openDesk names (../../zones/objectstore.py BUCKETS).
    'bucket': [
        ('nextcloud', 'data'),
        ('ums', 'data'),
        ('migrations', 'derived'),
        ('openxchange', 'off'),
    ],
    # The installer renders each Secret from the secret store of the target, and each ConfigMap from its values.
    'secret': [('*', 'identity')],
    'configmap': [('*', 'derived')],
}


def classify(kind, name):
    """The class of a part. A part of a retired application has the class off. An unknown part stops the job."""
    if kind not in COPY_PARTS:
        raise SystemExit(f'{kind} is not a kind of zone part. The kinds are {", ".join(COPY_PARTS)}.')
    if kind == 'claim' and applications.retired_part(name):
        return 'off'
    if kind == 'database' and name in applications.RETIRED_DATABASES.values():
        return 'off'
    if kind == 'bucket' and name in applications.RETIRED_BUCKETS:
        return 'off'
    for pattern, cls in COPY_PARTS[kind]:
        if fnmatch.fnmatchcase(name, pattern):
            return cls
    raise SystemExit(f'the {kind} {name} has no class in COPY_PARTS of k3s/platform/backups/parts.py. Give it the class '
                     f'data, people, derived, identity or off, then run the job again.')


# The columns of the copied databases that hold a credential of the source zone. The copy writes an empty value there
# (backups.py leave_out_source_values()), and the bind step of the restore (bind.py) writes the value of the target.
# Each rule is (table, match, column, change). match is None for every row, (match columns, match value tuples) for the
# rows whose match columns hold one of the tuples, or a function of the row {column: value} that returns True. The change None writes NULL, '' an empty text, and a tuple
# of key paths removes those keys from the JSON value of the column.
SOURCE_VALUES = {
    'keycloak': [
        # The client secrets of the openDesk and UMC clients. rerun_jobs() writes them from the Secrets of the target.
        ('client', None, 'secret', None),
        # The password of ldapsearch_keycloak in the user federation. keycloak_admin() writes it.
        ('component_config', (('name',), {('bindCredential',)}), 'value', ''),
    ],
    'nextcloud': [
        # The configuration row of Nextcloud. postgresql.nextcloud_config() writes the database fields, and the
        # Nextcloud management Job of rerun_jobs() writes the others.
        ('fs_config_store', (('name',), {('config_php',)}), 'value',
         (('dbpassword',), ('redis', 'password'), ('mail_smtppassword',), ('objectstore', 'arguments', 'key'),
          ('objectstore', 'arguments', 'secret'))),
        # The LDAP password, the shared secret of the central navigation and the serverinfo token. The management Job
        # writes them.
        ('oc_appconfig', (('appid', 'configkey'), {('user_ldap', 's01ldap_agent_password'),
                                                    ('integration_swp', 'navigation-json-api-secret'),
                                                    ('serverinfo', 'token')}), 'configvalue', ''),
    ],
    'xwiki': [
        # The SMTP password of Mail.MailConfig (class Mail.SendMailConfigClass), the only password row that is not a
        # hash. The XWiki configuration of the target writes it at its start.
        ('xwikipasswords', lambda row: row['xwp_name'] == 'password' and not (row['xwp_value'] or '').startswith('hash:'),
         'xwp_value', ''),
        # The history of Mail.MailConfig holds the same password in its patches. Its document id is a hash of its name,
        # which is the same in each wiki of the release.
        ('xwikircs', (('xwr_docid',), {('361299506791820685',)}), 'xwr_patch', ''),
    ],
}

# The members of a claim that the copy leaves out, as tar patterns: {claim pattern: [members]}. XWiki writes its three
# configuration files with the database password, the client secret, the LDAP password and the navigation secret from
# the Secrets of the target at each start (the init containers xwiki-changeable-configs and xwiki-secrets). The status
# logs of the extension jobs hold the SMTP password of the install.
CLAIM_LEFT_OUT = {
    'xwiki-data-xwiki-*': ['./xwiki.properties', './hibernate.cfg.xml', './xwiki.cfg', './jobs/status'],
}


def left_out(claim):
    """The tar patterns of the members of a claim that the copy leaves out."""
    return [m for pattern, members in CLAIM_LEFT_OUT.items() if fnmatch.fnmatchcase(claim, pattern) for m in members]
