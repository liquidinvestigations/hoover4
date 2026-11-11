#!/usr/bin/env python3
"""Check the store access of each Hoover service of a zone from inside its pod.

For each service of ../hoover/stores/service_users.py the check runs Python in one pod of the service with the
environment of that pod:
- ClickHouse: the user name of the answer to currentUser(), and whether the user reads chat_sessions, a table of
  the zone database without a grant for the browser. Only the browser user must not read it.
- Garage: whether the key reaches the system bucket and the bucket of the demo collection. Only the collection key
  must reach the collection bucket.
Each line of the output is JSON. The check prints no credential.
Usage: hoover-store-access-check.py <zone>
"""
import base64
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hoover' / 'stores'))
import settings  # noqa: E402
import service_users  # noqa: E402

K = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG)]
DEPLOYMENTS = {'website': 'hoover-website', 'worker': 'hoover-workers', 'ops': 'hoover-operations', 'ocr-pdf': 'hoover4-ocr-pdf'}
PYTHON = {'website': None, 'worker': '/opt/pysetup/.venv/bin/python3', 'ops': '/opt/pysetup/.venv/bin/python3'}
# The probe uses only the standard library and botocore when the image has it. The website image has no Python, so
# its probe runs in a worker pod with the website environment values.
PROBE = r'''
import json, os, sys, urllib.request, urllib.error
# The first line of stdin holds the probe values, so no value is on a command line.
os.environ.update(json.loads(sys.stdin.readline()))
out = {}
def ch(sql):
    req = urllib.request.Request(os.environ['CLICKHOUSE_URL'] + '/', data=sql.encode(), headers={
        'X-ClickHouse-User': os.environ.get('CLICKHOUSE_USER', ''), 'X-ClickHouse-Key': os.environ.get('CLICKHOUSE_PASSWORD', '')})
    try:
        return urllib.request.urlopen(req, timeout=10).read().decode().strip()
    except urllib.error.HTTPError as e:
        return 'refused ' + str(e.code)
    except Exception as e:
        return 'failed ' + type(e).__name__
if os.environ.get('CLICKHOUSE_USER'):
    out['clickhouse_user'] = ch('SELECT currentUser()')
    out['sessions_table'] = ch('SELECT count() FROM ' + os.environ['PROBE_GLOBAL_DB'] + '.chat_sessions')
    out['artifacts_table'] = ch('SELECT count() FROM ' + os.environ['PROBE_GLOBAL_DB'] + '.chat_artifacts')
if os.environ.get('S3_ACCESS_KEY'):
    try:
        import boto3
        from botocore.config import Config
        s3 = boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'], aws_access_key_id=os.environ['S3_ACCESS_KEY'],
                          aws_secret_access_key=os.environ['S3_SECRET_KEY'], region_name='us-east-1', config=Config(retries={'max_attempts': 1}))
        def reach(bucket):
            try:
                s3.list_objects_v2(Bucket=bucket, MaxKeys=1)
                return 'reached'
            except Exception as e:
                return 'refused ' + type(e).__name__
    except ImportError:
        from minio import Minio
        endpoint = os.environ['S3_ENDPOINT'].split('://', 1)[-1]
        s3 = Minio(endpoint, access_key=os.environ['S3_ACCESS_KEY'], secret_key=os.environ['S3_SECRET_KEY'], secure=False, region='us-east-1')
        def reach(bucket):
            try:
                list(s3.list_objects(bucket, recursive=False))[:1]
                return 'reached'
            except Exception as e:
                return 'refused ' + type(e).__name__
    out['system_bucket'] = reach(os.environ['PROBE_SYSTEM_BUCKET'])
    out['collection_bucket'] = reach(os.environ['PROBE_COLLECTION_BUCKET'])
print(json.dumps(out))
'''


def kubectl(*args, input=None):
    return subprocess.run(K + list(args), input=input, capture_output=True, text=True)


def main():
    zone = sys.argv[1]
    ns, prefix = f'hoover-{zone}', service_users.prefix(zone)
    probe_env = {'PROBE_GLOBAL_DB': f'{prefix}_Processing',
                 'PROBE_SYSTEM_BUCKET': f'{zone}-system', 'PROBE_COLLECTION_BUCKET': f'{zone}-c-demo'}
    failed = False
    for service, stores in service_users.SERVICES.items():
        deployment = DEPLOYMENTS.get(service, f'hoover4-{service}')
        found = kubectl('-n', ns, 'get', 'deployment', deployment, '-o', 'json')
        if found.returncode:
            print(json.dumps({'service': service, 'result': 'no deployment'}))
            failed = True
            continue
        spec = json.loads(found.stdout)['spec']['template']['spec']
        env_names = [e['name'] for e in spec['containers'][0].get('env', [])]
        # The website image has no Python. Its probe runs in a worker pod with the environment of the website.
        target = 'hoover-workers' if service == 'website' else deployment
        python = PYTHON.get(service, 'python3') or '/opt/pysetup/.venv/bin/python3'
        values = dict(probe_env)
        if service == 'website':
            for e in spec['containers'][0]['env']:
                if e['name'] in ('CLICKHOUSE_USER', 'CLICKHOUSE_URL', 'S3_ENDPOINT') and 'value' in e:
                    values[e['name']] = e['value']
            secret = json.loads(kubectl('-n', ns, 'get', 'secret', 'hoover-runtime', '-o', 'json').stdout)['data']
            values['CLICKHOUSE_PASSWORD'] = base64.b64decode(secret['clickhouse-website']).decode()
            values['S3_ACCESS_KEY'] = base64.b64decode(secret['s3-access-key-website']).decode()
            values['S3_SECRET_KEY'] = base64.b64decode(secret['s3-secret-key-website']).decode()
        # python -c reads the program from its argument and the values from stdin.
        r = kubectl('-n', ns, 'exec', '-i', f'deploy/{target}', '-c', spec['containers'][0]['name'] if target == deployment else 'hoover-workers',
                    '--', python, '-c', PROBE, input=json.dumps(values) + '\n')
        line = (r.stdout.strip().splitlines() or [''])[-1]
        try:
            result = json.loads(line)
        except ValueError:
            result = {'error': (r.stderr.strip().splitlines() or ['no output'])[-1][:200]}
        expected_user = service_users.user(zone, service) if 'clickhouse' in stores else None
        ok = 'error' not in result
        if expected_user:
            ok &= result.get('clickhouse_user') == expected_user
            browser = stores['clickhouse'] == 'browser'
            ok &= result.get('sessions_table', '').startswith('refused') == browser
            ok &= result.get('artifacts_table', '').isdigit()
        if 'garage' in stores:
            ok &= result.get('system_bucket') == 'reached'
            ok &= (result.get('collection_bucket') == 'reached') == (stores['garage'] == 'collections')
        ok &= ('CLICKHOUSE_PASSWORD' in env_names) == ('clickhouse' in stores)
        ok &= ('S3_ACCESS_KEY' in env_names) == ('garage' in stores)
        print(json.dumps({'service': service, 'ok': ok, **result}), flush=True)
        failed |= not ok
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
