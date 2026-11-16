"""An S3 client of the shared Garage for the operator tools. It runs in the container s3 of a Garage pod.

The removal of a zone (shared.py remove) empties the zone buckets with it, and needs no pod of the zone, so a disabled
zone needs no other steps. The zone backup job (../../platform/backups/backups.py) runs SCRIPT in a short pod of the
Hoover namespace instead, for the system bucket of a zone and the ClickHouse archive of the zone databases: kubectl exec
with standard input into a Kata pod, such as a Garage pod, stopped its output after 32 KiB on the test site.

Each Garage pod of shared.py garage() has the container s3 (sidecar()): the image of the Manticore file service with
the standard library of Python only, and no command of its own. It reaches the S3 port of Garage on 127.0.0.1, so no
network policy names it. The operator tools and the zone runner already run commands in the Garage pods, so the
client needs no right to create a pod. The container holds no credential. The tool reads the secret of a key from the
Garage admin (key()), and each command gets one JSON line with the endpoint and the key on its standard input, then
the data of the command.

The zone backup job also runs SCRIPT in a short pod of a zone namespace against the openDesk object store, with its admin
key. The first line can then name a key for server-side encryption with a customer key (SSE-C) for each bucket
(sse_c, base64). tar reads an object without the key first, and with the key when the store refuses that. It marks
such a member with the PAX field HOOVER.sse-c, and untar writes that member with the key again.

Commands of SCRIPT (each prints one JSON line on standard error, and get and tar write the data on standard output):
  purge <bucket>...         delete the incomplete uploads and the objects, then the bucket when the key owns it
  empty <bucket>            delete the incomplete uploads and the objects, and keep the bucket
  tar <bucket>              write every object as a tar stream. A member name is the object key
  untar <bucket>            put each file of a tar stream as an object with the member name as key
  buckets                   print the names of the buckets that the key lists, as one JSON line
  mkbucket <bucket>         create a bucket, when it does not exist
  get <bucket> <key>        write one object
  put <bucket> <key> <size> put the next size bytes as one object
  delete <bucket> <key>     delete one object
  count <bucket>            print the object count and the byte count
"""
import contextlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import settings  # noqa: E402

NS = 'hoover-stores'
ENDPOINT = '127.0.0.1:3900'
CONTAINER = 's3'
IMAGE = 'docker.io/library/python:3.14-alpine@sha256:7f2ec713f0436c59df2362d973b6a05af9e87ba78f0e94f5245c302984a7a1fd'
K = ['kubectl', '--kubeconfig', str(settings.KUBECONFIG)]

