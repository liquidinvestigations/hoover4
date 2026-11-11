"""Read the cells of one table file in a separate process, for the parser sandbox.

calamine (a Rust extension) and SQLite are native code that reads an untrusted file inside
the worker process. With ``HOOVER4_PARSER_SANDBOX=bwrap``, :func:`cells` starts this module
as ``python -m tasks.sandbox_cells <reader> <path> <params>`` through
:mod:`tasks.sandbox`, so the reader runs without the credentials and the network of the
worker. The child writes one JSON line for each progress report (``p``), each cell
(``c``) and a failure (``e``). The parent builds the ``RawCell`` values from plain JSON
fields, so it never decodes an object of the child.

Without the setting, :func:`cells` calls the reader in the worker process.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Callable, Optional

READERS = ("calamine", "sqlite")


def _reader(name: str, path: str, params: dict, on_progress):
    if name == "calamine":
        from tasks.P3_parse_files.table_readers import read_calamine_cells
        return read_calamine_cells(path, on_progress=on_progress)
    from tasks.P3_parse_files.table_sqlite import SqliteLimits, read_sqlite_cells
    return read_sqlite_cells(path, SqliteLimits(**params), on_progress=on_progress)


def _encode(cell) -> dict:
    row = dataclasses.asdict(cell)
    if row.get("time_value") is not None:
        row["time_value"] = row["time_value"].isoformat()
    return row


def cells(name: str, path: str, params: dict | None = None,
          on_progress: Optional[Callable[[str, int], None]] = None):
    """The cells of ``path`` from the reader ``name``, as ``(sheet_id, sheet_name, RawCell)``."""
    from tasks import sandbox
    if name not in READERS:
        raise ValueError(f"no sandboxed reader named {name!r}")
    if not sandbox.enabled():
        yield from _reader(name, path, params or {}, on_progress)
        return
    from tasks.P3_parse_files.table_readers import RawCell
    with tempfile.TemporaryFile() as errors:
        child = sandbox.Popen([sys.executable, "-m", "tasks.sandbox_cells", name, path, json.dumps(params or {})],
                              stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL, cwd="/app",
                              bufsize=1 << 20)
        failure = ""
        try:
            for raw in child.stdout:
                record = json.loads(raw)
                if "p" in record and on_progress:
                    on_progress(str(record["p"][0]), int(record["p"][1]))
                elif "c" in record:
                    sheet_id, sheet_name, fields = record["c"]
                    if fields.get("time_value"):
                        fields["time_value"] = datetime.fromisoformat(fields["time_value"])
                    yield int(sheet_id), str(sheet_name), RawCell(**fields)
                elif "e" in record:
                    failure = str(record["e"])[:2000]
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
        if failure or child.returncode:
            errors.seek(0)
            raise RuntimeError(failure or f"{name} reader exited with {child.returncode}: "
                               f"{errors.read()[-500:].decode(errors='replace')}")


def main() -> None:
    name, path, params = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])

    def progress(sheet: str, row: int) -> None:
        print(json.dumps({"p": [sheet, row]}), flush=True)

    try:
        for sheet_id, sheet_name, cell in _reader(name, path, params, progress):
            sys.stdout.write(json.dumps({"c": [sheet_id, sheet_name, _encode(cell)]}) + "\n")
    except BaseException as exc:  # noqa: BLE001 - a Rust panic derives from BaseException
        print(json.dumps({"e": f"{type(exc).__name__}: {exc}"}), flush=True)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
