# Runs inside the check pod in the zone namespace. Sets and reads 10,000 values of 1 KiB.
import json, os, socket, time
ZONE = os.environ['ZONE']


def connect(ns):
    return socket.create_connection((f'memcached.{ns}.svc.cluster.local', 11211), timeout=5)


def command(s, data):
    s.sendall(data)
    out = b''
    while not out.endswith((b'END\r\n', b'STORED\r\n', b'DELETED\r\n', b'NOT_FOUND\r\n')):
        out += s.recv(65536)
    return out


# The network policy agent admits a new pod some seconds after it starts.
for attempt in range(30):
    try:
        s = connect(ZONE)
        break
    except ConnectionRefusedError:
        time.sleep(1)
value = os.urandom(512).hex().encode()
t = time.time()
for i in range(10000):
    assert command(s, b'set check-%d 0 300 %d\r\n%s\r\n' % (i, len(value), value)) == b'STORED\r\n'
set_seconds = round(time.time() - t, 2)
t = time.time()
hits = sum(1 for i in range(10000) if command(s, b'get check-%d\r\n' % i).count(value) == 1)
get_seconds = round(time.time() - t, 2)
s.sendall(b'stats\r\n'); stats = b''
while not stats.endswith(b'END\r\n'):
    stats += s.recv(65536)
keep = {l.split()[1]: l.split()[2] for l in stats.decode().splitlines() if l.startswith('STAT') and l.split()[1] in ('curr_items', 'bytes', 'limit_maxbytes')}
print(json.dumps({'zone': ZONE, 'set_10000_seconds': set_seconds, 'get_10000_seconds': get_seconds, 'hits': hits, 'connect_attempts': attempt + 1, 'stats': keep}))
