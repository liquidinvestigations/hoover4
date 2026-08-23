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
import re
from typing import Any, NamedTuple

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
    barrier between user text and the query. Backslash first, then the quote, reversing
    the order would double-escape the backslashes introduced by the quote pass.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


#: The only full-text field in a shard pages table. Everything else in the schema
#: (`collection_dataset`, `file_hash`, `extracted_by`, `page_id`, `ner_*`) is an
#: attribute, so it belongs in WHERE, not in MATCH(). A `@field` naming anything else is
#: a hard 500 from Manticore: `no field 'title' found in schema`.
FULLTEXT_FIELDS = frozenset({"page_text"})

#: Manticore's boolean/proximity keywords. They are not search terms, so they do not
#: count when deciding whether a query has anything positive to match on.
_MATCH_KEYWORDS = frozenset(
    {"AND", "OR", "NOT", "MAYBE", "NEAR", "SENTENCE", "PARAGRAPH", "ZONE", "ZONESPAN"}
)

#: `@field`, `@!field`, `@(a,b)` or `@*`, the field-prefix operator in all its spellings.
_FIELD_OPERATOR_RE = re.compile(r"@(!?)(\*|\(([^)]*)\)|\w+)")


class MatchQueryError(ValueError):
    """A `MATCH()` expression that cannot be repaired into something searchable."""


class PreparedMatch(NamedTuple):
    """The result of turning free text into a `MATCH()` expression.

    `expr` is escaped and ready to interpolate into a single-quoted Manticore string
    literal, and is `""` when the query was unusable. `error` explains why in words the
    model can act on, and `repairs` lists what was silently fixed so the tool can tell it
    what its query became.
    """

    expr: str
    error: str | None = None
    repairs: tuple[str, ...] = ()


def _rewrite_field_operators(query: str) -> tuple[str, list[str]]:
    """Turn `@field` into a plain word unless `field` really is a full-text field.

    `who paid @acme` is prose, not syntax: Manticore reads `@acme` as a field prefix and
    fails the whole query with `no field 'acme' found in schema` rather than searching
    for the word. Since `page_text` is the only field there is, anything else was a false
    positive and the useful reading is the literal word.
    """
    repairs: list[str] = []

    def replace(m: re.Match) -> str:
        negated, body, group = m.group(1), m.group(2), m.group(3)
        if body == "*" and not negated:
            return m.group(0)  # `@*` = all fields, always valid
        names = [n.strip() for n in (group.split(",") if group is not None else [body]) if n.strip()]
        if not negated and names and all(n in FULLTEXT_FIELDS for n in names):
            return m.group(0)
        repairs.append(
            f"{m.group(0)!r} is not a searchable field, so it was read as plain text "
            f"(the only field is {', '.join(sorted(FULLTEXT_FIELDS))})"
        )
        return " ".join(names)

    return _FIELD_OPERATOR_RE.sub(replace, query), repairs


def _balance_quotes(query: str) -> tuple[str, list[str]]:
    """Drop a dangling `"`. An unbalanced quote is `syntax error, unexpected $end`."""
    if query.count('"') % 2 == 0:
        return query, []
    cut = query.rfind('"')
    return (
        query[:cut] + query[cut + 1:],
        ['dropped an unbalanced " — a phrase search needs both quotes'],
    )


def _balance_parens(query: str) -> tuple[str, list[str]]:
    """Close or drop unbalanced `(`. Same `unexpected $end` failure as a stray quote.

    A missing `)` is closed rather than dropped, because `(test | document` is a complete
    thought with a typo in it and `(test | document)` is what was meant. A surplus `)`
    has no such reading and is removed.
    """
    out: list[str] = []
    depth = 0
    dropped = 0
    for char in query:
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                dropped += 1
                continue
            depth -= 1
        out.append(char)

    repairs = []
    if dropped:
        repairs.append(f"dropped {dropped} unmatched ')'")
    if depth:
        repairs.append(f"added {depth} missing ')' to close the grouping")
    return "".join(out) + ")" * depth, repairs


def _has_positive_term(query: str) -> bool:
    """Whether anything in the query can *match*, as opposed to only exclude.

    Manticore rejects a query built only from negations: `-zzz` alone is
    `query is non-computable (single NOT operator)`, a 500 rather than an empty result.
    A quoted phrase counts as positive, and so does any word not introduced by `-`/`!`.
    """
    in_phrase = False
    for token in re.findall(r'"|\S+', query):
        if token == '"':
            in_phrase = not in_phrase
            continue
        if in_phrase:
            if any(c.isalnum() for c in token):
                return True
            continue
        if token.startswith(("-", "!")):
            continue
        word = token.strip('()|/~^=*')
        # `NEAR/3` and `ZONE/2` carry their distance in the token, so compare on the
        # part before the slash, otherwise the operator itself reads as a search word
        # and `NEAR/3 -zzz` looks computable when Manticore says it is not.
        if word.split("/", 1)[0].upper() in _MATCH_KEYWORDS or word.startswith("@"):
            continue
        if any(c.isalnum() for c in word):
            return True
    return False


def prepare_match_query(query: str) -> PreparedMatch:
    """Turn caller text into a `MATCH()` expression, repairing what can be repaired.

    Operators are **passed through** rather than stripped: `"exact phrase"`, `-exclude`,
    `term*`, `a | b`, `^start`, `=exact`, `NEAR/3` and `^3` boosts are what the agent uses in
    Manticore's extended syntax and the agent is told how to use them (see
    :mod:`.prompts`). What this does instead is head off the three shapes that come back
    as an HTTP 500 the model cannot interpret:

    * an unbalanced `"` or `(`: `syntax error, unexpected $end`
    * a query with no positive term, `non-computable (single NOT operator)`
    * an empty query, `MATCH('')` is not an error at all, which is worse: it matches
      **every row** in the shard

    Escaping is unchanged and stays last: `\\` and `'` are what could break out of the
    SQL string literal, and that is a separate concern from the query language living
    inside it.
    """
    if not query or not query.strip():
        return PreparedMatch("", error="query is empty")

    cleaned, repairs = _rewrite_field_operators(query)
    cleaned, quote_repairs = _balance_quotes(cleaned)
    cleaned, paren_repairs = _balance_parens(cleaned)
    repairs = repairs + quote_repairs + paren_repairs

    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return PreparedMatch("", error="query has no searchable terms")

    if not _has_positive_term(cleaned):
        return PreparedMatch(
            "",
            error=(
                "query only excludes terms; Manticore cannot run a search made of "
                "negations alone. Add at least one word to search for, e.g. "
                "'contract -draft' rather than '-draft'."
            ),
            repairs=tuple(repairs),
        )

    return PreparedMatch(escape_manticore_string(cleaned), repairs=tuple(repairs))


def sanitize_match_query(query: str) -> str:
    """The escaped `MATCH()` expression for `query`, or `""` if it is unusable.

    Thin wrapper over :func:`prepare_match_query` for callers that only need the string.
    """
    return prepare_match_query(query).expr
