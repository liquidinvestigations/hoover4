# Runs inside the check pod in the zone namespace. RESP protocol over a socket. Never prints the password.
import json, os, socket, time
ZONE = os.environ['ZONE']
password = open('/secret/redis-password').read().strip()


def resp(*args):
    return b'*%d\r\n' % len(args) + b''.join(b'$%d\r\n%s\r\n' % (len(a), a) for a in (x if isinstance(x, bytes) else str(x).encode() for x in args))


def connect(host):
    for attempt in range(30):
        try:
            return socket.create_connection((host, 6379), timeout=10)
        except ConnectionRefusedError:
            time.sleep(1)
    raise RuntimeError('refused')


def reply(s, buf):
    while b'\r\n' not in buf[0]:
        buf[0] += s.recv(65536)
    line, buf[0] = buf[0].split(b'\r\n', 1)
    if line[:1] == b'$' and int(line[1:]) >= 0:
        size = int(line[1:])
        while len(buf[0]) < size + 2:
            buf[0] += s.recv(65536)
        data, buf[0] = buf[0][:size], buf[0][size + 2:]
        return data
    return line


s = connect(f'redis-master.{ZONE}.svc.cluster.local'); buf = [b'']
s.sendall(resp('AUTH', password)); auth = reply(s, buf)
s.sendall(resp('SELECT', 15)); reply(s, buf)
value = os.urandom(512).hex().encode()
t = time.time()
s.sendall(b''.join(resp('SET', f'check-{i}', value, 'EX', 600) for i in range(10000)))
ok = sum(1 for _ in range(10000) if reply(s, buf) == b'+OK')
set_seconds = round(time.time() - t, 2)
t = time.time()
s.sendall(b''.join(resp('GET', f'check-{i}') for i in range(10000)))
hits = sum(1 for _ in range(10000) if reply(s, buf) == value)
get_seconds = round(time.time() - t, 2)
s.sendall(b''.join(resp('DEL', f'check-{i}') for i in range(10000))); [reply(s, buf) for _ in range(10000)]
s.sendall(resp('INFO', 'persistence')); info = reply(s, buf).decode()
persistence = {l.split(':')[0]: l.split(':')[1] for l in info.splitlines() if l.startswith(('aof_enabled', 'aof_last_write_status', 'rdb_last_bgsave_status'))}
print(json.dumps({'zone': ZONE, 'auth': auth.decode(), 'set_10000_seconds': set_seconds, 'set_ok': ok, 'get_10000_seconds': get_seconds,
                  'hits': hits, 'persistence': persistence}))
