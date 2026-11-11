"""The storage identity of this installation, for the agent services.

This is a copy of main_services/processing/tasks/storage_identity.json, because the agent
images do not contain the processing code. scripts/deploy.py_tests compares the two.
Each setting reads its environment variable. An absent variable gives the Compose default.
A value outside its allowed form raises ``ValueError`` with the variable name only.
"""

from __future__ import annotations

import os
import re
from typing import Mapping

#: name: (environment variable, Compose default, allowed form)
SETTINGS = {
    "clickhouse_database_prefix": ("HOOVER4_CLICKHOUSE_DB_PREFIX", "Hoover4", r"[A-Za-z_][A-Za-z0-9_]*"),
    "manticore_table_prefix": ("HOOVER4_MANTICORE_TABLE_PREFIX", "", r"([a-z][a-z0-9_]*)?"),
    "system_bucket": ("S3_SYSTEM_BUCKET", "hoover4-system", r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"),
    "collection_bucket_prefix": ("S3_COLLECTION_BUCKET_PREFIX", "hoover4-c-", r"[a-z0-9][a-z0-9.-]*"),
    "clickhouse_user": ("CLICKHOUSE_USER", "hoover4", r".+"),
    "clickhouse_password": ("CLICKHOUSE_PASSWORD", "hoover4", r".*"),
    "manticore_user": ("MANTICORE_USER", "manticore", r".+"),
    "manticore_password": ("MANTICORE_PASSWORD", "manticore", r".*"),
    "s3_access_key": ("S3_ACCESS_KEY", "hoover4-blobs-rw", r".+"),
    "s3_secret_key": ("S3_SECRET_KEY", "hoover4-garage-blob-secret-key-0", r".+"),
}


def setting(name: str, environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    variable, default, pattern = SETTINGS[name]
    value = environ.get(variable, default)
    if not re.fullmatch(pattern, value):
        raise ValueError(f"{variable} is invalid.")
    return value


def global_database(environ: Mapping[str, str] | None = None) -> str:
    return f"{setting('clickhouse_database_prefix', environ)}_Processing"


def collection_database(collectionname: str, environ: Mapping[str, str] | None = None) -> str:
    return f"{setting('clickhouse_database_prefix', environ)}_Collection_{collectionname}"


def manticore_table(logical: str, environ: Mapping[str, str] | None = None) -> str:
    """The physical Manticore table of a logical name such as ``<shard>_pages``."""
    return f"{setting('manticore_table_prefix', environ)}{logical}"


def collection_bucket(collectionname: str, environ: Mapping[str, str] | None = None) -> str:
    return f"{setting('collection_bucket_prefix', environ)}{collectionname.replace('_', '-')}"
