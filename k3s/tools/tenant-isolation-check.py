#!/usr/bin/env python3
"""Check that a zone cannot read or write the data of another zone in the shared stores of the site.

The probes run Python in the pods of hoover-<zone> with the credentials of each pod: the operations pod (ClickHouse
user, Garage key, Temporal key, Manticore write user and proxy credential), the collections server (Manticore read
user) and the schema proxy (Manticore schema user). Both zones need the collection demo with its Manticore tables, so
<prefix>_demo_vfs exists in each zone.
- ClickHouse: the user reads its own database <prefix>_Processing. It cannot read, write or drop a table of
  <other prefix>_Processing, create a database with the other prefix, or list the other databases.
- Garage: the key lists its own system bucket. It cannot list, read or write the system bucket of the other zone, and
  the bucket list holds no bucket of the other zone.
- Manticore, write user: it reads and changes rows of its own tables. It cannot read or change a table of the other
  zone, and it cannot create, alter or drop a table, also not a distributed table that names a table of the other zone.
- Manticore, read user on the read-only listener 9309 and on 9308: it reads its own tables. It cannot read a table
  of the other zone, change a row, or create a distributed table.
- Manticore schema proxy: with the proxy credential it creates a table of its own zone. It refuses a table of the
  other zone, an unknown operation such as a distributed table, and a request without the credential.
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
for store, case, expected, (result, detail) in cases:
    print(json.dumps({'store': store, 'case': case, 'expected': expected, 'result': result, 'detail': detail,
                      'pass': None if expected is None else result == expected}))
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
        return ('refused' if 'ACCESS_DENIED' in body or 'Not enough privileges' in body else 'error'), body[:160]
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
]
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


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    zone, other = sys.argv[1:]
    ok = True
    for deployment, python, probe in (('hoover-operations', PYTHON, PROBE), ('hoover4-mcp-collections', 'python3', READ_PROBE),
                                      ('manticore-schema', PYTHON, SCHEMA_PROBE)):
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
