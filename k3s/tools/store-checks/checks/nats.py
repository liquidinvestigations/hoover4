# Runs inside the check pod in the zone namespace. Uses the NATS text protocol. Never prints the password.
import json, os, socket, time, urllib.request
ZONE = os.environ['ZONE']
HOST = f'ums-provisioning-nats.{ZONE}.svc.cluster.local'
POD = os.environ.get('POD_IP')
password = open('/secret/password').read().strip()


class Client:
    def __init__(self):
        # The network policy agent admits a new pod some seconds after it starts.
        for attempt in range(30):
            try:
                self.s = socket.create_connection((HOST, 4222), timeout=10)
                break
            except ConnectionRefusedError:
                time.sleep(1)
        out['connect_attempts'] = attempt + 1
        self.buf = b''
        self.line()  # INFO
        self.s.sendall(b'CONNECT ' + json.dumps({'user': 'admin', 'pass': password, 'verbose': False, 'pedantic': False}).encode() + b'\r\nPING\r\n')
        assert self.line().startswith(b'PONG'), 'connect failed'
        self.s.sendall(b'SUB _INBOX.storecheck 1\r\n')

    def line(self):
        while b'\r\n' not in self.buf:
            self.buf += self.s.recv(65536)
        line, self.buf = self.buf.split(b'\r\n', 1)
        return line

    def message(self):
        while True:
            line = self.line()
            if line.startswith(b'MSG'):
                size = int(line.split()[-1])
                while len(self.buf) < size + 2:
                    self.buf += self.s.recv(65536)
                payload, self.buf = self.buf[:size], self.buf[size + 2:]
                return json.loads(payload or b'{}')
            if line.startswith(b'PING'):
                self.s.sendall(b'PONG\r\n')
            if line.startswith(b'-ERR'):
                raise RuntimeError(line.decode()[:120])

    def request(self, subject, body):
        data = json.dumps(body).encode()
        self.s.sendall(b'PUB %s _INBOX.storecheck %d\r\n%s\r\n' % (subject.encode(), len(data), data))
        return self.message()


def streams(c):
    names = c.request('$JS.API.STREAM.NAMES', {}).get('streams') or []
    return {n: c.request(f'$JS.API.STREAM.INFO.{n}', {}).get('state', {}).get('messages') for n in sorted(names)}


out = {}
c = Client()
out['streams_before'] = streams(c)
c.request('$JS.API.STREAM.CREATE.STORECHECK', {'name': 'STORECHECK', 'subjects': ['storecheck.load'], 'storage': 'file'})
payload = os.urandom(512).hex().encode()
t = time.time()
for i in range(10000):
    c.s.sendall(b'PUB storecheck.load _INBOX.storecheck %d\r\n%s\r\n' % (len(payload), payload))
acks = sum(1 for _ in range(10000) if 'seq' in c.message())
out['publish_10000_acked_seconds'] = round(time.time() - t, 2)
out['acks'] = acks
info = c.request('$JS.API.STREAM.INFO.STORECHECK', {})
out['stream_messages'] = info.get('state', {}).get('messages')
c.request('$JS.API.STREAM.DELETE.STORECHECK', {})
out['streams_after'] = streams(c)
print(json.dumps(out))
