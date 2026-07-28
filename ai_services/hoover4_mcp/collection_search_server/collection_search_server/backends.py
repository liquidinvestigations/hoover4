"""Thin ClickHouse and Manticore clients for the collection search MCP server.

Both databases are talked to over plain HTTP rather than through a driver: the queries
here are a handful of SELECTs, and an HTTP call keeps the container small and its
dependency surface tiny (this image should not need to be rebuilt every time a driver
bumps a major version).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = float(os.getenv("BACKEND_TIMEOUT_SECONDS", "30"))

GLOBAL_DB = "Hoover4_Processing"


def collection_db(collectionname: str) -> str:
    """The ClickHouse database holding one collection's data."""
    return f"Hoover4_Collection_{collectionname}"


def _clickhouse_url() -> str:
    return os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123").rstrip("/")


def _manticore_url() -> str:
    return os.getenv("MANTICORE_URL", "http://manticore:9308").rstrip("/")


def clickhouse_query(sql: str, database: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Run a SELECT and return rows as dicts.

    Uses `JSONEachRow` rather than TSV so column types survive the round trip, and
    ClickHouse's own `param_*` mechanism for values so nothing is string-interpolated
    into the query.
    """
    query_params = {
        "database": database,
        "user": os.getenv("CLICKHOUSE_USER", "hoover4"),
        "password": os.getenv("CLICKHOUSE_PASSWORD", "hoover4"),
        "default_format": "JSONEachRow",
    }
    for key, value in (params or {}).items():
        query_params[f"param_{key}"] = value

    response = requests.post(
        _clickhouse_url(), params=query_params, data=sql.encode(), timeout=DEFAULT_TIMEOUT
    )
    if response.status_code != 200:
        raise RuntimeError(f"ClickHouse error {response.status_code}: {response.text[:400]}")

    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def manticore_query(sql: str) -> list[dict]:
    """Run one Manticore SQL statement over the HTTP endpoint and return its rows.

    Manticore's `/sql?mode=raw` returns a list with a single result object; an empty
    result set still carries an `error` field, which is checked here so a broken query
    surfaces as an exception instead of silently returning nothing.
    """
    response = requests.post(
        f"{_manticore_url()}/sql",
        params={"mode": "raw"},
        data={"query": sql},
        timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Manticore error {response.status_code}: {response.text[:400]}")

    payload = response.json()
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if payload.get("error"):
        raise RuntimeError(f"Manticore query failed: {payload['error']}")
    return payload.get("data", [])


def escape_manticore_string(value: str) -> str:
    """Escape a value for a single-quoted Manticore SQL string literal.

    Manticore has no parameter binding over the HTTP SQL endpoint, so this is the only
    barrier between user text and the query. Backslash first, then the quote — reversing
    the order would double-escape the backslashes introduced by the quote pass.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


#: Characters that are operators in Manticore's `MATCH()` extended query syntax. A user
#: question like "who paid @acme?" would otherwise be read as a field-prefix operator and
#: fail the query rather than searching for the words.
_MATCH_OPERATORS = '!"$()-/<@^|~*'


def sanitize_match_query(query: str) -> str:
    """Turn free text into a safe `MATCH()` expression.

    Deliberately strips operators instead of escaping them: the caller is an LLM writing
    natural-language search phrases, not someone composing Manticore syntax, so operator
    characters are noise. See open question Q7.
    """
    cleaned = "".join(" " if c in _MATCH_OPERATORS else c for c in query)
    return escape_manticore_string(" ".join(cleaned.split()))
