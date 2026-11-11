# Runs inside the check pod. Prints one JSON object. Never prints a key.
# The zone key writes, reads and deletes one object, and loads 200 objects of 256 KiB. A request without a key is refused.
import filecmp, json, os, subprocess, time
ZONE = os.environ['ZONE']
ENDPOINT = f"http://garage.{ZONE}.svc.cluster.local:3900"
keys = json.load(open('/secret/tenants.json'))
BUCKET = f's3://{ZONE}-system'
subprocess.run(['aws', 'configure', 'set', 'default.s3.addressing_style', 'path'], check=True)


def aws(*args, signed=True):
    k = keys[ZONE]
    env = {**os.environ, 'AWS_ACCESS_KEY_ID': k['access_key'], 'AWS_SECRET_ACCESS_KEY': k['secret_key'], 'AWS_DEFAULT_REGION': 'us-east-1'}
    t = time.time()
    r = subprocess.run(['aws', '--endpoint-url', ENDPOINT, 's3', *args] + ([] if signed else ['--no-sign-request']), env=env,
                       capture_output=True, text=True, timeout=600)
    r.seconds = round(time.time() - t, 2)
    return r


out = {}
data = os.urandom(1 << 20)
open('/tmp/object', 'wb').write(data)
key = f'{BUCKET}/store-check-object'
put, get = aws('cp', '/tmp/object', key), aws('cp', key, '/tmp/back')
out['round_trip'] = put.returncode == 0 and get.returncode == 0 and open('/tmp/back', 'rb').read() == data
out['delete_ok'] = aws('rm', key).returncode == 0
anonymous = aws('ls', BUCKET, signed=False)
out['anonymous_list_refused'] = anonymous.returncode != 0
os.makedirs('/tmp/up'); os.makedirs('/tmp/down')
for i in range(200):
    open(f'/tmp/up/o{i:03d}', 'wb').write(os.urandom(256 << 10))
prefix = f'{BUCKET}/store-load/'
up = aws('cp', '--recursive', '--quiet', '/tmp/up', prefix)
down = aws('cp', '--recursive', '--quiet', prefix, '/tmp/down')
out['load'] = {'objects': 200, 'mib': 50, 'upload': [up.returncode, up.seconds], 'download': [down.returncode, down.seconds],
               'identical': len(os.listdir('/tmp/down')) == 200 and all(filecmp.cmp(f'/tmp/up/{n}', f'/tmp/down/{n}', shallow=False) for n in os.listdir('/tmp/up'))}
rm = aws('rm', '--recursive', '--quiet', prefix)
out['load']['delete'] = [rm.returncode, rm.seconds]
print(json.dumps(out))
