"""The renames of a Compose import: from the Compose storage names to the storage names of the zone. Standard library only.

A Compose install has the default storage identity of main_services/processing/tasks/storage_identity.json: the
ClickHouse databases Hoover4_Processing and Hoover4_Collection_<collection>, Manticore tables without a prefix, the
system bucket hoover4-system and the collection buckets hoover4-c-<collection>. The zone derives its names from the
zone id (../config.py Hoover), for example zone_a_Processing, zone_a_<table> and zone-a-c-<collection>.

The functions here compute the renames and the statements from the record of the source. They run no command.
  databases  RENAME DATABASE for each Hoover database. The databases use the Atomic engine, so the rename changes
             metadata only.
  tables     ALTER TABLE <table> RENAME <prefix><table> for each table of both Manticore servers.
  buckets    the aliases of each Garage bucket: the new global or local alias, then the removal of the old alias. A
             collection bucket has a local alias of the access key that created it.
  s3 paths   rows keep object locations as s3://<bucket>/<key>. Each String column whose name ends with s3_path gets an
             UPDATE of the bucket part. A column of the sorting key cannot change, so it stops the import.
  datasets   the dataset rows keep the container path of their dataset mount, for example /uploads/x. A cluster
             mount is /data/<mount name>, so dataset_path gets the new prefix.
"""
import json
from pathlib import Path

STORAGE_IDENTITY = Path(__file__).resolve().parents[2] / 'main_services/processing/tasks/storage_identity.json'
S3_COLUMN_SUFFIX = 's3_path'


class RenameError(ValueError):
    """The record holds a name that the import cannot rename. The message names it."""


def compose_identity():
    """The storage names of a Compose install: the defaults of storage_identity.json."""
    settings = json.loads(STORAGE_IDENTITY.read_text())['settings']
    return {k: settings[k]['default'] for k in ('clickhouse_database_prefix', 'manticore_table_prefix', 'system_bucket',
                                                'collection_bucket_prefix')}


def zone_identity(hoover):
    return {k: getattr(hoover, k) for k in ('clickhouse_database_prefix', 'manticore_table_prefix', 'system_bucket',
                                            'collection_bucket_prefix')}


def quote(text):
    """A ClickHouse string literal."""
    return "'" + str(text).replace('\\', '\\\\').replace("'", "\\'") + "'"


def ident(name):
    """A ClickHouse identifier."""
    return '`' + str(name).replace('`', '``') + '`'


def database_renames(databases, hoover, source=None):
    """[(old, new)] of each Hoover database of the source. Other databases, such as default, keep their names."""
    source, target = source or compose_identity(), zone_identity(hoover)
    old = source['clickhouse_database_prefix']
    new = target['clickhouse_database_prefix']
    out = []
    for name in sorted(set(databases)):
        if name == f'{old}_Processing' or name.startswith(f'{old}_Collection_'):
            out.append((name, new + name[len(old):]))
    return out


def table_renames(tables, hoover, source=None):
    """[(old, new)] of each Manticore table of one server."""
    source, target = source or compose_identity(), zone_identity(hoover)
    old, new = source['manticore_table_prefix'], target['manticore_table_prefix']
    out = []
    for name in sorted(set(tables)):
        if not name.startswith(old):
            raise RenameError(f'the Manticore table {name} does not have the Compose prefix {old!r}.')
        out.append((name, new + name[len(old):]))
    return out


def bucket_name(alias, hoover, source=None):
    """The zone name of a Compose bucket alias, or None for an alias outside the Compose names."""
    source, target = source or compose_identity(), zone_identity(hoover)
    if alias == source['system_bucket']:
        return target['system_bucket']
    if alias.startswith(source['collection_bucket_prefix']):
        return target['collection_bucket_prefix'] + alias[len(source['collection_bucket_prefix']):]
    return None


def bucket_renames(buckets, hoover, source=None):
    """The alias changes of the Garage buckets: [{bucketId, old, new, accessKeyId}], accessKeyId empty for a global alias.

    buckets is the answer of the admin endpoint ListBuckets: [{id, globalAliases, localAliases: [{accessKeyId, alias}]}].
    """
    out, unknown = [], []
    for bucket in sorted(buckets, key=lambda b: b['id']):
        aliases = [(a, '') for a in bucket.get('globalAliases') or []]
        aliases += [(a['alias'], a['accessKeyId']) for a in bucket.get('localAliases') or []]
        for alias, key in sorted(aliases):
            new = bucket_name(alias, hoover, source)
            if new is None:
                unknown.append(alias)
                continue
            out.append({'bucketId': bucket['id'], 'old': alias, 'new': new, 'accessKeyId': key})
    if unknown:
        raise RenameError(f'the Garage buckets {", ".join(sorted(unknown))} do not have a Compose bucket name.')
    return out


