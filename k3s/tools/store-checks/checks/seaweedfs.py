# Runs inside the check pod. Prints one JSON object. Never prints a credential.
# The nextcloud identity writes, reads and deletes one object in its bucket. It must not list the bucket of openproject.
import hashlib, json, os, subprocess
ENDPOINT = f"http://seaweedfs-all-in-one.{os.environ['ZONE']}.svc.cluster.local:8333"
config = json.load(open('/secret/seaweedfs_s3_config'))


def env(identity):
    c = next(i for i in config['identities'] if i['name'] == identity)['credentials'][0]
    return {**os.environ, 'AWS_ACCESS_KEY_ID': c['accessKey'], 'AWS_SECRET_ACCESS_KEY': c['secretKey'], 'AWS_DEFAULT_REGION': 'us-east-1'}


def aws(identity, *args):
    return subprocess.run(['aws', '--endpoint-url', ENDPOINT, *args], env=env(identity), capture_output=True, text=True, timeout=120)


out = {'buckets': {}}
for line in aws('admin', 's3', 'ls').stdout.split('\n'):
    if line.strip():
        bucket = line.split()[-1]
        listing = aws('admin', 's3', 'ls', f's3://{bucket}', '--recursive').stdout.split('\n')
        out['buckets'][bucket] = sum(1 for l in listing if l.strip())
data = os.urandom(1 << 20)
open('/tmp/object', 'wb').write(data)
key = 's3://nextcloud/store-check-object'
put = aws('nextcloud', 's3', 'cp', '/tmp/object', key)
get = aws('nextcloud', 's3', 'cp', key, '/tmp/back')
same = get.returncode == 0 and hashlib.sha256(open('/tmp/back', 'rb').read()).digest() == hashlib.sha256(data).digest()
delete = aws('nextcloud', 's3', 'rm', key)
cross = aws('nextcloud', 's3', 'ls', 's3://openproject')
out.update(put_ok=put.returncode == 0, read_back_identical=same, delete_ok=delete.returncode == 0,
           other_bucket_list_refused=cross.returncode != 0, other_bucket_error=(cross.stderr.strip().splitlines() or [''])[-1][:120])
print(json.dumps(out))
