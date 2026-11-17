#!/usr/bin/env python3
"""Check that a zone cannot read or write the data of another zone in the shared stores of the site.

The probes run Python in the pods of hoover-<zone> with the credentials of each pod: the operations pod (ClickHouse
user, Garage key, Temporal key, Manticore write user and proxy credential), the collections server (Manticore read
user) and the schema proxy (Manticore schema user). Both zones need the collection demo with its Manticore tables, so
<prefix>_demo_vfs exists in each zone.
- ClickHouse: the user reads its own database <prefix>_Processing. It cannot read, write or drop a table of
  <other prefix>_Processing, create a database with the other prefix, or list the other databases.
- ClickHouse backup: the operations user backs up a table of its own database into the export bucket of its zone
  (CLICKHOUSE_BACKUP_S3_URL) and reads that row of system.backups. It cannot back up a table of the other zone or back
  up to a file of the server volume. It cannot write into or restore from the export bucket of the other zone, or
  restore into a database of the other zone. It reads no row of system.backups with another prefix. The probe removes
  its archive.
- Garage: the key lists its own system bucket. It cannot list, read or write the system bucket of the other zone, or
  list its export bucket, and the bucket list holds no bucket of the other zone.
- Manticore, write user: it reads and changes rows of its own tables. It cannot read or change a table of the other
  zone, and it cannot create, alter or drop a table, also not a distributed table that names a table of the other zone.
- Manticore, read user on the read-only listener 9309 and on 9308: it reads its own tables. It cannot read a table
  of the other zone, change a row, or create a distributed table.
- Manticore schema proxy: with the proxy credential it creates a table of its own zone. It refuses a table of the
  other zone, an unknown operation such as a distributed table, and a request without the credential. export_tables
  and import_tables refuse an export folder outside the backup root of the zone, a table argument, and a manifest
  whose artifact path leaves the export folder. The operations pod cannot reach the file service of the text daemon.
- Manticore status credential of the website: it reads the operation status, and the proxy refuses every schema
  operation and the import with it.
- Manticore file service, from the schema proxy with the schema user: it reads a file of an own table and writes and
  removes an own import stage. It refuses a file of a table of the other zone, and a request without credentials.
- Manticore, schema user (only the proxy holds it): it cannot read, change or drop a table of the other zone. The case
  that creates a distributed table over a table of the other zone and reads it through that table reports the result
  without a pass or fail: Manticore 29.9 allows it, so no zone service holds this user. The probe drops the table.
- Temporal: with the key of the pod (TEMPORAL_API_KEY), the zone describes its namespace, lists, starts, signals and
  terminates a probe workflow in it. In the namespace of the other zone it cannot describe, list, start, signal,
  cancel, terminate or read a history, and it cannot create or delete a namespace or add a search attribute. A request
  without a key is refused. Temporal answers a refused request with PERMISSION_DENIED.
- Garage bucket names: a key that can create buckets can create a bucket with the name prefix of another zone. Garage
  gives such a bucket a local alias of the creating key, so the names of the other zone stay free. The case reports
  the result without a pass or fail, and the probe deletes the bucket at once.
- Processing pools of the site (../hoover/pools.py): no pool pod has a store credential, a store address, a zone
  identity, a claim, an NFS or a host folder, and the namespace hoover-pools holds no Secret except the GPU token of
  the pools. The searchable-PDF builder, called from a worker of the zone with an object key of the other zone, reads
  no object. After the requests of an ingest end, no pool keeps a file in its temporary folders (TEMP_FOLDERS) that is
  younger than the start of its container (START_SECONDS).
Each line of the output is JSON. The check prints no credential. It exits with 1 when a case has another result than
expected.
Usage: tenant-isolation-check.py <zone> <other zone>
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings  # noqa: E402

K = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG)]
PYTHON = '/opt/pysetup/.venv/bin/python3'
# The Manticore read user of the collections server, over HTTP. 9309 is the read-only listener.
READ_PROBE = r'''
import json, os, sys, urllib.parse, urllib.request, urllib.error
zone, other = sys.argv[1], sys.argv[2]
mine, theirs = zone.replace('-', '_') + '_', other.replace('-', '_') + '_'
import base64
auth = 'Basic ' + base64.b64encode(f"{os.environ['MANTICORE_USER']}:{os.environ['MANTICORE_PASSWORD']}".encode()).decode()
def mt(port, sql):
    req = urllib.request.Request(f'http://manticore:{port}/sql?mode=raw', data=urllib.parse.urlencode({'query': sql}).encode(),
                                 headers={'Authorization': auth})
    try:
        body = urllib.request.urlopen(req, timeout=20).read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
    error = ''
    try:
        data = json.loads(body)
        error = data.get('error', '') if isinstance(data, dict) else (data[0].get('error', '') if data else '')
    except ValueError:
        error = body
    if not error:
        return 'allowed', body[:120]
    return ('refused' if 'Permission denied' in error or 'read-only' in error else 'error'), error[:160]
cases = [
    ('manticore', 'read user reads own table on 9309', 'allowed', mt(9309, f'SELECT count(*) FROM {mine}demo_vfs')),
    ('manticore', 'read user reads other table on 9309', 'refused', mt(9309, f'SELECT count(*) FROM {theirs}demo_vfs')),
    ('manticore', 'read user changes own rows on 9309', 'refused', mt(9309, f'DELETE FROM {mine}demo_vfs WHERE id = 1 AND id = 2')),
    ('manticore', 'read user changes own rows on 9308', 'refused', mt(9308, f'DELETE FROM {mine}demo_vfs WHERE id = 1 AND id = 2')),
    ('manticore', 'read user creates distributed table on 9309', 'refused',
     mt(9309, f"CREATE TABLE {mine}isolation_probe_d type='distributed' local='{theirs}demo_vfs'")),
    ('manticore', 'read user creates distributed table on 9308', 'refused',
     mt(9308, f"CREATE TABLE {mine}isolation_probe_d type='distributed' local='{theirs}demo_vfs'")),
    ('manticore', 'read user leaves read-only on 9309', 'refused', mt(9309, 'SET ro=0')),
]
for store, case, expected, (result, detail) in cases:
    print(json.dumps({'store': store, 'case': case, 'expected': expected, 'result': result, 'detail': detail,
                      'pass': result == expected}))
'''
# The Manticore schema user, which only the schema proxy holds.
SCHEMA_PROBE = r'''
import json, os, sys
import mysql.connector
zone, other = sys.argv[1], sys.argv[2]
mine, theirs = zone.replace('-', '_') + '_', other.replace('-', '_') + '_'
def mt(sql):
    try:
        cnx = mysql.connector.connect(host=os.environ['MANTICORE_HOST'], port=9306, user=os.environ['MANTICORE_USER'],
                                      password=os.environ['MANTICORE_PASSWORD'], connection_timeout=10)
        try:
            cur = cnx.cursor()
            cur.execute(sql)
            return 'allowed', str(cur.fetchall() if cur.with_rows else [])[:120]
        finally:
            cnx.close()
    except mysql.connector.Error as e:
        return ('refused' if 'Permission denied' in str(e) else 'error'), str(e)[:160]
cases = [
    ('manticore', 'schema user reads other table', 'refused', mt(f'SELECT count(*) FROM {theirs}demo_vfs')),
    ('manticore', 'schema user writes other table', 'refused', mt(f'DELETE FROM {theirs}demo_vfs WHERE id = 1 AND id = 2')),
    ('manticore', 'schema user drops other table', 'refused', mt(f'DROP TABLE IF EXISTS {theirs}demo_vfs')),
    ('manticore', 'schema user creates table with other prefix', 'refused', mt(f'CREATE TABLE {theirs}isolation_probe (title text)')),
]
created = mt(f"CREATE TABLE {mine}isolation_probe_d type='distributed' local='{theirs}demo_vfs'")
read = mt(f'SELECT count(*) FROM {mine}isolation_probe_d') if created[0] == 'allowed' else ('refused', 'not created')
mt(f'DROP TABLE IF EXISTS {mine}isolation_probe_d')
cases += [('manticore', 'schema user creates distributed table over other table', None, created),
          ('manticore', 'schema user reads other table through it', None, read)]
import base64, secrets, shutil, urllib.error, urllib.request
auth = 'Basic ' + base64.b64encode(f"{os.environ['MANTICORE_USER']}:{os.environ['MANTICORE_PASSWORD']}".encode()).decode()
def files(method, path, body=None, header=None):
    req = urllib.request.Request(os.environ['MANTICORE_FILES_URL'] + path, method=method, data=body,
                                 headers={'Authorization': auth if header is None else header})
    try:
        return 'allowed', f'{urllib.request.urlopen(req, timeout=30).status}'
    except urllib.error.HTTPError as e:
        return ('refused' if e.code in (400, 401, 403) else 'error'), f'{e.code} {e.read().decode()[:120]}'
    except OSError as e:
        return 'error', str(e)[:120]
stage = secrets.token_hex(4)
cases += [
    ('manticore', 'file service reads own table file', 'allowed', files('GET', f'/tables/{mine}demo_vfs/{mine}demo_vfs.meta')),
    ('manticore', 'file service reads other table file', 'refused', files('GET', f'/tables/{theirs}demo_vfs/{theirs}demo_vfs.meta')),
    ('manticore', 'file service without credentials', 'refused', files('GET', f'/tables/{mine}demo_vfs/{mine}demo_vfs.meta', header='')),
    ('manticore', 'file service writes own stage', 'allowed', files('PUT', f'/stage/{stage}/{mine}probe/{mine}probe.meta', b'{}')),
    ('manticore', 'file service removes own stage', 'allowed', files('DELETE', f'/stage/{stage}')),
]
# An export folder in the backup root of the zone whose manifest names a table file of the other zone.
folder = os.path.join(os.environ.get('HOOVER4_BACKUP_ROOT', '/backups'), f'isolation-probe-{stage}')
os.makedirs(os.path.join(folder, 'manticore'))
with open(os.path.join(folder, 'manifest.json'), 'w') as handle:
    json.dump({'collectionname': 'demo', 'stores': {'manticore': {'tables': [
        {'table': f'{theirs}demo_vfs', 'path': f'../../var/lib/manticore/{theirs}demo_vfs/{theirs}demo_vfs.meta'}]}}}, handle)
req = urllib.request.Request('http://127.0.0.1:' + os.environ.get('MANTICORE_SCHEMA_PORT', '8080') + '/operation',
                             data=json.dumps({'operation': 'import_tables', 'arguments': {'collection': 'demo', 'export': os.path.basename(folder)}}).encode(),
                             headers={'Authorization': f"Bearer {os.environ['MANTICORE_SCHEMA_TOKEN']}"})
try:
    result = ('allowed', urllib.request.urlopen(req, timeout=60).read().decode()[:120])
except urllib.error.HTTPError as e:
    result = ('refused' if e.code == 400 else 'error', f'{e.code} {e.read().decode()[:120]}')
shutil.rmtree(folder, ignore_errors=True)
cases.append(('manticore', 'proxy imports a manifest that names a file of the other zone', 'refused', result))
for store, case, expected, (result, detail) in cases:
    print(json.dumps({'store': store, 'case': case, 'expected': expected, 'result': result, 'detail': detail,
                      'pass': None if expected is None else result == expected}))
'''
# The status credential of the website. The website image has bash and no Python, so the probe speaks HTTP over the
# /dev/tcp of bash.
WEB_PROBE = r'''
call() {
  exec 3<>/dev/tcp/manticore-schema/8080 || { echo 000; return; }
  printf 'POST /operation HTTP/1.0\r\nHost: manticore-schema\r\nAuthorization: Bearer %s\r\nContent-Type: application/json\r\nContent-Length: %s\r\n\r\n%s' \
    "$MANTICORE_STATUS_TOKEN" "${#1}" "$1" >&3
  head -1 <&3 | cut -d' ' -f2
  exec 3<&-
}
row() {
  code=$(call "$3")
  case "$code" in 200) result=allowed;; 401|403) result=refused;; *) result=error;; esac
  pass=false; [ "$result" = "$2" ] && pass=true
  printf '{"store": "manticore", "case": "%s", "expected": "%s", "result": "%s", "detail": "%s", "pass": %s}\n' "$1" "$2" "$result" "$code" "$pass"
}
row 'status credential reads the daemon status' allowed '{"operation": "status", "arguments": {}}'
row 'status credential creates a table' refused '{"operation": "create_vfs_table", "arguments": {"collection": "demo"}}'
row 'status credential imports tables' refused '{"operation": "import_tables", "arguments": {"collection": "demo", "export": "x"}}'
row 'status credential drops the tables of a collection' refused '{"operation": "drop_collection_tables", "arguments": {"collection": "demo"}}'
'''
PROBE = r'''
import json, os, sys, urllib.request, urllib.error
from minio import Minio
zone, other = sys.argv[1], sys.argv[2]
mine, theirs = zone.replace('-', '_') + '_Processing', other.replace('-', '_') + '_Processing'
def ch(sql):
    req = urllib.request.Request(os.environ['CLICKHOUSE_URL'] + '/', data=sql.encode(), headers={
        'X-ClickHouse-User': os.environ['CLICKHOUSE_USER'], 'X-ClickHouse-Key': os.environ['CLICKHOUSE_PASSWORD']})
    try:
        return 'allowed', urllib.request.urlopen(req, timeout=20).read().decode().strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        denied = ('ACCESS_DENIED', 'Not enough privileges', 'Forbidden', 'AccessDenied', 'Access Denied', 'allowed_path')
        return ('refused' if any(d in body for d in denied) else 'error'), body[:160]
def s3(call):
    try:
        return 'allowed', str(call())[:160]
    except Exception as e:
        code = getattr(e, 'code', type(e).__name__)
        return ('refused' if code in ('AccessDenied', 'NoSuchBucket', 'Forbidden') else 'error'), str(code)
client = Minio(os.environ['S3_ENDPOINT'].split('://')[-1], os.environ['S3_ACCESS_KEY'], os.environ['S3_SECRET_KEY'], secure=False)
cases = [
    ('clickhouse', 'own database', 'allowed', ch(f'SELECT count() FROM {mine}.collections')),
    ('clickhouse', 'read other database', 'refused', ch(f'SELECT count() FROM {theirs}.collections')),
    ('clickhouse', 'write other database', 'refused', ch(f"INSERT INTO {theirs}.server_settings (key, value) VALUES ('p4', 'x')")),
    ('clickhouse', 'drop other table', 'refused', ch(f'DROP TABLE {theirs}.server_settings')),
    ('clickhouse', 'create database with other prefix', 'refused', ch(f"CREATE DATABASE {other.replace('-', '_')}_probe")),
    ('clickhouse', 'system log of other users', 'refused', ch('SELECT count() FROM system.query_log')),
    ('clickhouse', 'list other databases', 'allowed',
     ('allowed' if other.replace('-', '_') not in ch('SHOW DATABASES')[1] else 'refused', 'listed only own databases')),
    ('garage', 'own system bucket', 'allowed', s3(lambda: len(list(client.list_objects(f'{zone}-system'))))),
    ('garage', 'list other system bucket', 'refused', s3(lambda: len(list(client.list_objects(f'{other}-system'))))),
    ('garage', 'write other system bucket', 'refused',
     s3(lambda: client.put_object(f'{other}-system', 'p4-probe', __import__('io').BytesIO(b'x'), 1))),
    ('garage', 'read other object', 'refused', s3(lambda: client.get_object(f'{other}-system', 'p4-probe').read())),
    ('garage', 'bucket list', 'allowed',
     ('allowed' if not any(b.name.startswith(other + '-') for b in client.list_buckets()) else 'refused', 'no bucket of the other zone')),
]
# The ClickHouse backup of a collection export: the operations user backs up its own databases into the export bucket
# of its zone (CLICKHOUSE_BACKUP_S3_URL) with the zone key, and reads only its own rows of system.backups.
import uuid
url = os.environ['CLICKHOUSE_BACKUP_S3_URL']
garage, own_bucket = url.rsplit('/', 1)
other_bucket, pfx, run = f'{other}-exports', zone.replace('-', '_'), uuid.uuid4().hex[:12]
def quoted(text):
    return "'" + text.replace('\\', '\\\\').replace("'", "\\'") + "'"
def target(bucket, key):
    return (f"S3({quoted(garage + '/' + bucket + '/' + key)}, {quoted(os.environ['S3_ACCESS_KEY'])}, "
            f"{quoted(os.environ['S3_SECRET_KEY'])})")
probe_key = f'isolation-probe/{run}.tar'
cases += [
    ('clickhouse', 'back up own table into own export bucket', 'allowed',
     ch(f"BACKUP TABLE {mine}.server_settings TO {target(own_bucket, probe_key)} SETTINGS id='{pfx}-isolation-{run}'")),
    ('clickhouse', 'read own row of system.backups', 'allowed',
     ch(f"SELECT status FROM system.backups WHERE id = '{pfx}-isolation-{run}'")),
    ('clickhouse', 'back up other database into own export bucket', 'refused',
     ch(f"BACKUP TABLE {theirs}.server_settings TO {target(own_bucket, f'isolation-probe/{run}-other.tar')}")),
    ('clickhouse', 'write archive into other export bucket', 'refused',
     ch(f"BACKUP TABLE {mine}.server_settings TO {target(other_bucket, f'isolation-probe/{run}.tar')} "
        f"SETTINGS id='{pfx}-isolation-{run}-b'")),
    ('clickhouse', 'back up to a file of the server volume', 'refused',
     ch(f"BACKUP TABLE {mine}.server_settings TO File('isolation-probe-{run}.tar')")),
    ('clickhouse', 'restore into other database', 'refused',
     ch(f"RESTORE TABLE {mine}.server_settings AS {theirs}.isolation_probe FROM {target(own_bucket, probe_key)}")),
    ('clickhouse', 'restore from other export bucket', 'refused',
     ch(f"RESTORE TABLE {mine}.server_settings AS {mine}.isolation_probe FROM {target(other_bucket, probe_key)}")),
]
seen = ch(f"SELECT count() FROM system.backups WHERE NOT startsWith(id, '{pfx}-')")
cases.append(('clickhouse', 'read rows of system.backups of other zones', 'refused',
              ('refused', 'no row') if seen == ('allowed', '0') else ('allowed' if seen[0] == 'allowed' else 'error', seen[1])))
ch(f'DROP TABLE IF EXISTS {mine}.isolation_probe')
for key in client.list_objects(own_bucket, prefix='isolation-probe/', recursive=True):
    client.remove_object(own_bucket, key.object_name)
cases.append(('garage', 'list other export bucket', 'refused', s3(lambda: len(list(client.list_objects(other_bucket))))))
import mysql.connector
mine_mt, theirs_mt = zone.replace('-', '_') + '_', other.replace('-', '_') + '_'
def mt(sql):
    try:
        cnx = mysql.connector.connect(host=os.environ['MANTICORE_HOST'], port=9306, user=os.environ['MANTICORE_USER'],
                                      password=os.environ['MANTICORE_PASSWORD'], connection_timeout=10)
        try:
            cur = cnx.cursor()
            cur.execute(sql)
            rows = cur.fetchall() if cur.with_rows else []
            return 'allowed', str(rows)[:120]
        finally:
            cnx.close()
    except mysql.connector.Error as e:
        text = str(e)
        return ('refused' if 'Permission denied' in text or 'read-only' in text else 'error'), text[:160]
def proxy(operation, arguments, token=None):
    token = os.environ['MANTICORE_SCHEMA_TOKEN'] if token is None else token
    req = urllib.request.Request(os.environ['MANTICORE_SCHEMA_URL'] + '/operation', data=json.dumps(
        {'operation': operation, 'arguments': arguments}).encode(), headers={'Authorization': f'Bearer {token}'})
    try:
        return 'allowed', urllib.request.urlopen(req, timeout=30).read().decode()[:160]
    except urllib.error.HTTPError as e:
        return ('refused' if e.code in (400, 401) else 'error'), f'{e.code} {e.read().decode()[:140]}'
cases += [
    ('manticore', 'write user reads own table', 'allowed', mt(f'SELECT count(*) FROM {mine_mt}demo_vfs')),
    ('manticore', 'write user changes own rows', 'allowed', mt(f'DELETE FROM {mine_mt}demo_vfs WHERE id = 1 AND id = 2')),
    ('manticore', 'write user reads other table', 'refused', mt(f'SELECT count(*) FROM {theirs_mt}demo_vfs')),
    ('manticore', 'write user writes other table', 'refused', mt(f"DELETE FROM {theirs_mt}demo_vfs WHERE id = 1 AND id = 2")),
    ('manticore', 'write user drops other table', 'refused', mt(f'DROP TABLE IF EXISTS {theirs_mt}demo_vfs')),
    ('manticore', 'write user creates own table', 'refused', mt(f'CREATE TABLE {mine_mt}isolation_probe (title text)')),
    ('manticore', 'write user creates distributed table', 'refused',
     mt(f"CREATE TABLE {mine_mt}isolation_probe_d type='distributed' local='{theirs_mt}demo_vfs'")),
    ('manticore', 'write user alters own table', 'refused', mt(f'ALTER TABLE {mine_mt}demo_vfs ADD COLUMN isolation_probe int')),
    ('manticore', 'write user drops own table', 'refused', mt(f'DROP TABLE IF EXISTS {mine_mt}isolation_probe_none')),
    ('manticore', 'proxy creates own table', 'allowed', proxy('create_vfs_table', {'collection': 'demo'})),
    ('manticore', 'proxy with a table of the other zone', 'refused',
     proxy('add_pages_column', {'table': f'{theirs_mt}demo_1_pages', 'column': 'virus_hit'})),
    ('manticore', 'proxy distributed table', 'refused',
     proxy('create_distributed_table', {'name': f'{mine_mt}d', 'local': [f'{theirs_mt}demo_vfs']})),
    ('manticore', 'proxy without credential', 'refused', proxy('create_vfs_table', {'collection': 'demo'}, token='')),
    ('manticore', 'proxy imports from a folder of the other zone', 'refused',
     proxy('import_tables', {'collection': 'demo', 'export': f'../hoover-{other}'})),
    ('manticore', 'proxy imports from an absolute path', 'refused', proxy('import_tables', {'collection': 'demo', 'export': '/backups'})),
    ('manticore', 'proxy imports a table of the other zone', 'refused',
     proxy('import_tables', {'collection': 'demo', 'export': 'x', 'table': f'{theirs_mt}demo_vfs'})),
    ('manticore', 'proxy exports into the parent folder', 'refused', proxy('export_tables', {'collection': 'demo', 'export': '..'})),
]
def files_port():
    import socket
    try:
        socket.create_connection(('manticore', 9318), timeout=5).close()
        return 'allowed', 'connected'
    except OSError as e:
        return 'refused', str(e)[:120]
cases.append(('manticore', 'operations pod reaches the file service', 'refused', files_port()))
name = f'{other}-c-p4probe'
created = s3(lambda: client.make_bucket(name))
if created[0] == 'allowed':
    s3(lambda: client.remove_bucket(name))
cases.append(('garage', 'create bucket with other prefix', None, created))

import asyncio
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode
from temporalio.api.workflowservice.v1 import (DescribeNamespaceRequest, ListWorkflowExecutionsRequest,
    StartWorkflowExecutionRequest, SignalWorkflowExecutionRequest, TerminateWorkflowExecutionRequest,
    RequestCancelWorkflowExecutionRequest, GetWorkflowExecutionHistoryRequest, RegisterNamespaceRequest)
from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest, DeleteNamespaceRequest
from temporalio.api.common.v1 import WorkflowType, WorkflowExecution
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.enums.v1 import IndexedValueType
from google.protobuf.duration_pb2 import Duration

async def temporal_cases():
    key = os.environ.get('TEMPORAL_API_KEY') or None
    own = await Client.connect('temporal:7233', namespace=zone, api_key=key)
    bare = await Client.connect('temporal:7233', namespace=zone)
    ws, ops = own.workflow_service, own.operator_service
    async def call(coro):
        try:
            await coro
            return 'allowed', 'ok'
        except RPCError as e:
            return ('refused' if e.status == RPCStatusCode.PERMISSION_DENIED else 'error'), f'{e.status.name}: {e.message[:120]}'
    wid = 'tenant-isolation-probe'
    def start(ns):
        return ws.start_workflow_execution(StartWorkflowExecutionRequest(namespace=ns, workflow_id=wid,
            workflow_type=WorkflowType(name='TenantIsolationProbe'), task_queue=TaskQueue(name='tenant-isolation-probe'),
            request_id=__import__('uuid').uuid4().hex))
    def execution():
        return WorkflowExecution(workflow_id=wid)
    out = [
        ('temporal', 'describe own namespace', 'allowed', await call(ws.describe_namespace(DescribeNamespaceRequest(namespace=zone)))),
        ('temporal', 'list own workflows', 'allowed', await call(ws.list_workflow_executions(ListWorkflowExecutionsRequest(namespace=zone, page_size=1)))),
        ('temporal', 'start in own namespace', 'allowed', await call(start(zone))),
        ('temporal', 'signal in own namespace', 'allowed', await call(ws.signal_workflow_execution(SignalWorkflowExecutionRequest(
            namespace=zone, workflow_execution=execution(), signal_name='probe')))),
        ('temporal', 'terminate in own namespace', 'allowed', await call(ws.terminate_workflow_execution(TerminateWorkflowExecutionRequest(
            namespace=zone, workflow_execution=execution(), reason='tenant isolation probe')))),
        ('temporal', 'describe other namespace', 'refused', await call(ws.describe_namespace(DescribeNamespaceRequest(namespace=other)))),
        ('temporal', 'list other workflows', 'refused', await call(ws.list_workflow_executions(ListWorkflowExecutionsRequest(namespace=other, page_size=1)))),
        ('temporal', 'start in other namespace', 'refused', await call(start(other))),
        ('temporal', 'signal in other namespace', 'refused', await call(ws.signal_workflow_execution(SignalWorkflowExecutionRequest(
            namespace=other, workflow_execution=execution(), signal_name='probe')))),
        ('temporal', 'cancel in other namespace', 'refused', await call(ws.request_cancel_workflow_execution(RequestCancelWorkflowExecutionRequest(
            namespace=other, workflow_execution=execution())))),
        ('temporal', 'terminate in other namespace', 'refused', await call(ws.terminate_workflow_execution(TerminateWorkflowExecutionRequest(
            namespace=other, workflow_execution=execution())))),
        ('temporal', 'history in other namespace', 'refused', await call(ws.get_workflow_execution_history(GetWorkflowExecutionHistoryRequest(
            namespace=other, execution=execution())))),
        ('temporal', 'register a namespace', 'refused', await call(ws.register_namespace(RegisterNamespaceRequest(
            namespace=f'{zone}-probe', workflow_execution_retention_period=Duration(seconds=86400))))),
        ('temporal', 'delete other namespace', 'refused', await call(ops.delete_namespace(DeleteNamespaceRequest(namespace=other)))),
        ('temporal', 'add search attribute', 'refused', await call(ops.add_search_attributes(AddSearchAttributesRequest(
            namespace=zone, search_attributes={'TenantProbe': IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD})))),
        ('temporal', 'own namespace without key', 'refused', await call(bare.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace=zone)))),
    ]
    return out
cases += asyncio.run(temporal_cases())
for store, case, expected, (result, detail) in cases:
    print(json.dumps({'store': store, 'case': case, 'expected': expected, 'result': result, 'detail': detail,
                      'pass': None if expected is None else result == expected}))
'''


# The temporary folders of each pool. A file written in the first START_SECONDS of the container is a file of the
# start, for example the merged configuration of Tika, and no file of a request.
TEMP_FOLDERS = ('/tmp', '/var/tmp')
START_SECONDS = 60
# Tika writes the arguments of each forked parser JVM (/tmp/pipes-server-<n>-<id>/jvm-args.txt) when the first
# request starts that JVM. The file holds the class path and the options of the JVM, no request data.
NOT_REQUEST_FILES = ('/jvm-args.txt',)
# The variables of an installation that a pool must not hold.
ZONE_VARIABLES = ('CLICKHOUSE', 'MANTICORE', 'S3_', 'TEMPORAL', 'HOOVER4_CLICKHOUSE_DB_PREFIX', 'HOOVER4_MANTICORE_TABLE_PREFIX',
                  'HOOVER4_DATASET_MOUNTS', 'AGENT_API_BASE_URL')
POOL_PROBE = r'''
import json, sys, urllib.request, urllib.error
other = sys.argv[1]
body = json.dumps({'bucket': other + '-system', 'source_key': 'probe.pdf', 'dest_key': 'derived/probe.pdf'}).encode()
try:
    urllib.request.urlopen(urllib.request.Request('http://hoover4-ocr-pdf:8000/ocr-pdf', data=body,
                                                  headers={'Content-Type': 'application/json'}), timeout=60)
    print('allowed')
except urllib.error.HTTPError as e:
    print('refused', e.code, e.read().decode()[:160])
except Exception as e:
    print('error', type(e).__name__, str(e)[:160])
'''


def kubectl_json(*args):
    r = subprocess.run(K + list(args) + ['-o', 'json'], capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise SystemExit(f'kubectl {" ".join(args)} failed: {r.stderr.strip()[-300:]}')
    return json.loads(r.stdout)


def pool_cases(zone, other):
    """[(case, expected, result, detail)] of the processing pools."""
    out = []
    pods = [p for p in kubectl_json('-n', 'hoover-pools', 'get', 'pods')['items'] if p['status'].get('phase') == 'Running']
    names = {zone, other, zone.replace('-', '_'), other.replace('-', '_')}
    found = []
    for pod in pods:
        spec = pod['spec']
        for v in spec.get('volumes') or []:
            if {'persistentVolumeClaim', 'nfs', 'hostPath'} & set(v):
                found.append(f"{pod['metadata']['name']} volume {v['name']}")
        for c in spec['containers']:
            for e in c.get('env') or []:
                if e['name'].startswith(ZONE_VARIABLES) or any(n in str(e.get('value', '')) for n in names):
                    found.append(f"{pod['metadata']['name']} {e['name']}")
    out.append(('no pool pod holds a store credential, a store address, a zone identity or a volume of data', 'refused',
                'refused' if pods and not found else 'allowed', ', '.join(found[:6]) or f'{len(pods)} pods'))
    secrets = {s['metadata']['name']: sorted(s.get('data') or {}) for s in kubectl_json('-n', 'hoover-pools', 'get', 'secrets')['items']
               if s.get('type') != 'kubernetes.io/service-account-token'}
    extra = {n: k for n, k in secrets.items() if (n, k) != ('hoover-runtime', ['gpu-token'])}
    out.append(('the pools namespace holds no Secret except the GPU token of the pools', 'refused',
                'allowed' if extra else 'refused', json.dumps(extra)[:160] or 'none'))
    r = subprocess.run(K + ['-n', f'hoover-{zone}', 'exec', 'deploy/hoover-workers', '-c', 'hoover-workers', '--', PYTHON, '-c',
                            POOL_PROBE, other], capture_output=True, text=True, timeout=120)
    answer = (r.stdout.strip().splitlines() or [r.stderr.strip()[-160:]])[-1]
    out.append(('the searchable-PDF builder reads an object of the other zone', 'refused',
                'allowed' if answer.startswith('allowed') else 'refused', answer[:160]))
    import calendar
    import time
    kept, unread = [], []
    for pod in pods:
        name = pod['metadata']['name']
        container = pod['spec']['containers'][0]['name']
        status = next(c for c in pod['status']['containerStatuses'] if c['name'] == container)
        started = calendar.timegm(time.strptime(status['state']['running']['startedAt'], '%Y-%m-%dT%H:%M:%SZ'))
        r = subprocess.run(K + ['-n', 'hoover-pools', 'exec', name, '-c', container, '--', 'sh', '-c',
                                'find ' + ' '.join(TEMP_FOLDERS) + " -xdev -type f -exec stat -c '%Y %s %n' {} + 2>/dev/null; echo end"],
                           capture_output=True, text=True, timeout=120)
        if not r.stdout.strip().endswith('end'):
            unread.append(name)
            continue
        for line in r.stdout.strip().splitlines()[:-1]:
            mtime, size, path = line.split(' ', 2)
            if int(mtime) > started + START_SECONDS and not path.endswith(NOT_REQUEST_FILES):
                kept.append(f'{name}:{path} ({size} bytes)')
    out.append(('a pool keeps a file of a request in its temporary folders', 'refused',
                'allowed' if kept else 'error' if unread else 'refused',
                ', '.join(kept[:6]) or (f'unreadable: {", ".join(unread)}' if unread else f'{len(pods)} pods')))
    return out


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    zone, other = sys.argv[1:]
    ok = True
    for case, expected, result, detail in pool_cases(zone, other):
        ok &= result == expected
        print(json.dumps({'zone': zone, 'other': other, 'from': 'hoover-pools', 'store': 'pools', 'case': case,
                          'expected': expected, 'result': result, 'detail': detail, 'pass': result == expected}), flush=True)
    for deployment, python, probe in (('hoover-operations', PYTHON, PROBE), ('hoover4-mcp-collections', 'python3', READ_PROBE),
                                      ('manticore-schema', PYTHON, SCHEMA_PROBE), ('hoover-website', 'bash', WEB_PROBE)):
        r = subprocess.run(K + ['-n', f'hoover-{zone}', 'exec', f'deploy/{deployment}', '--', python, '-c', probe, zone, other],
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            raise SystemExit(f'the probe in {deployment} failed: {r.stderr.strip()[-600:]}')
        for line in r.stdout.splitlines():
            row = json.loads(line)
            ok &= row['pass'] is not False
            print(json.dumps({'zone': zone, 'other': other, 'from': deployment, **row}), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
