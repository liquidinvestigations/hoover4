"""The Manticore schema operations of Hoover, and the schema proxy that runs them for one zone.

Every create, alter and drop of a Hoover Manticore table goes through :func:`run` with an
operation name and its arguments. No caller sends SQL. Each operation checks its arguments
and builds fixed statements from the table names of :mod:`database.manticore`, so every
name has the table prefix of this process (``HOOVER4_MANTICORE_TABLE_PREFIX``).

Two modes use the same operations:

* Without ``MANTICORE_SCHEMA_URL`` (Compose), :mod:`database.manticore` calls :func:`run`
  in its own process with its own Manticore user.
* With ``MANTICORE_SCHEMA_URL`` (the site layout of k3s), :mod:`database.manticore` sends
  the operation to the schema proxy of its zone. The services of the zone hold a Manticore
  user that can read and write rows, and cannot create, alter or drop a table. Only the
  proxy holds the schema user of the zone. Manticore lets a user with the schema right
  create a distributed table that names a table of another user, and then read that
  table through it. The proxy has no operation that creates a distributed table, and it
  builds every table name from its own prefix, so a zone cannot name a table of another
  zone.

The operations (``OPERATIONS``):

| Operation | Arguments | Effect |
|---|---|---|
| ``create_pages_table`` | ``collection``, ``shard`` | The pages table of one shard on the text daemon. |
| ``create_vectors_table`` | ``collection``, ``shard``, ``dims`` | The vectors table of one shard on the vectors daemon. |
| ``create_vfs_table`` | ``collection`` | The structure table of a collection. |
| ``create_entities_table`` | ``collection`` | The facet-term table of a collection. |
| ``add_pages_column`` | ``table``, ``column`` | A missing column of a pages table, with the type of the pages DDL. |
| ``drop_collection_tables`` | ``collection`` | Every table of a collection on both daemons. |
| ``drop_collection_vector_tables`` | ``collection`` | The vectors tables of a collection. |
| ``migrate`` | ``collections`` (name to shard indexes) | The Manticore migration of Hoover. |
| ``export_tables`` | ``collection``, ``export`` | The text tables of a collection into the export folder. |
| ``import_tables`` | ``collection``, ``export`` | The text tables of an export folder into the tables of this prefix. |
| ``status`` | none | The load counters of ``SHOW STATUS`` of both daemons (``STATUS_COUNTERS``). |

``export`` names one folder of the backup root (:mod:`database.manticore_files`), never a
path. ``import_tables`` imports each table under this prefix and the name after the
prefix in the export, so an export of another installation imports into the tables of
this one. ``status`` changes nothing. Its counters cover the whole daemon, also the
tables of the other zones of a site.

The proxy (``python -m database.manticore_schema serve``) takes ``POST /operation`` with
the JSON body ``{"operation": ..., "arguments": {...}}`` and the header
``Authorization: Bearer <token>``. ``MANTICORE_SCHEMA_TOKEN`` allows every operation.
``MANTICORE_STATUS_TOKEN``, when set, allows ``status`` only: the website holds it. The
proxy answers ``{"result": ...}``, or ``{"error": ...}`` with status 400 for refused
arguments, 401 for a wrong token, 403 for an operation that the token does not allow and
502 for a Manticore error. ``GET /ready`` answers 200. The proxy refuses to start without
a token or a table prefix.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re

log = logging.getLogger(__name__)

#: The largest request body of the proxy, in bytes.
MAX_BODY = 1 << 20
#: The largest shard index and the largest shard count of one collection in a request.
MAX_SHARD = 1_000_000
MAX_SHARDS = 100_000


class Refused(ValueError):
    """The operation or its arguments are not allowed."""


def _collection(arguments: dict) -> str:
    from database.clickhouse import validate_collectionname

    name = arguments["collection"]
    try:
        return validate_collectionname(name)
    except ValueError as error:
        raise Refused(str(error)) from None


def _shard(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= MAX_SHARD:
        raise Refused(f"a shard index must be an integer from 1 to {MAX_SHARD}")
    return value


def _own_table(table) -> str:
    """Return a table name of this prefix, or refuse it."""
    from database import manticore

    prefix = manticore.table_prefix()
    if not isinstance(table, str) or not table.startswith(prefix) or not re.fullmatch(r"[a-z0-9_]+", table):
        raise Refused("the table does not belong to this installation")
    return table


def _pages_table(table) -> str:
    """Return the name of a pages table of this prefix, or refuse it."""
    from database import manticore

    table = _own_table(table)
    logical = table[len(manticore.table_prefix()):]
    if not logical.endswith(f"_{manticore.PAGES_TABLE_SUFFIX}"):
        raise Refused("the table is not a shard pages table")
    try:
        if manticore.shard_table_from_name(logical[:-len(manticore.PAGES_TABLE_SUFFIX) - 1]) != table:
            raise ValueError
    except ValueError:
        raise Refused("the table is not a shard pages table") from None
    return table


def page_columns() -> dict[str, str]:
    """``{column: type}`` of a pages table, from the pages DDL."""
    from database.manticore import pages_table_ddl

    body = pages_table_ddl("t")
    inner = body[body.index("(") + 1:body.rindex(")")]
    columns = {}
    for line in inner.split(","):
        match = re.match(r"\s*([a-z_0-9]+)\s+([a-z0-9]+)", line)
        if match:
            columns[match.group(1)] = match.group(2)
    return columns


def create_pages_table(arguments):
    from database import manticore

    table = manticore.shard_table_name(_collection(arguments), _shard(arguments["shard"]))
    manticore._execute_ddl(manticore.pages_table_ddl(table))
    return table


def create_vectors_table(arguments):
    from database import manticore

    dims = arguments["dims"]
    if not isinstance(dims, int) or isinstance(dims, bool) or not 1 <= dims <= 65535:
        raise Refused("dims must be an integer from 1 to 65535")
    table = manticore.vectors_table_name(_collection(arguments), _shard(arguments["shard"]))
    manticore._execute_ddl(manticore.vectors_table_ddl(table, dims), manticore.VECTORS)
    return table


def create_vfs_table(arguments):
    from database import manticore

    table = manticore.vfs_table_name(_collection(arguments))
    manticore._execute_ddl(manticore.vfs_table_ddl(table))
    return table


def create_entities_table(arguments):
    from database import manticore

    table = manticore.entities_table_name(_collection(arguments))
    manticore._execute_ddl(manticore.entities_table_ddl(table))
    return table


def add_pages_column(arguments):
    from database import manticore

    table = _pages_table(arguments["table"])
    column = arguments["column"]
    kind = page_columns().get(column) if isinstance(column, str) else None
    if kind is None:
        raise Refused("the column is not a column of the pages DDL")
    manticore._execute_ddl(f"ALTER TABLE {table} ADD COLUMN {column} {kind}", manticore.TEXT)
    return {"table": table, "column": column, "type": kind}


def drop_collection_tables(arguments):
    from database import manticore

    collection = _collection(arguments)
    dropped = []
    for table in manticore.list_collection_tables(collection):
        manticore._execute_ddl(f"drop table if exists {_own_table(table)}", manticore.endpoint_for_table(table))
        dropped.append(table)
    if dropped:
        log.warning("Dropped Manticore tables for collection %s: %s", collection, dropped)
    return dropped


def drop_collection_vector_tables(arguments):
    from database import manticore

    collection = _collection(arguments)
    pattern = re.compile(manticore._SHARD_TABLE_RE_TEMPLATE.format(coll=re.escape(manticore.table_prefix() + collection)))
    tables = sorted(t for t in manticore._list_all_tables(manticore.VECTORS)
                    if pattern.match(t) and t.endswith(f"_{manticore.VECTORS_TABLE_SUFFIX}"))
    for table in tables:
        manticore._execute_ddl(f"drop table if exists {_own_table(table)}", manticore.VECTORS)
    return tables


def migrate(arguments):
    """Create the missing tables of each collection, and drop the earlier vectors tables of the text daemon.

    ``collections`` maps each collection to the shard indexes of its ledger. The structure
    and facet-term tables have no ledger, so each collection gets them. A recovered table
    is empty, and ``main.py reindex-collection`` fills it again.
    """
    from database import manticore

    collections = arguments["collections"]
    if not isinstance(collections, dict) or not all(isinstance(v, list) for v in collections.values()):
        raise Refused("collections must map each collection to a list of shard indexes")
    if sum(len(v) for v in collections.values()) > MAX_SHARDS:
        raise Refused(f"a migration takes at most {MAX_SHARDS} shards")
    created = 0
    for collection, shards in sorted(collections.items()):
        create_vfs_table({"collection": collection})
        create_entities_table({"collection": collection})
        for shard in shards:
            create_pages_table({"collection": collection, "shard": shard})
            created += 1
        if shards:
            log.info("Collection %s: ensured %d shard tables exist", collection, len(shards))
    # Another installation can share the daemon under another prefix, so only the
    # tables of this prefix are dropped.
    prefix = manticore.table_prefix()
    dropped = []
    for table in manticore._list_all_tables(manticore.TEXT):
        if not table.endswith(f"_{manticore.VECTORS_TABLE_SUFFIX}") or not table.startswith(prefix):
            continue
        manticore._execute_ddl(f"drop table if exists {_own_table(table)}", manticore.TEXT)
        log.warning("Dropped old vectors table %s. Run reindex-collection with --vectors-only.", table)
        dropped.append(table)
    return {"collections": len(collections), "shards": created, "dropped": dropped}


def _export_folder(arguments) -> str:
    from database import manticore_files

    try:
        return manticore_files.backup_folder(arguments["export"])
    except manticore_files.FilesRefused as error:
        raise Refused(str(error)) from None


def export_tables(arguments, progress=None):
    from database import manticore_files

    collection = _collection(arguments)
    folder = _export_folder(arguments)
    try:
        return manticore_files.export_tables(collection, folder, manticore_files.backend(), progress)
    except manticore_files.FilesRefused as error:
        raise Refused(str(error)) from None


def import_tables(arguments, progress=None):
    from database import manticore_files

    collection = _collection(arguments)
    folder = _export_folder(arguments)
    try:
        return manticore_files.import_tables(collection, folder, manticore_files.backend(), progress)
    except manticore_files.FilesRefused as error:
        raise Refused(str(error)) from None


#: The counters of ``SHOW STATUS`` that ``status`` returns: the ones the admin load panel shows.
STATUS_COUNTERS = ("uptime", "load", "load_primary", "load_secondary", "workers_total", "workers_active",
                   "work_queue_length")


def status(arguments):
    """``{daemon: [{"Counter": name, "Value": value}]}`` of the text and the vectors daemon."""
    from database import manticore

    result = {}
    for daemon, endpoint in (("manticore", manticore.TEXT), ("manticore-vectors", manticore.VECTORS)):
        with manticore.get_manticore_client(endpoint) as cnx:
            cursor = cnx.cursor()
            cursor.execute("SHOW STATUS")
            rows = cursor.fetchall()
        result[daemon] = [{"Counter": str(name), "Value": str(value)} for name, value in rows
                          if name in STATUS_COUNTERS]
    return result


#: Each operation, its function and the names of its arguments.
OPERATIONS = {
    "create_pages_table": (create_pages_table, {"collection", "shard"}),
    "create_vectors_table": (create_vectors_table, {"collection", "shard", "dims"}),
    "create_vfs_table": (create_vfs_table, {"collection"}),
    "create_entities_table": (create_entities_table, {"collection"}),
    "add_pages_column": (add_pages_column, {"table", "column"}),
    "drop_collection_tables": (drop_collection_tables, {"collection"}),
    "drop_collection_vector_tables": (drop_collection_vector_tables, {"collection"}),
    "migrate": (migrate, {"collections"}),
    "export_tables": (export_tables, {"collection", "export"}),
    "import_tables": (import_tables, {"collection", "export"}),
    "status": (status, set()),
}
#: The operations that report the bytes of their work to an in-process caller.
WITH_PROGRESS = {"export_tables", "import_tables"}
#: The operations that the status token allows.
STATUS_OPERATIONS = {"status"}


def run(operation, arguments, progress=None):
    """Check and run one operation in this process. Raise :class:`Refused` for a refused request."""
    if not isinstance(operation, str):
        raise Refused("the operation must be a name")
    if operation not in OPERATIONS:
        raise Refused(f"unknown operation {operation!r}")
    function, names = OPERATIONS[operation]
    if not isinstance(arguments, dict) or set(arguments) != names:
        raise Refused(f"{operation} takes the arguments {', '.join(sorted(names)) or 'none'}")
    if operation in WITH_PROGRESS:
        return function(arguments, progress)
    return function(arguments)


# ----------------------------------------------------------------------------------------------------------------------
# The proxy
# ----------------------------------------------------------------------------------------------------------------------

def handle(token: str, authorization: str, body: bytes, status_token: str = "") -> tuple[int, dict]:
    """The status and the JSON answer of one request to ``POST /operation``.

    ``token`` allows every operation. ``status_token``, when it is not empty, allows the
    operations of ``STATUS_OPERATIONS`` only.
    """
    given = authorization.encode()
    full = hmac.compare_digest(given, f"Bearer {token}".encode())
    limited = bool(status_token) and hmac.compare_digest(given, f"Bearer {status_token}".encode())
    if not full and not limited:
        return 401, {"error": "the proxy credential is not valid"}
    try:
        request = json.loads(body)
        if not isinstance(request, dict) or set(request) != {"operation", "arguments"}:
            raise Refused("the request must hold operation and arguments only")
        if not full and (not isinstance(request["operation"], str) or request["operation"] not in STATUS_OPERATIONS):
            return 403, {"error": "this credential allows the status operation only"}
        return 200, {"result": run(request["operation"], request["arguments"])}
    except (Refused, json.JSONDecodeError, UnicodeDecodeError) as error:
        return 400, {"error": str(error)}
    except Exception as error:  # a Manticore error
        log.exception("schema operation failed")
        return 502, {"error": f"Manticore refused the statement: {str(error)[:300]}"}


def serve(port: int = 8080) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from database import manticore

    token = os.environ.get("MANTICORE_SCHEMA_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("MANTICORE_SCHEMA_TOKEN must hold at least 32 characters.")
    status_token = os.environ.get("MANTICORE_STATUS_TOKEN", "")
    if status_token and (len(status_token) < 32 or status_token == token):
        raise SystemExit("MANTICORE_STATUS_TOKEN must hold at least 32 characters and differ from the schema token.")
    if not manticore.table_prefix():
        raise SystemExit("HOOVER4_MANTICORE_TABLE_PREFIX must not be empty for the schema proxy.")

    class Handler(BaseHTTPRequestHandler):
        def answer(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.answer(200, {"ready": True}) if self.path == "/ready" else self.answer(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if self.path != "/operation":
                return self.answer(404, {"error": "not found"})
            if length > MAX_BODY:
                return self.answer(413, {"error": "the request is too large"})
            status, payload = handle(token, self.headers.get("Authorization", ""), self.rfile.read(length), status_token)
            log.info("operation status %s", status)
            self.answer(status, payload)

        def log_message(self, *args):
            return None

    log.info("Manticore schema proxy for the prefix %s on port %d", manticore.table_prefix(), port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if sys.argv[1:] != ["serve"]:
        raise SystemExit("Usage: python -m database.manticore_schema serve")
    serve(int(os.environ.get("MANTICORE_SCHEMA_PORT", "8080")))