def alias_request(change, which):
    """The JSON body of AddBucketAlias (which = new) or RemoveBucketAlias (which = old)."""
    body = {'bucketId': change['bucketId']}
    if change['accessKeyId']:
        body.update(localAlias=change[which], accessKeyId=change['accessKeyId'])
    else:
        body['globalAlias'] = change[which]
    return body


def bucket_map(changes):
    """{old bucket name: new bucket name} of the alias changes."""
    return {c['old']: c['new'] for c in changes}


def s3_path_updates(columns, buckets):
    """The UPDATE statements of the s3 path columns.

    columns holds rows (database, table, column, in_sorting_key) of the renamed databases. buckets is
    {old bucket: new bucket}. A column without a row of an old bucket stays as it is, because the WHERE clause matches
    the old prefixes only. A second run therefore changes nothing.
    """
    if not buckets:
        return []
    statements = []
    pairs = sorted(buckets.items())
    for database, table, column, in_key in sorted(columns):
        if not column.endswith(S3_COLUMN_SUFFIX):
            continue
        if in_key:
            raise RenameError(f'the column {database}.{table}.{column} is part of the sorting key, so its bucket names '
                              'cannot change.')
        c = ident(column)
        cases = ', '.join(f"startsWith({c}, {quote(f's3://{old}/')}), concat({quote(f's3://{new}/')}, "
                          f"substring({c}, {len(f's3://{old}/') + 1}))" for old, new in pairs)
        where = ' OR '.join(f"startsWith({c}, {quote(f's3://{old}/')})" for old, _ in pairs)
        statements.append(f'ALTER TABLE {ident(database)}.{ident(table)} UPDATE {c} = multiIf({cases}, {c}) WHERE {where}')
    return statements


def dataset_paths(mounts):
    """{Compose container path: cluster path} of the dataset mounts. A cluster mount is /data/<mount name>."""
    return {m['container_path'].rstrip('/') or '/': f'/data/{m["name"]}' for m in mounts
            if (m['container_path'].rstrip('/') or '/') != f'/data/{m["name"]}'}


def dataset_path_update(database, paths):
    """The UPDATE statement of the dataset rows, or None. A path that equals a mount path or is below it moves."""
    if not paths:
        return None
    c = ident('dataset_path')
    cases, matches = [], []
    # The longest container path first, so a nested mount path wins over its parent.
    for old, new in sorted(paths.items(), key=lambda p: (-len(p[0]), p[0])):
        cases.append(f'{c} = {quote(old)}, {quote(new)}')
        cases.append(f"startsWith({c}, {quote(old + '/')}), concat({quote(new + '/')}, substring({c}, {len(old) + 2}))")
        matches.append(f"{c} = {quote(old)} OR startsWith({c}, {quote(old + '/')})")
    return (f'ALTER TABLE {ident(database)}.{ident("dataset")} UPDATE {c} = multiIf({", ".join(cases)}, {c}) '
            f'WHERE {" OR ".join(matches)}')


def renamed_counts(counts, databases):
    """The ClickHouse row counts {database.table: rows} under the new database names."""
    mapping = dict(databases)
    out = {}
    for key, value in counts.items():
        database, table = key.split('.', 1)
        out[f'{mapping.get(database, database)}.{table}'] = value
    return out


def renamed_tables(counts, tables):
    mapping = dict(tables)
    return {mapping.get(k, k): v for k, v in counts.items()}


def bucket_aliases(buckets):
    """{bucket id: sorted aliases} of a ListBuckets answer, with the access key of each local alias."""
    out = {}
    for bucket in buckets:
        aliases = list(bucket.get('globalAliases') or [])
        aliases += [f'{a["alias"]}@{a["accessKeyId"]}' for a in bucket.get('localAliases') or []]
        out[bucket['id']] = sorted(aliases)
    return out


def renamed_aliases(buckets, changes):
    """The bucket aliases that the target must have after the alias changes."""
    by_id = {}
    for c in changes:
        by_id.setdefault(c['bucketId'], {})[c['old'] + (f'@{c["accessKeyId"]}' if c['accessKeyId'] else '')] = \
            c['new'] + (f'@{c["accessKeyId"]}' if c['accessKeyId'] else '')
    return {bid: sorted(by_id.get(bid, {}).get(a, a) for a in aliases) for bid, aliases in bucket_aliases(buckets).items()}
