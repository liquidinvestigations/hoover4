"""The table files of the Manticore text daemon in a collection export and restore.

The schema operations ``export_tables`` and ``import_tables`` (:mod:`database.manticore_schema`)
use this module. Each export artifact is ``manticore/<table>.tar.zst`` in the export
folder: a zstd tar of the files that ``FREEZE`` names, with the base names of the daemon.

Two backends read and write the table files:

* :class:`LocalFiles` when this process mounts the data folder of the daemon (Compose and
  the local layout of k3s). It reads ``/stores/manticore`` and stages an import in
  ``/stores/manticore-restore``. Both are mounts of the daemon data folder.
* :class:`ServiceFiles` when ``MANTICORE_FILES_URL`` is set (the site layout of k3s). The
  data folder is a block volume inside the guest of the daemon pod, so no other pod can
  mount it. The file service of that pod (``k3s/hoover/stores/manticore_file_service.py``)
  reads and writes the files with the Manticore user and password of the caller. It gives
  the files of a table only to a user that Manticore shows the table to. It keeps the
  import stages of each user in ``import/<user>/`` of the data folder.

``IMPORT TABLE`` of Manticore 29.9 copies the staged files into the data folder and leaves
the source files in place, also from another file system. The import removes its stage
after the last table.

The export folder and the restore source are subfolders of the backup root
(``HOOVER4_BACKUP_ROOT``). A caller names a subfolder, never a path.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import secrets
import tarfile
import time

#: The backup root of this process. The schema proxy of a zone mounts the backup claim of the zone here.
BACKUP_ROOT = os.environ.get("HOOVER4_BACKUP_ROOT", "/backups")
#: Where the daemon keeps its tables, as the daemon sees it. ``FREEZE`` answers with these paths.
DAEMON_DATA_ROOT = "/var/lib/manticore"
#: The data folder of the daemon in this process, read-only (Compose).
LOCAL_DATA_ROOT = "/stores/manticore"
#: The data folder of the daemon in this process, read-write, for the import stages only (Compose).
LOCAL_RESTORE_ROOT = "/stores/manticore-restore"
#: The name prefix of a local import stage in the data folder. ``IMPORT TABLE`` does not take a
#: path verbatim when a folder of the path starts with a dot, so the name has no leading dot.
LOCAL_STAGE_PREFIX = "restore-"
#: A frozen table file up to this size is read whole before it enters the archive.
SMALL_FILE_BYTES = 4 * 1024 * 1024
#: The block size of a streamed copy.
CHUNK = 1024 * 1024

_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
_TABLE_RE = re.compile(r"^[a-z0-9_]+$")
_FILE_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


class FilesRefused(ValueError):
    """A folder, table or file name that this module does not accept."""


def backup_folder(name) -> str:
    """The absolute path of an existing subfolder ``name`` of the backup root, or refuse it."""
    if not isinstance(name, str) or not _FOLDER_RE.match(name) or name in (".", ".."):
        raise FilesRefused("the export names one folder of the backup root: letters, digits, dot, dash and underscore")
    root = os.path.realpath(BACKUP_ROOT)
    path = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(path) != root or not os.path.isdir(path):
        raise FilesRefused(f"the backup root has no folder {name}")
    return path


def file_name(table: str, path: str) -> str:
    """The base name of a frozen file of ``table``, from the daemon path that ``FREEZE`` gives."""
    folder, name = os.path.split(path)
    if folder != f"{DAEMON_DATA_ROOT}/{table}" or not _FILE_RE.match(name) or not name.startswith(table + "."):
        raise FilesRefused(f"FREEZE {table} named the file {path}, which is not a file of the table")
    return name


class LocalFiles:
    """The table files through the mounts of the daemon data folder in this process."""

    def __init__(self, data_root=LOCAL_DATA_ROOT, restore_root=LOCAL_RESTORE_ROOT):
        self.data_root = data_root
        self.restore_root = restore_root

    def table_bytes(self, table):
        folder = os.path.join(self.data_root, table)
        if not os.path.isdir(folder):
            return 0
        return sum(entry.stat().st_size for entry in os.scandir(folder) if entry.is_file())

    def read(self, table, name):
        with open(os.path.join(self.data_root, table, name), "rb") as handle:
            return handle.read()

    def open(self, table, name):
        """(stream, size) of a table file."""
        path = os.path.join(self.data_root, table, name)
        return open(path, "rb"), os.path.getsize(path)

    def write(self, stage, table, name, stream, size):
        folder = os.path.join(self.restore_root, LOCAL_STAGE_PREFIX + stage, table)
        os.makedirs(folder, exist_ok=True)
        # The daemon runs as its own user, and it reads the staged files.
        os.chmod(os.path.dirname(folder), 0o777)
        os.chmod(folder, 0o777)
        path = os.path.join(folder, name)
        with open(path, "wb") as handle:
            _copy(stream, handle, size)
        os.chmod(path, 0o666)

    def daemon_path(self, stage, table):
        return f"{DAEMON_DATA_ROOT}/{LOCAL_STAGE_PREFIX}{stage}/{table}/{table}"

    def remove(self, stage):
        import shutil

        shutil.rmtree(os.path.join(self.restore_root, LOCAL_STAGE_PREFIX + stage), ignore_errors=True)


class ServiceFiles:
    """The table files through the file service of the daemon pod, with the Manticore user of this process."""

    def __init__(self, url, user, password, timeout=600):
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        self.host, self.port = parts.hostname, parts.port or 80
        self.user = user
        self.timeout = timeout
        self.headers = {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}

    def _request(self, method, path, body=None, headers=None):
        import http.client

        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        connection.request(method, path, body=body, headers={**self.headers, **(headers or {})})
        response = connection.getresponse()
        if response.status >= 300:
            message = response.read(1000).decode(errors="replace")
            connection.close()
            raise RuntimeError(f"The Manticore file service answered {response.status} to {method} {path}: {message}")
        return connection, response

    def table_bytes(self, table):
        return 0

    def read(self, table, name):
        connection, response = self._request("GET", f"/tables/{table}/{name}")
        try:
            return response.read()
        finally:
            connection.close()

    def open(self, table, name):
        connection, response = self._request("GET", f"/tables/{table}/{name}")
        return _Closing(response, connection), int(response.headers["Content-Length"])

    def write(self, stage, table, name, stream, size):
        connection, response = self._request("PUT", f"/stage/{stage}/{table}/{name}", body=_Limited(stream, size),
                                             headers={"Content-Length": str(size)})
        response.read()
        connection.close()

    def daemon_path(self, stage, table):
        return f"{DAEMON_DATA_ROOT}/import/{self.user}/{stage}/{table}/{table}"

    def remove(self, stage):
        try:
            connection, response = self._request("DELETE", f"/stage/{stage}")
            response.read()
            connection.close()
        except (OSError, RuntimeError):
            pass


class _Closing:
    def __init__(self, response, connection):
        self.response, self.connection = response, connection

    def read(self, size=-1):
        return self.response.read(size)

    def close(self):
        self.connection.close()


class _Limited:
    """A reader of exactly ``size`` bytes of a stream, so a streamed request body has its declared length."""

    def __init__(self, stream, size):
        self.stream, self.left = stream, size

    def read(self, size=-1):
        if self.left <= 0:
            return b""
        data = self.stream.read(self.left if size < 0 else min(size, self.left))
        if not data:
            raise RuntimeError("a table file of the export ended early")
        self.left -= len(data)
        return data


def _copy(source, target, size):
    left = size
    while left > 0:
        data = source.read(min(CHUNK, left))
        if not data:
            raise RuntimeError("a table file of the export ended early")
        target.write(data)
        left -= len(data)


def backend():
    """The backend of this process: the file service with ``MANTICORE_FILES_URL``, the local mounts otherwise."""
    from database import storage_identity

    url = os.environ.get("MANTICORE_FILES_URL", "")
    if url:
        return ServiceFiles(url, storage_identity.setting("manticore_user"), storage_identity.setting("manticore_password"))
    return LocalFiles()


def stable_read(read, name, attempts: int = 20, pause: float = 0.25) -> bytes:
    """Read a small file until two reads in a row are equal, and a ``.meta`` file is valid JSON.

    ``read`` reads the whole file. The daemon can rewrite a small file during a freeze, and
    a copy of the earlier size then holds a cut file. The archive entry gets the size of the
    bytes that were read.
    """
    previous = None
    for _ in range(attempts):
        data = read()
        valid = True
        if name.endswith(".meta"):
            try:
                json.loads(data)
            except ValueError:
                valid = False
        if valid and data == previous:
            return data
        previous = data if valid else None
        time.sleep(pause)
    raise RuntimeError(
        f"{name} kept changing during the freeze, so the export cannot hold a consistent "
        f"copy of it. Stop the writers of the collection and export again."
    )


class _HashingWriter:
    def __init__(self, fileobj):
        self._file = fileobj
        self._digest = hashlib.sha256()
        self.bytes_written = 0

    def write(self, data) -> int:
        self._file.write(data)
        self._digest.update(data)
        self.bytes_written += len(data)
        return len(data)

    def flush(self) -> None:
        self._file.flush()

    @property
    def hexdigest(self) -> str:
        return self._digest.hexdigest()


class _HashingReader:
    def __init__(self, fileobj, expected: str, name: str):
        self._file = fileobj
        self._digest = hashlib.sha256()
        self._expected = expected
        self._name = name

    def read(self, size: int = -1) -> bytes:
        data = self._file.read(size)
        self._digest.update(data)
        return data

    def verify(self) -> None:
        if self._expected and self._digest.hexdigest() != self._expected:
            raise RuntimeError(f"{self._name} does not match the checksum in the manifest: expected {self._expected}, "
                               f"read {self._digest.hexdigest()}. The artifact is damaged. Restore from another backup.")


def add_file(tar, files, table, name) -> int:
    """Add one frozen table file to the archive and return its size."""
    info = tarfile.TarInfo(name)
    info.mode = 0o600
    info.mtime = int(time.time())
    stream, size = files.open(table, name)
    try:
        if size > SMALL_FILE_BYTES:
            info.size = size
            tar.addfile(info, _Limited(stream, size))
            return size
        first = [stream.read()]
    finally:
        stream.close()
    data = stable_read(lambda: first.pop() if first else files.read(table, name), name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))
    return len(data)


def export_tables(collection, folder, files, progress=None) -> dict:
    """Write ``manticore/<table>.tar.zst`` of each text table of a collection into the export folder ``folder``.

    ``FREEZE`` flushes the RAM chunk of a table, holds its files unchanged and names them.
    Every freeze is released, also after a failure, because a frozen table takes no more
    writes. ``progress(done, total)`` receives the bytes copied.
    """
    import zstandard

    from database.manticore import TEXT, endpoint_for_table, get_manticore_client, list_collection_tables

    tables = list(dict.fromkeys(t for t in list_collection_tables(collection) if endpoint_for_table(t) == TEXT))
    target = os.path.join(folder, "manticore")
    os.makedirs(target, exist_ok=True)
    total = sum(files.table_bytes(t) for t in tables) if progress else 0
    if progress:
        progress(0, total)
    artifacts, done = [], 0
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        for table in tables:
            cursor.execute(f"FREEZE {table}")
            names = sorted({file_name(table, row[0]) for row in cursor.fetchall()})
            try:
                path = os.path.join(target, f"{table}.tar.zst")
                raw = 0
                with open(path, "wb") as handle:
                    writer = _HashingWriter(handle)
                    with zstandard.ZstdCompressor(level=3).stream_writer(writer, closefd=False) as stream:
                        with tarfile.open(fileobj=stream, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                            for name in names:
                                size = add_file(tar, files, table, name)
                                raw += size
                                done += size
                                if progress:
                                    progress(done, max(total, done))
            finally:
                cursor.execute(f"UNFREEZE {table}")
            artifacts.append({"table": table, "path": f"manticore/{table}.tar.zst", "source_bytes": raw,
                              "bytes": writer.bytes_written, "sha256": writer.hexdigest})
    return {"tables": artifacts, "source_bytes": done}


def target_table(collection, source) -> str:
    """The table of this installation for the export table ``source`` of ``collection``.

    The export keeps the physical names of its installation, with that table prefix. The
    import keeps the name after the prefix and adds the prefix of this process, so a table
    can only arrive under this prefix.
    """
    from database import manticore

    match = re.search(rf"(?:^|_)({re.escape(collection)}_(?:vfs|entities|[1-9][0-9]*_pages))$", source or "")
    if not match:
        raise FilesRefused(f"{source!r} is not a text table of the collection {collection}")
    logical = match.group(1)
    if logical.endswith("_pages"):
        return manticore.shard_table_from_name(logical[:-len("_pages")])
    return manticore.table_prefix() + logical


def _artifact_path(folder, path) -> str:
    full = os.path.realpath(os.path.join(folder, path if isinstance(path, str) else ""))
    if os.path.dirname(full) != os.path.join(os.path.realpath(folder), "manticore") or not full.endswith(".tar.zst"):
        raise FilesRefused(f"the manifest names the artifact {path!r} outside the manticore folder of the export")
    return full


def import_tables(collection, folder, files, progress=None) -> dict:
    """Import the text tables of the export folder ``folder`` into the tables of this installation.

    Each artifact is checked against its SHA-256 in the manifest while it is read. Its
    files are renamed to the target table and staged, the target table is dropped when it
    exists, and ``IMPORT TABLE`` copies the staged files into the data folder. The vectors
    tables are not in an export. ``progress(done, total)`` receives the bytes staged.
    """
    import zstandard

    from database.manticore import TEXT, _execute_ddl, endpoint_for_table

    with open(os.path.join(folder, "manifest.json")) as handle:
        manifest = json.load(handle)
    if manifest.get("collectionname") != collection:
        raise FilesRefused(f"the export holds the collection {manifest.get('collectionname')!r}, not {collection!r}")
    listed = (manifest.get("stores") or {}).get("manticore", {}).get("tables") or []
    artifacts = [a for a in listed if endpoint_for_table(str(a.get("table", ""))) == TEXT]
    plan = [(a, target_table(collection, str(a["table"])), _artifact_path(folder, a.get("path"))) for a in artifacts]
    total = sum(int(a.get("source_bytes") or 0) for a in artifacts)
    stage = secrets.token_hex(8)
    restored, done = [], 0
    if progress:
        progress(0, total)
    try:
        for artifact, table, path in plan:
            source = str(artifact["table"])
            with open(path, "rb") as raw:
                reader = _HashingReader(raw, artifact.get("sha256", ""), artifact["path"])
                with zstandard.ZstdDecompressor().stream_reader(reader) as stream:
                    with tarfile.open(fileobj=stream, mode="r|") as tar:
                        for member in tar:
                            if not member.isfile() or "/" in member.name or not member.name.startswith(source + "."):
                                raise FilesRefused(f"{artifact['path']} holds {member.name!r}, which is not a file of {source}")
                            name = table + member.name[len(source):]
                            if not _FILE_RE.match(name):
                                raise FilesRefused(f"{artifact['path']} holds the file name {member.name!r}")
                            files.write(stage, table, name, tar.extractfile(member), member.size)
                            done += member.size
                            if progress:
                                progress(done, max(total, done))
                    while stream.read(CHUNK):
                        pass
                reader.verify()
            _execute_ddl(f"DROP TABLE IF EXISTS {table}")
            _execute_ddl(f"IMPORT TABLE {table} FROM '{files.daemon_path(stage, table)}'")
            restored.append(table)
    finally:
        files.remove(stage)
    return {"tables": restored, "skipped_vectors": len(listed) - len(artifacts)}