SCRIPT = r'''
import datetime, hashlib, hmac, http.client, json, sys, tarfile, urllib.parse
import xml.etree.ElementTree as ET
first = json.loads(sys.stdin.buffer.readline())
ENDPOINT, ACCESS, SECRET = first['endpoint'], first['access_key'], first['secret_key']
SSE_C = first.get('sse_c') or {}
SSE_FIELD = 'HOOVER.sse-c'
REGION = 'us-east-1'
XMLNS = '{http://s3.amazonaws.com/doc/2006-03-01/}'


def quote(text):
    return urllib.parse.quote(text, safe='-_.~')


def sse_headers(bucket):
    """The SSE-C headers of the customer key of a bucket."""
    import base64
    key = SSE_C[bucket]
    return {'x-amz-server-side-encryption-customer-algorithm': 'AES256',
            'x-amz-server-side-encryption-customer-key': key,
            'x-amz-server-side-encryption-customer-key-md5': base64.b64encode(hashlib.md5(base64.b64decode(key)).digest()).decode()}


def call(method, bucket, key='', query=None, body=None, length=None, ok=(200, 204), extra=None):
    """One signed request (AWS signature version 4 with an unsigned payload). Return the open response. extra holds
    more x-amz headers, which the signature covers."""
    path = '/' + quote(bucket) + ('/' + '/'.join(quote(p) for p in key.split('/')) if key else '')
    qs = '&'.join(f'{quote(k)}={quote(v)}' for k, v in sorted((query or {}).items()))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    headers = {'host': ENDPOINT, 'x-amz-content-sha256': 'UNSIGNED-PAYLOAD', 'x-amz-date': stamp, **(extra or {})}
    names = ';'.join(sorted(headers))
    canonical = '\n'.join([method, path, qs, ''.join(f'{h}:{headers[h]}\n' for h in sorted(headers)), names, 'UNSIGNED-PAYLOAD'])
    scope = f'{stamp[:8]}/{REGION}/s3/aws4_request'
    text = '\n'.join(['AWS4-HMAC-SHA256', stamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signing = ('AWS4' + SECRET).encode()
    for part in (stamp[:8], REGION, 's3', 'aws4_request'):
        signing = hmac.new(signing, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing, text.encode(), hashlib.sha256).hexdigest()
    headers['authorization'] = f'AWS4-HMAC-SHA256 Credential={ACCESS}/{scope}, SignedHeaders={names}, Signature={signature}'
    if length is not None:
        headers['content-length'] = str(length)
    host, _, port = ENDPOINT.partition(':')
    connection = http.client.HTTPConnection(host, int(port or 80), timeout=600)
    connection.request(method, path + ('?' + qs if qs else ''), body=body, headers=headers)
    response = connection.getresponse()
    if response.status not in ok:
        raise SystemExit(f'{method} {bucket}/{key} answered {response.status}: {response.read()[:300].decode(errors="replace")}')
    return response


def listing(bucket):
    """(key, size) of every object of a bucket."""
    token = None
    while True:
        query = {'list-type': '2', **({'continuation-token': token} if token else {})}
        root = ET.fromstring(call('GET', bucket, query=query).read())
        for item in root.iter(XMLNS + 'Contents'):
            yield item.findtext(XMLNS + 'Key'), int(item.findtext(XMLNS + 'Size'))
        token = root.findtext(XMLNS + 'NextContinuationToken')
        if root.findtext(XMLNS + 'IsTruncated') != 'true' or not token:
            return


def empty(bucket):
    """Delete the incomplete uploads and the objects of a bucket. Return the deleted object count."""
    root = ET.fromstring(call('GET', bucket, query={'uploads': ''}).read())
    for upload in root.iter(XMLNS + 'Upload'):
        call('DELETE', bucket, upload.findtext(XMLNS + 'Key'), {'uploadId': upload.findtext(XMLNS + 'UploadId')}).read()
    count = 0
    for key, _ in list(listing(bucket)):
        call('DELETE', bucket, key).read()
        count += 1
    return count


def report(**row):
    sys.stderr.write(json.dumps(row) + '\n')


command, args = sys.argv[1], sys.argv[2:]
if command == 'purge':
    for bucket in args:
        if call('HEAD', bucket, ok=(200, 404)).status == 404:
            report(bucket=bucket, present=False)
            continue
        deleted = empty(bucket)
        # The key deletes a bucket that it owns: a bucket with a local alias of the key. The Garage admin deletes a
        # bucket with a global alias.
        gone = call('DELETE', bucket, ok=(204, 403, 409)).status == 204
        report(bucket=bucket, objects=deleted, bucket_deleted=gone)
elif command == 'empty':
    report(bucket=args[0], objects=empty(args[0]))
elif command == 'count':
    found = list(listing(args[0]))
    print(json.dumps({'bucket': args[0], 'objects': len(found), 'bytes': sum(s for _, s in found)}))
elif command == 'tar':
    count = encrypted = 0
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|', format=tarfile.PAX_FORMAT) as tar:
        for key, size in list(listing(args[0])):
            info = tarfile.TarInfo(key)
            response = call('GET', args[0], key, ok=(200, 400, 403) if args[0] in SSE_C else (200,))
            if response.status != 200:
                response.read()
                response = call('GET', args[0], key, extra=sse_headers(args[0]))
                info.pax_headers = {SSE_FIELD: '1'}
                encrypted += 1
            # The length of the answer: an object with a customer key can list another size.
            info.size, info.mode = int(response.getheader('content-length', size)), 0o600
            tar.addfile(info, response)
            count += 1
    report(bucket=args[0], objects=count, customer_key_objects=encrypted)
elif command == 'untar':
    count = 0
    with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as tar:
        for member in tar:
            if member.isfile():
                extra = sse_headers(args[0]) if member.pax_headers.get(SSE_FIELD) == '1' else None
                call('PUT', args[0], member.name, body=tar.extractfile(member), length=member.size, extra=extra).read()
                count += 1
    report(bucket=args[0], objects=count)
elif command == 'buckets':
    root = ET.fromstring(call('GET', '').read())
    print(json.dumps(sorted(b.findtext(XMLNS + 'Name') for b in root.iter(XMLNS + 'Bucket'))))
elif command == 'mkbucket':
    call('PUT', args[0], ok=(200, 409)).read()
    report(bucket=args[0], created=True)
elif command == 'get':
    response = call('GET', args[0], args[1])
    size, length = 0, int(response.getheader('content-length'))
    while chunk := response.read(1 << 20):
        sys.stdout.buffer.write(chunk)
        size += len(chunk)
    if size != length:
        raise SystemExit(f'the object {args[1]} ended after {size} of {length} bytes')
    report(bucket=args[0], key=args[1], bytes=size)
elif command == 'put':
    call('PUT', args[0], args[1], body=sys.stdin.buffer, length=int(args[2])).read()
    report(bucket=args[0], key=args[1], bytes=int(args[2]))
elif command == 'delete':
    call('DELETE', args[0], args[1]).read()
    report(bucket=args[0], key=args[1], deleted=True)
else:
    raise SystemExit(f'unknown command {command}')
'''


