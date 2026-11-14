"""The store users of the Hoover services of a zone.

Each service that uses a store has its own ClickHouse user and Manticore user with its own random password. A user
name is the zone prefix and the service, for example zone_a_mcp_browser. creds.py writes the passwords into the
Secret hoover-stores of the zone namespace. ../setup.py creates the users in the shared ClickHouse and in the Manticore
daemons of the zone, and copies the passwords into the Secret hoover-runtime of the Hoover namespace.
Garage has no grant on a bucket that is created later, and the processing code creates a bucket for each new
collection. The services that use the collection buckets therefore share the zone key, which can create buckets.
Each other Garage user has its own key with access to the system bucket only.
"""

# The Compose name of each service without the hoover4- prefix, and its stores. clickhouse names the grants: zone
# gives the grants of the zone user, browser gives only the tables of the page citations. garage is collections for
# the zone key, or system for an own key on the system bucket.
SERVICES = {
    'website': {'clickhouse': 'zone', 'manticore': 'write', 'garage': 'collections'},
    'worker': {'clickhouse': 'zone', 'manticore': 'write', 'garage': 'collections'},
    'ops': {'clickhouse': 'zone', 'manticore': 'write', 'garage': 'collections'},
    'ocr-pdf': {'garage': 'collections'},
    'mcp-collections': {'clickhouse': 'zone', 'manticore': 'read', 'garage': 'system'},
    # The todo server reads its tables with the ClickHouse client of the processing code.
    'mcp-todo': {'clickhouse': 'zone'},
    'internal-search-agent': {'clickhouse': 'zone'},
    'full-research-agent': {'clickhouse': 'zone'},
    'mcp-browser': {'clickhouse': 'browser', 'garage': 'system'},
}
MANTICORE_GRANTS = {'write': ('read', 'write', 'schema'), 'read': ('read',)}


def prefix(zone):
    return zone.replace('-', '_')


def user(zone, service):
    """The ClickHouse and Manticore user name of a service."""
    return f"{prefix(zone)}_{service.replace('-', '_')}"


def env_name(service):
    """The environment variable of the ClickHouse container that holds the password of a service."""
    return 'CH_PASSWORD_' + service.replace('-', '_').upper()


def garage_key(zone, service):
    """The Garage key name of a service. The collection services use the zone key."""
    return zone if SERVICES[service].get('garage') == 'collections' else f'{zone}-{service}'


def using(store):
    return [s for s, stores in SERVICES.items() if store in stores]


def zone_grants(zone):
    """The ClickHouse grants of the zone user: the database <prefix> and every database <prefix>_*. A quoted name
    would make the * of the wildcard grant a literal character, so the names stay unquoted."""
    p = prefix(zone)
    rights = 'SELECT, INSERT, ALTER, CREATE DATABASE, CREATE TABLE, CREATE VIEW, DROP TABLE, DROP VIEW, TRUNCATE, OPTIMIZE, SHOW'
    return [f'GRANT {rights} ON {p}.*', f'GRANT {rights.replace("DROP TABLE", "DROP DATABASE, DROP TABLE")} ON {p}_*.*']


def clickhouse_grants(zone, service):
    p = prefix(zone)
    if SERVICES[service]['clickhouse'] == 'zone':
        return zone_grants(zone)
    # The browser stores page captures and citations, reads the chat rows of its own session and writes telemetry.
    db = f'{p}_Processing'
    return [f'GRANT SELECT, INSERT ON {db}.chat_artifacts', f'GRANT SELECT ON {db}.chat_messages',
            f'GRANT SELECT ON {db}.agent_run_messages', f'GRANT INSERT ON {db}.ai_service_telemetry']

