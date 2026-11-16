"""The file service of the shared Manticore text daemon. It uses the standard library only.

It runs as the container files in the pod of the daemon (shared.py manticore()), with the data folder of the daemon
mounted at DATA. The data folder is a block volume inside the guest of the pod, so no other pod can mount it. The
schema proxy of a zone uses this service for the collection export and the restore (main_services/processing/database/
manticore_files.py).

Each request carries the HTTP Basic credentials of a Manticore user whose name ends with _schema. The service checks
them with SHOW TABLES on the HTTP port of the daemon, so Manticore decides who the caller is and which tables the
caller sees:

  GET    /tables/<table>/<file>          a file of the table folder. The table must be in SHOW TABLES of the caller.
  PUT    /stage/<stage>/<table>/<file>   write a file into import/<user>/<stage>/<table>/ of the data folder.
  DELETE /stage/<stage>                  remove import/<user>/<stage>/.
  DELETE /import                         remove import/<user>/.
  GET    /ready                          200 without credentials.

A caller writes only below import/<user>/ of its own user and reads only the folders of its own tables. The schema
proxy of a zone holds the only schema user of the zone. The network policies of the namespace hoover-stores admit only
the schema proxies to the port of this service. Names hold lowercase letters, digits and underscores, and a
file name starts with the table name and a dot. The service follows no symbolic link.
"""
import base64, http.server, json, os, re, shutil, urllib.error, urllib.request

DATA = os.environ.get('MANTICORE_DATA', '/var/lib/manticore')
DAEMON = os.environ.get('MANTICORE_HTTP', 'http://127.0.0.1:9308')
PORT = int(os.environ.get('FILES_PORT', '9318'))
CHUNK = 1 << 20
NAME = re.compile(r'^[a-z0-9_]{1,128}$')
FILE = re.compile(r'^[a-z0-9_]{1,128}(\.[a-z0-9_]{1,32}){1,4}$')
STAGE = re.compile(r'^[a-z0-9]{1,64}$')
USER = re.compile(r'^[a-z0-9_]{1,120}_schema$')


class Refused(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def caller(header):
    """(user, tables) of the Basic credentials of a request, as Manticore sees them."""
    if not header.startswith('Basic '):
        raise Refused(401, 'the request has no Manticore credentials')
    try:
        user = base64.b64decode(header[6:], validate=True).decode().split(':', 1)[0]
    except ValueError:
        raise Refused(401, 'the Manticore credentials do not decode') from None
    if not USER.match(user):
        raise Refused(403, 'only the schema user of a zone uses this service')
    request = urllib.request.Request(f'{DAEMON}/sql?mode=raw', data=b'query=SHOW+TABLES', headers={'Authorization': header})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            rows = json.loads(response.read())[0].get('data') or []
    except urllib.error.HTTPError as error:
        raise Refused(401 if error.code in (401, 403) else 502, 'Manticore refused the credentials') from None
    return user, {row.get('Table') for row in rows}


def no_links(path):
    """Refuse a path below DATA with a symbolic link in it."""
    if os.path.realpath(path) != os.path.normpath(path) or not os.path.normpath(path).startswith(DATA + '/'):
        raise Refused(403, 'the path leaves the data folder')


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def answer(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def parts(self, count):
        parts = self.path.split('?', 1)[0].strip('/').split('/')
        if len(parts) != count:
            raise Refused(404, 'not found')
        return parts

    def run(self, method):
        try:
            if method == 'GET' and self.path == '/ready':
                return self.answer(200, {'ready': True})
            user, tables = caller(self.headers.get('Authorization', ''))
            if method == 'GET':
                kind, table, name = self.parts(3)
                if kind != 'tables' or not NAME.match(table) or not FILE.match(name) or not name.startswith(table + '.'):
                    raise Refused(400, 'the request names no file of a table')
                if table not in tables:
                    raise Refused(403, f'Manticore shows no table {table} to {user}')
                path = os.path.join(DATA, table, name)
                no_links(path)
                with open(path, 'rb', opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW)) as handle:
                    size = os.fstat(handle.fileno()).st_size
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Length', str(size))
                    self.end_headers()
                    left = size
                    while left > 0:
                        data = handle.read(min(CHUNK, left))
                        if not data:
                            break
                        self.wfile.write(data)
                        left -= len(data)
                return
            if method == 'PUT':
                kind, stage, table, name = self.parts(4)
                if kind != 'stage' or not STAGE.match(stage) or not NAME.match(table) or not FILE.match(name) \
                        or not name.startswith(table + '.'):
                    raise Refused(400, 'the request names no stage file of a table')
                length = int(self.headers.get('Content-Length') or -1)
                if length < 0:
                    raise Refused(411, 'the request has no length')
                folder = os.path.join(DATA, 'import', user, stage, table)
                os.makedirs(folder, mode=0o755, exist_ok=True)
                no_links(folder)
                path = os.path.join(folder, name)
                with open(path + '.part', 'wb', opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o644)) as handle:
                    left = length
                    while left > 0:
                        data = self.rfile.read(min(CHUNK, left))
                        if not data:
                            raise Refused(400, 'the request body ended early')
                        handle.write(data)
                        left -= len(data)
                os.replace(path + '.part', path)
                return self.answer(200, {'written': length})
            if method == 'DELETE' and self.path.split('?', 1)[0].strip('/') == 'import':
                folder = os.path.join(DATA, 'import', user)
                if os.path.lexists(folder):
                    no_links(folder)
                    shutil.rmtree(folder)
                return self.answer(200, {'removed': 'import'})
            if method == 'DELETE':
                kind, stage = self.parts(2)
                if kind != 'stage' or not STAGE.match(stage):
                    raise Refused(400, 'the request names no stage')
                folder = os.path.join(DATA, 'import', user, stage)
                if os.path.lexists(folder):
                    no_links(folder)
                    shutil.rmtree(folder)
                return self.answer(200, {'removed': stage})
            raise Refused(405, 'the method is not allowed')
        except Refused as error:
            self.close_connection = True
            return self.answer(error.status, {'error': str(error)})
        except (OSError, ValueError) as error:
            self.close_connection = True
            return self.answer(500, {'error': f'{type(error).__name__}: {str(error)[:200]}'})

    def do_GET(self):
        self.run('GET')

    def do_PUT(self):
        self.run('PUT')

    def do_DELETE(self):
        self.run('DELETE')

    def log_message(self, form, *args):
        print(f'{self.command} {self.path.split("?")[0]} {args[1] if len(args) > 1 else ""}', flush=True)


if __name__ == '__main__':
    os.umask(0o022)
    http.server.ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