def kubectl(*args, input=None, check=True):
    r = subprocess.run(K + list(args), input=input, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f'kubectl {" ".join(args[:4])} failed: {r.stderr.strip()[-300:]}')
    return r.stdout


def ready_garage():
    """The name of a ready Garage pod."""
    found = json.loads(kubectl('-n', NS, 'get', 'pods', '-l', 'hoover.dev/store=garage', '-o', 'json'))['items']
    for item in sorted(found, key=lambda p: p['metadata']['name']):
        if not item['metadata'].get('deletionTimestamp') and any(
                c['type'] == 'Ready' and c['status'] == 'True' for c in item.get('status', {}).get('conditions', [])):
            return item['metadata']['name']
    raise SystemExit(f'the shared garage has no ready pod in {NS}. Run deploy-k3s up --steps stores.')


def admin(*args, check=True):
    """Run the Garage CLI as the admin in a ready Garage pod. Return its output."""
    r = subprocess.run(K + ['-n', NS, 'exec', ready_garage(), '-c', 'garage', '--', '/garage', *args],
                       capture_output=True, text=True, timeout=300)
    if check and r.returncode:
        raise SystemExit(f'garage {" ".join(args[:2])} failed: {r.stderr.strip()[-400:]}')
    return r.stdout


def parse_key(out):
    """{access_key, secret_key} of the output of garage key create, or of garage key info --show-secret."""
    found = re.search(r'Key ID:\s+(\S+)', out), re.search(r'Secret key:\s+(\S+)', out)
    if not all(found):
        raise SystemExit('the Garage CLI gave no key.')
    return {'access_key': found[0].group(1), 'secret_key': found[1].group(1)}


def key(pattern):
    """{access_key, secret_key} of a Garage key by its id or name. Garage gives the secret to its admin."""
    return parse_key(admin('key', 'info', '--show-secret', pattern))


def keys():
    """{key id: key name} of every Garage key."""
    lines = [l.split() for l in admin('key', 'list').splitlines() if l.strip() and not l.startswith('==')][1:]
    return {row[0]: row[2] for row in lines if len(row) > 2}


def zone_key(zone):
    """The Garage key of a zone, which reads and writes every bucket of the zone (../setup.py garage())."""
    found = [i for i, name in keys().items() if name == zone]
    if len(found) != 1:
        raise SystemExit(f'Garage has {len(found)} keys with the name {zone}, and the step needs one.')
    return key(found[0])


def sidecar():
    """The container s3 of a Garage pod. It waits, and the tools run SCRIPT in it with kubectl exec."""
    return {'name': CONTAINER, 'image': IMAGE, 'imagePullPolicy': 'IfNotPresent',
            'command': ['/bin/sh', '-c', 'trap "exit 0" TERM; while :; do sleep 3600 & wait $!; done'],
            'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                'runAsNonRoot': True, 'runAsUser': 65534, 'runAsGroup': 65534,
                                'capabilities': {'drop': ['ALL']}},
            'resources': {'requests': {'cpu': '1m', 'memory': '16Mi'}, 'limits': {'cpu': '500m', 'memory': '128Mi'}}}


@contextlib.contextmanager
def client():
    """Yield the name of a ready Garage pod, whose container s3 runs the commands of SCRIPT."""
    yield ready_garage()


def run(name, key, *args, data=None, out=None):
    """Run one command of SCRIPT in the container s3 of the Garage pod name with key. data is a path or bytes for the standard input after
    the key line. out is a path for the standard output. Return (standard output text when out is None, report lines).

    The standard input stays open until the command ends (../../podexec.py), because the output of a Kata container
    stops after 32 KiB once kubectl closes it."""
    import podexec
    first = json.dumps({'endpoint': ENDPOINT, **{k: key[k] for k in ('access_key', 'secret_key')}}).encode() + b'\n'
    with tempfile.TemporaryFile() as errors, (open(out, 'wb') if out else tempfile.TemporaryFile()) as output:
        code = podexec.run(K + ['-n', NS, 'exec', '-i', name, '-c', CONTAINER], ['python3', '-I', '-c', SCRIPT, *args],
                           [first] + ([] if data is None else [data]), stdout=output, stderr=errors)
        errors.seek(0)
        text = errors.read().decode(errors='replace')
        if code:
            raise SystemExit(f'garage {args[0]} {" ".join(args[1:2])} failed: {text.strip()[-400:]}')
        reports = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
        if out:
            return None, reports
        output.seek(0)
        return output.read().decode(), reports
