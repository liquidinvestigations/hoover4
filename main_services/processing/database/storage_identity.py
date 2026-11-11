"""The storage identity of this installation: database, table and bucket names, and the
store users.

``tasks/storage_identity.json`` defines each setting once:
its environment variable, its Compose default and its allowed form. A variable that is
absent gives the default, so a Compose deployment that sets none of them keeps the names
``Hoover4_Processing``, ``Hoover4_Collection_<name>``, the unprefixed Manticore tables and
the ``hoover4-system`` and ``hoover4-c-<name>`` buckets. The website and the agent
services read the same variables through checked copies of the definition.

A value outside its allowed form raises ``ValueError`` with the variable name only, so
the process stops at start and no credential reaches a log.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Mapping

DEFINITION_PATH = pathlib.Path(__file__).resolve().parent.parent / "tasks" / "storage_identity.json"
DEFINITION = json.loads(DEFINITION_PATH.read_text(encoding="utf-8"))
SETTINGS = DEFINITION["settings"]


def setting(name: str, environ: Mapping[str, str] | None = None) -> str:
    """The value of one setting, from ``environ`` (the process environment by default)."""
    environ = os.environ if environ is None else environ
    spec = SETTINGS[name]
    value = environ.get(spec["variable"], spec["default"])
    if not re.fullmatch(spec["pattern"], value):
        raise ValueError(f"{spec['variable']} is invalid.")
    return value


def global_database(environ: Mapping[str, str] | None = None) -> str:
    return f"{setting('clickhouse_database_prefix', environ)}_Processing"


def collection_database_prefix(environ: Mapping[str, str] | None = None) -> str:
    """The database name of a collection without the collection name."""
    return f"{setting('clickhouse_database_prefix', environ)}_Collection_"


def manticore_table(logical: str, environ: Mapping[str, str] | None = None) -> str:
    """The physical Manticore table of a logical table name.

    The shard ledger and the ClickHouse rows keep the logical names.
    """
    return f"{setting('manticore_table_prefix', environ)}{logical}"


def collection_bucket_name(collectionname: str, environ: Mapping[str, str] | None = None) -> str:
    """Return the bucket of a collection. Each ``_`` becomes ``-`` (``database.s3``)."""
    return f"{setting('collection_bucket_prefix', environ)}{collectionname.replace('_', '-')}"
