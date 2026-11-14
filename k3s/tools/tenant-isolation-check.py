#!/usr/bin/env python3
"""Check that a zone cannot read or write the data of another zone in the shared stores of the site.

The probe runs Python in the operations pod of hoover-<zone>, with the ClickHouse user and the Garage key of that pod.
- ClickHouse: the user reads its own database <prefix>_Processing. It cannot read, write or drop a table of
  <other prefix>_Processing, create a database with the other prefix, or list the other databases.
- Garage: the key lists its own system bucket. It cannot list, read or write the system bucket of the other zone, and
  the bucket list holds no bucket of the other zone.
- Manticore: the daemons of the other zone are in its zone namespace, and the network policies refuse the connection.
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
PROBE = r'''
import json, os, socket, sys, urllib.request, urllib.error
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
def tcp(host, port):
    try:
        socket.create_connection((host, port), 5).close()
        return 'allowed', 'open'
    except Exception as e:
        return 'refused', type(e).__name__
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
    ('manticore', 'other zone daemon', 'refused', tcp(f'manticore.{other}.svc.cluster.local', 9306)),
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
    r = subprocess.run(K + ['-n', f'hoover-{zone}', 'exec', 'deploy/hoover-operations', '--', PYTHON, '-c', PROBE, zone, other],
                       capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise SystemExit(f'the probe failed: {r.stderr.strip()[-600:]}')
    ok = True
    for line in r.stdout.splitlines():
        row = json.loads(line)
        ok &= row['pass'] is not False
        print(json.dumps({'zone': zone, 'other': other, **row}), flush=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
