#!/usr/bin/env python3
"""Send requests to the UDM REST API of a zone as Administrator.

A port forward does not reach a gVisor pod, so each request runs in the UDM REST API container through kubectl exec.
The request with the credentials goes through standard input, so no password is on a command line.
"""
import base64
import json
import subprocess
import time

# Runs in the UDM REST API container: one HTTP request from standard input, the answer as JSON on standard output.
REMOTE = '''import json,sys,urllib.request,urllib.error
q=json.load(sys.stdin)
r=urllib.request.Request(q['url'],method=q['method'],headers=q['headers'],data=json.dumps(q['body']).encode() if q['body'] is not None else None)
try:
 with urllib.request.urlopen(r,timeout=60) as a:print(json.dumps({'status':a.status,'headers':dict(a.headers),'body':a.read().decode()}))
except urllib.error.HTTPError as e:print(json.dumps({'status':e.code,'headers':dict(e.headers),'body':e.read().decode(errors='replace')}))
'''


class CallError(Exception):
    def __init__(self, code, body):
        super().__init__(f'{code} {body[:300]}')
        self.code = code
        self.body = body


def client(zone):
    """Return call(method, path, body=None, headers={}) -> (status, headers, body) after the API answers."""
    secret = json.loads(subprocess.check_output(['kubectl', '-n', zone, 'get', 'secret', 'ums-nubus-credentials', '-o', 'json']))
    admin = base64.b64decode(secret['data']['administrator_password']).decode()
    auth = 'Basic ' + base64.b64encode(f'Administrator:{admin}'.encode()).decode()

    def call(method, path, body=None, headers={}):
        request = {'method': method, 'url': f'http://127.0.0.1:9979/univention/udm/{path}', 'body': body,
                   'headers': {'Authorization': auth, 'Accept': 'application/json', 'Content-Type': 'application/json', **headers}}
        out = subprocess.run(['kubectl', '-n', zone, 'exec', '-i', 'deploy/ums-udm-rest-api', '-c', 'main', '--', 'python3', '-c', REMOTE],
                             input=json.dumps(request), capture_output=True, text=True, timeout=120)
        if out.returncode:
            raise ConnectionError(out.stderr.strip()[-300:])
        answer = json.loads(out.stdout)
        if answer['status'] >= 400:
            raise CallError(answer['status'], answer['body'])
        return answer['status'], answer['headers'], json.loads(answer['body'] or '{}')

    for _ in range(30):
        try:
            call('GET', 'users/user/?filter=uid%3DAdministrator')
            break
        except (CallError, ConnectionError):
            time.sleep(2)
    return call


def user(call, uid):
    """Return the UDM object of a user with every property, or None."""
    _, _, found = call('GET', f'users/user/?filter=uid%3D{uid}&properties=%2A')
    items = found.get('_embedded', {}).get('udm:object', [])
    return items[0] if items else None
