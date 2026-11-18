#!/usr/bin/env python3
"""The openDesk databases of a zone on the shared PostgreSQL server of the site.

A zone of the store layout site keeps the databases of its openDesk applications in the PostgreSQL server of the shared
stores (../hoover/stores/shared.py postgresql()). It runs no PostgreSQL in its namespace. Each PostgreSQL database of
the openDesk release (DATABASES) has the database <prefix>_<name> and the user <prefix>_<user> of the zone, where the
prefix is the zone id with _ for - (zone-a gives zone_a_nextcloud and zone_a_nextcloud_user). The user owns its
database, has the connection limit of the release, and cannot create a database or a role. ensure() creates them,
and a second run changes nothing. The passwords are postgresql of the zone secrets in the secret store (../secretstore.py). zones.py writes the host,
the names and the passwords into the openDesk values of the zone (values()) and turns the PostgreSQL of openDesk off.

Isolation: no database of a zone and no database of the server (postgres, template1) admits a connection of PUBLIC,
so a user connects only to its own database. In each zone database the users cannot read the catalogs of HIDDEN, which
name the databases, the roles and the sessions of the server. Synapse reads the collation of its database from
pg_database at its start, so its user reads that catalog in its own database (READERS) and can list the database names.
The network policy postgresql-clients of shared.py admits only the openDesk namespaces of the site zones.

The zone state entry has postgresql = site for a zone on the shared server. zone.py apply gives it to each new zone of
the store layout site. A zone of an earlier version runs PostgreSQL in its namespace and has no value. zone.py apply
moves such a zone with the admin kubeconfig (move()):
  1. ensure() creates the databases and the users on the shared server.
  2. The users of the zone server lose their login, and their sessions end. From this moment no application changes a
     row until the switch ends.
  3. Each database of the zone server is copied (pg_dump, then pg_restore as its new user into an empty database).
  4. The row count of each table must be equal in both servers. Else the users get their login again, the
     applications use the zone server again, and the command stops with the counts.
  5. The Nextcloud configuration in the copied database (fs_config_store) gets the new host, name, user and password,
     because Nextcloud reads it from its database at its start.
  6. The volume of the zone server gets the reclaim policy Retain and the label LABEL. The record
     postgresql-move.json of the zone in the secret store holds the counts and the times.
  7. The zone state gets postgresql = site. zones.py then writes the values with the shared server, and the openDesk
     waves of zone.py apply them. Helm removes the PostgreSQL of the zone.
  8. Each workload whose configuration names the shared server, and Nextcloud, restart once when their pods started
     before the switch (finish()). The switch ends when they are ready. The claim of the zone server goes, and its
     volume stays.
A zone runner without the right to change a volume leaves the zone on its own server, and deploy-k3s up moves it.
After a check of the applications, drop-volume deletes the kept volume. zone.py delete deletes it too.

Usage: postgresql.py show <zone>           print the databases of the zone on the shared server with their sizes
       postgresql.py check <zone>          compare the row counts of the zone server and the shared server, without a
                                           change. The applications write while the check reads, so a busy table can
                                           differ.
       postgresql.py drop-volume <zone>    delete the volume of the zone server that a move kept
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / 'hoover' / 'stores'))
import settings  # noqa: E402

# The PostgreSQL databases of the openDesk release (databases of database.yaml.gotmpl with the type postgresql): the
# value key, and the database name and the user name of the release. test_postgresql.py compares them with the release.
DATABASES = {
    'keycloak': ('keycloak', 'keycloak_user'),
    'keycloakExtension': ('keycloak_extensions', 'keycloak_extensions_user'),
    'matrixAuthenticationService': ('matrix_authentication', 'matrix_authentication_user'),
    'nextcloud': ('nextcloud', 'nextcloud_user'),
    'notes': ('notes', 'notes_user'),
    'openproject': ('openproject', 'openproject_user'),
    'oxConnector': ('oxconnector', 'oxconnector_user'),
    'synapse': ('matrix', 'matrix_user'),
    'umsAuthSession': ('nubus_authsession', 'authsession_user'),
    'umsGuardianManagementApi': ('guardianmanagementapi', 'guardianmanagementapi_user'),
    'umsSelfservice': ('selfservice', 'selfservice_user'),
    'xwiki': ('xwiki', 'xwiki_user'),
}
# The CREATE DATABASE options of the release (additionalParams). Synapse refuses a database with another collation.
CREATE_OPTIONS = {'synapse': "ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0",
                  'xwiki': "ENCODING 'UNICODE' TEMPLATE template0"}
# The connection limit of each user (connectionLimit of the release, else databases.defaults.userConnectionLimit).
CONNECTION_LIMITS = {'umsAuthSession': 10, 'umsSelfservice': 10}
DEFAULT_CONNECTION_LIMIT = 100
# The catalogs that name the databases, the roles and the sessions of the server. No zone user reads them.
HIDDEN = ('pg_database', 'pg_stat_database', 'pg_stat_database_conflicts', 'pg_roles', 'pg_user', 'pg_group',
          'pg_auth_members', 'pg_stat_activity', 'pg_shdescription')
# The catalogs of HIDDEN that an application reads in its own database.
READERS = {'synapse': ('pg_database',)}
# The databases of the server that no zone user connects to.
SERVER_DATABASES = ('postgres', 'template1')
STORES_NS = 'hoover-stores'
HOST = f'postgresql.{STORES_NS}.svc.cluster.local'
PORT = 5432
# The PostgreSQL of a zone of an earlier version: its pod, its container and its claim.
ZONE_POD = 'postgresql-0'
ZONE_CLAIM = 'data-postgresql-0'
# The label of a zone server volume that a move kept. Its value is the zone.
LABEL = 'hoover.dev/postgresql-of'
RECORD = 'postgresql-move.json'
# The table of the Nextcloud database that holds config.php, and the fields of the database connection.
NEXTCLOUD_CONFIG = ('fs_config_store', 'config_php')


def prefix(zone):
    return zone.replace('-', '_')


def database_name(zone, key):
    return f'{prefix(zone)}_{DATABASES[key][0]}'


def user_name(zone, key):
    return f'{prefix(zone)}_{DATABASES[key][1]}'


def connection_limit(key):
    return CONNECTION_LIMITS.get(key, DEFAULT_CONNECTION_LIMIT)


def new_passwords():
    """A password for each database user of a zone."""
    return {key: secrets.token_hex(24) for key in DATABASES}


def on_shared(entry):
    """True when the zone state entry keeps the openDesk databases on the shared server."""
    return entry.get('stores') == 'site' and entry.get('postgresql') == 'site'


def values(zone, passwords):
    """The openDesk values of a zone on the shared server: each database with the host, its names and its password."""
    return {'databases': {key: {'host': HOST, 'port': PORT, 'name': database_name(zone, key), 'username': user_name(zone, key),
                                'password': {'value': passwords[key]}} for key in DATABASES}}


def scram_matches(verifier, password):
    """True when the SCRAM-SHA-256 verifier of pg_authid belongs to the password (RFC 5802 StoredKey)."""
    match = re.fullmatch(r'SCRAM-SHA-256\$(\d+):([^$]+)\$([^:]+):(.+)', verifier or '')
    if not match:
        return False
    iterations, salt, stored = int(match.group(1)), base64.b64decode(match.group(2)), base64.b64decode(match.group(3))
    salted = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
    client = hmac.new(salted, b'Client Key', hashlib.sha256).digest()
    return hmac.compare_digest(hashlib.sha256(client).digest(), stored)


def quote(name):
    if not re.fullmatch(r'[a-z0-9_]+', name):
        raise ValueError(f'{name!r} is not a database or user name of a zone')
    return f'"{name}"'


def literal(text):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', text):
        raise ValueError('a password of a zone database user has a character other than a letter, a digit, _, . or -')
    return f"'{text}'"


# ----------------------------------------------------------------------------------------------------------------------
# Shared server


def shared():
    import shared as module
    return module


def server_sql(sql, database='postgres', check=True):
    return shared().postgresql_sql(sql, database=database, check=check)


def rows(text):
    return [line.split('\t') for line in text.splitlines() if line.strip()]


def read_state(zone):
    """The users, the databases and the catalog rights of a zone on the shared server, and the PUBLIC rights of the
    server databases."""
    names = [user_name(zone, k) for k in DATABASES]
    databases = [database_name(zone, k) for k in DATABASES] + list(SERVER_DATABASES)
    found = rows(server_sql(
        "SELECT 'user', rolname, coalesce(rolpassword, ''), rolconnlimit::text, rolcanlogin::text, "
        "(rolcreatedb OR rolcreaterole OR rolsuper)::text FROM pg_authid WHERE rolname = ANY(ARRAY[%s]::text[]);\n"
        "SELECT 'database', datname, pg_get_userbyid(datdba), coalesce(datacl::text, ''), '', '' FROM pg_database "
        "WHERE datname = ANY(ARRAY[%s]::text[]);\n" % (', '.join(f"'{n}'" for n in names),
                                                      ', '.join(f"'{n}'" for n in databases))))
    users = {r[1]: {'verifier': r[2], 'limit': int(r[3]), 'login': r[4] == 'true', 'rights': r[5] == 'true'}
             for r in found if r[0] == 'user'}
    present = {r[1]: {'owner': r[2], 'acl': r[3]} for r in found if r[0] == 'database'}
    catalogs = {}
    own = [d for d in databases[:len(DATABASES)] if d in present]
    if own:
        script = ''.join(f'\\connect {quote(d)}\nSELECT {literal(d)}, relname, coalesce(relacl::text, \'\') FROM pg_class '
                         f'WHERE relnamespace = \'pg_catalog\'::regnamespace AND relname = ANY(ARRAY[{", ".join(repr(c) for c in HIDDEN)}]);\n'
                         for d in own)
        for database, relname, acl in rows(server_sql(script)):
            catalogs.setdefault(database, {})[relname] = acl
    return users, present, catalogs


def public_access(acl):
    """True when an ACL of a database or a catalog gives PUBLIC a right. An empty ACL is the default, which does."""
    return not acl or bool(re.search(r'(^|[{,])=[a-zA-Z]+/', acl))


def holds(acl, user, right='r'):
    match = re.search(r'(^|[{,])"?' + re.escape(user) + r'"?=([a-zA-Z]*)/', acl or '')
    return bool(match) and right in match.group(2)


def statements(zone, passwords, state):
    """(statements on the server, {database: catalog statements}, changes) that bring the zone to its wanted form."""
    users, present, catalogs = state
    server, inside, changed = [], {}, []
    for database in SERVER_DATABASES:
        if database in present and public_access(present[database]['acl']):
            server.append(f'REVOKE ALL ON DATABASE {quote(database)} FROM PUBLIC;')
            changed.append(f'no connection of PUBLIC to {database}')
    for key in DATABASES:
        user, database, limit = user_name(zone, key), database_name(zone, key), connection_limit(key)
        found = users.get(user)
        if found is None:
            server.append(f'CREATE ROLE {quote(user)} LOGIN NOCREATEDB NOCREATEROLE CONNECTION LIMIT {limit} '
                          f'PASSWORD {literal(passwords[key])};')
            changed.append(f'user {user}')
        else:
            if not scram_matches(found['verifier'], passwords[key]):
                server.append(f'ALTER ROLE {quote(user)} PASSWORD {literal(passwords[key])};')
                changed.append(f'password of {user}')
            if found['limit'] != limit or not found['login'] or found['rights']:
                server.append(f'ALTER ROLE {quote(user)} LOGIN NOCREATEDB NOCREATEROLE CONNECTION LIMIT {limit};')
                changed.append(f'login and connection limit of {user}')
        if database not in present:
            server.append(f'CREATE DATABASE {quote(database)} OWNER {quote(user)} {CREATE_OPTIONS.get(key, "")}'.rstrip() + ';')
            server.append(f'REVOKE ALL ON DATABASE {quote(database)} FROM PUBLIC;')
            changed.append(f'database {database}')
        else:
            if present[database]['owner'] != user:
                server.append(f'ALTER DATABASE {quote(database)} OWNER TO {quote(user)};')
                changed.append(f'owner of {database}')
            if public_access(present[database]['acl']):
                server.append(f'REVOKE ALL ON DATABASE {quote(database)} FROM PUBLIC;')
                changed.append(f'no connection of PUBLIC to {database}')
        acls = catalogs.get(database, {})
        own = []
        for catalog in HIDDEN:
            acl = acls.get(catalog)
            if database not in present or public_access(acl):
                own.append(f'REVOKE SELECT ON pg_catalog.{catalog} FROM PUBLIC;')
            if catalog in READERS.get(key, ()) and (database not in present or not holds(acl, user)):
                own.append(f'GRANT SELECT ON pg_catalog.{catalog} TO {quote(user)};')
        if own:
            inside[database] = own
            changed.append(f'catalog rights in {database}')
    return server, inside, changed


def ensure(zone, passwords):
    """Create the users and the databases of a zone on the shared server, with their rights. Only a missing or a
    different part changes, so an unchanged zone changes nothing. Return the changes. No output names a password."""
    server, inside, changed = statements(zone, passwords, read_state(zone))
    if server:
        server_sql('\n'.join(server) + '\n')
    if inside:
        server_sql(''.join(f'\\connect {quote(d)}\n' + '\n'.join(s) + '\n' for d, s in inside.items()))
    return changed


def drop_databases(zone, keys):
    """Drop databases of a zone on the shared server with their connections. ensure() creates them again empty."""
    server_sql(''.join(f'DROP DATABASE IF EXISTS {quote(database_name(zone, key))} WITH (FORCE);\n' for key in keys))


# ----------------------------------------------------------------------------------------------------------------------
# The PostgreSQL of a zone of an earlier version


def kubectl(*args, input=None, check=True):
    r = subprocess.run(['kubectl', '--kubeconfig', str(settings.KUBECONFIG), *args], input=input, text=True, capture_output=True)
    if check and r.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:4])} failed: {r.stderr.strip()[-400:]}')
    return r.stdout


def zone_server(zone):
    """True when the PostgreSQL pod of the zone namespace runs."""
    return kubectl('-n', zone, 'get', 'pod', ZONE_POD, '--ignore-not-found', '-o', 'jsonpath={.status.phase}').strip() == 'Running'


def zone_server_installed(zone):
    return bool(kubectl('-n', zone, 'get', 'statefulset', 'postgresql', '--ignore-not-found', '-o', 'name').strip())


def zone_exec(zone):
    return ['kubectl', '--kubeconfig', str(settings.KUBECONFIG), '-n', zone, 'exec', '-i', ZONE_POD, '-c', 'postgresql']


def shared_exec():
    return ['kubectl', '--kubeconfig', str(settings.KUBECONFIG), '-n', STORES_NS, 'exec', '-i',
            shared().ready_pod('postgresql'), '-c', 'postgresql']


def zone_sql(zone, sql, database='postgres', check=True):
    """Run SQL from stdin as the superuser of the zone server through its local socket."""
    import podexec
    r = podexec.call(zone_exec(zone), ['psql', '-U', 'postgres', '-d', database, '-v', 'ON_ERROR_STOP=1', '-X', '-q', '-At',
                                       '-F', '\t'], sql, timeout=900)
    if check and r.returncode:
        raise SystemExit(f'the PostgreSQL of {zone} refused the statements: {r.stderr.strip()[-600:]}')
    return r.stdout


# The row count of each table of a database, as rows (table, count).
COUNTS = ("SELECT n.nspname || '.' || c.relname, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', "
          "n.nspname, c.relname), false, true, '')))[1]::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
          "WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
          "AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1;\n")


def counts(text):
    return {table: int(count) for table, count in rows(text)}


def zone_counts(zone):
    """{database key: {table: rows}} of the zone server."""
    present = {r[0] for r in rows(zone_sql(zone, 'SELECT datname FROM pg_database;\n'))}
    return {key: counts(zone_sql(zone, COUNTS, DATABASES[key][0])) for key in DATABASES if DATABASES[key][0] in present}


def shared_counts(zone, keys=None):
    return {key: counts(server_sql(COUNTS, database_name(zone, key))) for key in (keys or DATABASES)}


def differences(source, target):
    """The tables whose row count differs, as messages."""
    problems = []
    for key in sorted(set(source) | set(target)):
        a, b = source.get(key, {}), target.get(key, {})
        problems += [f'{database_key_name(key)} {table}: the zone server has {a.get(table)} rows, the shared server {b.get(table)}'
                     for table in sorted(set(a) | set(b)) if a.get(table) != b.get(table)]
    return problems


def database_key_name(key):
    return DATABASES.get(key, (key,))[0]


def copy_database(zone, key, folder):
    """Copy one database of the zone server into its empty database on the shared server, as its new user."""
    import podexec
    source, target, user = DATABASES[key][0], database_name(zone, key), user_name(zone, key)
    dump = Path(folder) / f'{source}.dump'
    with open(dump, 'wb') as out, tempfile.TemporaryFile() as errors:
        code = podexec.run(zone_exec(zone), ['pg_dump', '-U', 'postgres', '-Fc', '--no-owner', '--no-acl', '-d', source],
                           stdout=out, stderr=errors, timeout=1800)
        errors.seek(0)
        if code:
            raise SystemExit(f'pg_dump of {source} in {zone} failed: {errors.read().decode(errors="replace").strip()[-400:]}')
    with tempfile.TemporaryFile() as errors:
        code = podexec.run(shared_exec(), ['pg_restore', '-U', 'postgres', '--no-owner', '--no-acl', f'--role={user}',
                                           '--exit-on-error', '--single-transaction', '-d', target], [dump],
                           stderr=errors, timeout=1800)
        errors.seek(0)
        if code:
            raise SystemExit(f'pg_restore of {source} of {zone} into {target} failed: '
                             f'{errors.read().decode(errors="replace").strip()[-400:]}')
    return dump.stat().st_size


def nextcloud_config(zone, passwords):
    """Write the shared server into the Nextcloud configuration of the copied database. Nextcloud loads config.php from
    this row at its start and connects with its database fields. The value is never printed."""
    table, name = NEXTCLOUD_CONFIG
    database = database_name(zone, 'nextcloud')
    text = server_sql(f"SELECT value FROM {table} WHERE name = '{name}';\n", database).strip()
    if not text:
        return False
    config = json.loads(text)
    wanted = {'dbhost': f'{HOST}:{PORT}', 'dbname': database, 'dbuser': user_name(zone, 'nextcloud'),
              'dbpassword': passwords['nextcloud']}
    if all(config.get(k) == v for k, v in wanted.items()):
        return False
    config.update(wanted)
    value = json.dumps(config, separators=(',', ':'))
    if '$hoover$' in value:
        raise SystemExit('the Nextcloud configuration holds the quote mark of the update. Update it by hand.')
    server_sql(f"UPDATE {table} SET value = $hoover${value}$hoover$ WHERE name = '{name}';\n", database)
    return True


def record_path(zone):
    return settings.PRIVATE / 'zones' / zone / RECORD


def write_record(zone, record):
    """Write the record into the secret store and a copy into the zone folder (objectstore.write_record())."""
    import objectstore
    objectstore.write_record(zone, record, RECORD)


def read_record(zone):
    import objectstore
    return objectstore.read_record(zone, RECORD)


def step(name, **fields):
    print(json.dumps({'at': time.strftime('%H:%M:%S'), 'step': name, **fields}), flush=True)


def logins(zone, allowed):
    """Give the users of the zone server their login, or take it and end their sessions."""
    names = ', '.join(f"'{user}'" for _, user in DATABASES.values())
    sql = ''.join(f'ALTER ROLE {quote(user)} {"LOGIN" if allowed else "NOLOGIN"};\n' for _, user in DATABASES.values()
                  if user in {r[0] for r in rows(zone_sql(zone, f'SELECT rolname FROM pg_roles WHERE rolname IN ({names});\n'))})
    if not allowed:
        sql += f'SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE usename IN ({names});\n'
    return zone_sql(zone, sql)


def volume(zone):
    return kubectl('-n', zone, 'get', 'pvc', ZONE_CLAIM, '--ignore-not-found', '-o', 'jsonpath={.spec.volumeName}').strip()


def can_keep_volumes():
    return kubectl('auth', 'can-i', 'patch', 'persistentvolumes', check=False).strip() == 'yes'


def move(zone, passwords):
    """Copy the databases of the zone server into the shared server, check the row counts, and keep the volume of the
    zone server (steps 1 to 6 of the module text). Return the record. The caller sets postgresql = site and runs the
    waves."""
    if not zone_server(zone):
        raise SystemExit(f'{zone} has no running PostgreSQL, and the move of its databases needs it. Start it and run '
                         'zone.py apply again.')
    ensure(zone, passwords)
    record = {'zone': zone, 'switch_started': time.time()}
    logins(zone, False)
    step('postgresql-switch', zone=zone, result='the zone users have no login, the copy starts')
    try:
        source = zone_counts(zone)
        unknown = sorted(set(DATABASES) - set(source))
        record['bytes'] = {}
        # An earlier move that stopped can have left rows, so each database starts empty.
        drop_databases(zone, source)
        ensure(zone, passwords)
        with tempfile.TemporaryDirectory(prefix=f'postgresql-{zone}-') as folder:
            for key in source:
                record['bytes'][DATABASES[key][0]] = copy_database(zone, key, folder)
        record['copied'] = time.time()
        target = shared_counts(zone, list(source))
        record['databases'] = {DATABASES[k][0]: {'tables': len(source[k]), 'rows': sum(source[k].values()),
                                                 'shared_rows': sum(target.get(k, {}).values())} for k in source}
        record['missing_in_zone'] = [DATABASES[k][0] for k in unknown]
        problems = differences(source, target)
        if problems:
            raise SystemExit(f'the copy of the databases of {zone} differs: {"; ".join(problems[:20])}. The zone stays on '
                             'its own PostgreSQL.')
        record['nextcloud_config'] = nextcloud_config(zone, passwords)
    except BaseException:
        logins(zone, True)
        step('postgresql-switch', zone=zone, result='ended without a move, the applications use the zone PostgreSQL again')
        raise
    record['checked'] = time.time()
    name = volume(zone)
    record['volumes'] = [name] if name else []
    for item in record['volumes']:
        kubectl('patch', 'pv', item, '-p', json.dumps({'metadata': {'labels': {LABEL: zone}},
                                                       'spec': {'persistentVolumeReclaimPolicy': 'Retain'}}))
    write_record(zone, record)
    step('postgresql-copy', zone=zone, databases=record['databases'],
         seconds=round(record['checked'] - record['switch_started'], 1))
    return record


def finish(zone):
    """Restart the workloads that name the shared server or read the Nextcloud configuration and started before the
    switch, delete the claim of the removed zone server, and record the end of the switch (step 8). A zone without an
    open switch in its record is left as it is."""
    import objectstore
    record = read_record(zone)
    if not record or record.get('switch_ended'):
        return None
    record['waves_done'] = time.time()
    record['restarted'] = objectstore.restart_holders(zone, HOST, record['switch_started'])
    if not zone_server_installed(zone):
        kubectl('-n', zone, 'delete', 'pvc', ZONE_CLAIM, '--ignore-not-found', '--wait=false')
        record['claim_deleted'] = ZONE_CLAIM
    record['switch_ended'] = time.time()
    record['pause_seconds'] = round(record['switch_ended'] - record['switch_started'], 1)
    write_record(zone, record)
    step('postgresql-switch', zone=zone, result='done', restarted=record['restarted'], pause_seconds=record['pause_seconds'])
    return record


def drop_volume(zone):
    """Delete the volume of the zone server that a move of a zone on the shared server kept."""
    import objectstore
    import zonestate
    entry = zonestate.load()['zones'].get(zone)
    if entry is not None and not on_shared(entry):
        raise SystemExit(f'{zone} still uses its own PostgreSQL, so its volume stays.')
    if entry is not None and zone_server_installed(zone):
        raise SystemExit(f'{zone} still runs its own PostgreSQL. Run zone.py apply {zone} first.')
    kubectl('-n', zone, 'delete', 'pvc', ZONE_CLAIM, '--ignore-not-found', '--wait=true', check=False)
    return objectstore.drop_kept(zone, label=LABEL, record=RECORD)


def zone_passwords(zone):
    import secretstore
    passwords = secretstore.zone_secrets(zone).get('postgresql')
    if not passwords:
        raise SystemExit(f'the zone secrets have no PostgreSQL passwords of {zone}. Run zone.py apply {zone}.')
    return passwords


def main(argv):
    if len(argv) != 2 or argv[0] not in ('show', 'check', 'drop-volume'):
        raise SystemExit(__doc__)
    command, zone = argv
    import zones
    if not zones.ZONE_NAME.fullmatch(zone):
        raise SystemExit(f'{zone!r} is not a zone id.')
    settings.use_kubeconfig()
    if command == 'drop-volume':
        print(json.dumps({'zone': zone, 'dropped': drop_volume(zone)}))
        return
    if command == 'show':
        names = ', '.join(f"'{database_name(zone, k)}'" for k in DATABASES)
        found = rows(server_sql(f'SELECT datname, pg_get_userbyid(datdba), pg_database_size(datname) FROM pg_database '
                                f'WHERE datname IN ({names}) ORDER BY 1;\n'))
        print(json.dumps({'zone': zone, 'host': HOST, 'databases': {d: {'owner': o, 'bytes': int(b)} for d, o, b in found}},
                         indent=1))
        return
    if not zone_server(zone):
        raise SystemExit(f'{zone} has no running PostgreSQL to compare with.')
    source = zone_counts(zone)
    target = shared_counts(zone, list(source))
    problems = differences(source, target)
    print(json.dumps({'zone': zone, 'tables': {DATABASES[k][0]: len(v) for k, v in source.items()}, 'differences': problems},
                     indent=1))
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main(sys.argv[1:])
