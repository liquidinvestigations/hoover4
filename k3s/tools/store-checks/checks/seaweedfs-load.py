# Runs inside the check pod. Uploads, downloads, compares and deletes 200 objects of 256 KiB with the nextcloud identity.
import filecmp, json, os, subprocess, time
ENDPOINT = f"http://seaweedfs-all-in-one.{os.environ['ZONE']}.svc.cluster.local:8333"
config = json.load(open('/secret/seaweedfs_s3_config'))
c = next(i for i in config['identities'] if i['name'] == 'nextcloud')['credentials'][0]
env = {**os.environ, 'AWS_ACCESS_KEY_ID': c['accessKey'], 'AWS_SECRET_ACCESS_KEY': c['secretKey'], 'AWS_DEFAULT_REGION': 'us-east-1'}
os.makedirs('/tmp/up'); os.makedirs('/tmp/down')
for i in range(200):
    open(f'/tmp/up/o{i:03d}', 'wb').write(os.urandom(256 << 10))
def aws(*a):
    t = time.time(); r = subprocess.run(['aws', '--endpoint-url', ENDPOINT, 's3', *a], env=env, capture_output=True, text=True, timeout=600); return r.returncode, round(time.time() - t, 2)
prefix = 's3://nextcloud/store-load/'
up = aws('cp', '--recursive', '--quiet', '/tmp/up', prefix)
down = aws('cp', '--recursive', '--quiet', prefix, '/tmp/down')
same = not filecmp.dircmp('/tmp/up', '/tmp/down').diff_files and len(os.listdir('/tmp/down')) == 200 and \
    all(filecmp.cmp(f'/tmp/up/{n}', f'/tmp/down/{n}', shallow=False) for n in os.listdir('/tmp/up'))
rm = aws('rm', '--recursive', '--quiet', prefix)
print(json.dumps({'objects': 200, 'mib': 50, 'upload': up, 'download': down, 'identical': same, 'delete': rm}))
