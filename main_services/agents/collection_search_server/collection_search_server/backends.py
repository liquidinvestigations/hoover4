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


def _boolean_word_tokens(query: str) -> list[tuple[int, int]]:
    """Split a query into tokens for :func:`_rewrite_boolean_words`, as `(start, end)`.

    Whitespace separates tokens, `(` and `)` outside quotes are tokens of their own, and
    a quoted run, closed or not, stays inside the token that holds it.
    """
    tokens: list[tuple[int, int]] = []
    start: int | None = None
    in_phrase = False
    for i, char in enumerate(query):
        if char == '"':
            in_phrase = not in_phrase
            if start is None:
                start = i
            continue
        if in_phrase:
            continue
        if char.isspace() or char in "()":
            if start is not None:
                tokens.append((start, i))
                start = None
            if char in "()":
                tokens.append((i, i + 1))
            continue
        if start is None:
            start = i
    if start is not None:
        tokens.append((start, len(query)))
    return tokens


def _is_boolean_term(word: str) -> bool:
    return word not in {"OR", "AND", "NOT", "|", "(", ")"}


def _rewrite_boolean_words(query: str) -> tuple[str, list[str]]:
    """Read the words `OR`, `AND` and `NOT` as the operators they are in a Boolean search.

    Manticore reads these words as ordinary search terms, so `a OR b` finds only a text
    that holds all three words. The rule: `OR` between two terms becomes `|`, a bare
    `AND` is dropped because every word must occur anyway, and `NOT x` becomes `-x`. An
    `OR` or `NOT` with no term on the needed side is dropped. Only the upper-case words
    are operators, and nothing inside double quotes changes. Each operator token is
    replaced in place and the rest of the text is kept as it is, so `"a b"~3` and an
    unbalanced quote reach the later passes unchanged.

    The Rust copy is `rewrite_boolean_words` in
    `website/backend/src/db_utils/manticore_match.rs`. The two copies are one rule and
    change in one patch.
    """
    tokens = _boolean_word_tokens(query)
    words = [query[start:end] for start, end in tokens]
    or_read = and_dropped = not_read = stray = 0
    out: list[str] = []
    # The last token written to the output, for the left side of an `OR`.
    last_written: str | None = None
    join_next = False
    cursor = 0
    for i, ((start, end), word) in enumerate(zip(tokens, words)):
        if not join_next:
            out.append(query[cursor:start])
        join_next = False
        cursor = end
        after = words[i + 1] if i + 1 < len(words) else None
        written: str | None
        if word == "AND":
            and_dropped += 1
            written = None
        elif word == "OR":
            before_ok = last_written is not None and (_is_boolean_term(last_written) or last_written == ")")
            after_ok = after is not None and (_is_boolean_term(after) or after == "(")
            if before_ok and after_ok:
                or_read += 1
                written = "|"
            else:
                stray += 1
                written = None
        elif word == "NOT":
            if after is not None and (_is_boolean_term(after) or after == "("):
                not_read += 1
                join_next = True
                written = "-"
            else:
                stray += 1
                written = None
        else:
            written = word
        if written is not None:
            out.append(written)
            if written != "-":
                last_written = written
    out.append(query[cursor:])

    repairs = []
    if or_read:
        repairs.append(f"read {or_read} OR as |, because OR is an ordinary word in a search")
    if and_dropped:
        repairs.append(f"dropped {and_dropped} AND, because every word of a query must occur anyway")
    if not_read:
        repairs.append(f"read {not_read} NOT x as -x, because NOT is an ordinary word in a search")
    if stray:
        repairs.append(f"dropped {stray} OR or NOT with no word on one side")
    return "".join(out), repairs


def _rewrite_field_operators(query: str) -> tuple[str, list[str]]:
    """Turn `@field` into a plain word unless `field` really is a full-text field.

    `who paid @acme` is prose, not syntax: Manticore reads `@acme` as a field prefix and
    fails the whole query with `no field 'acme' found in schema` rather than searching
    for the word. Since `page_text` is the only field there is, anything else was a false
    positive and the useful reading is the literal word.

    An `@` with a word character right before it is part of a word, as in the address
    `name@host`. It becomes `\\@`, the escape the website search uses for every `@`, so
    Manticore reads it as a character of the word and the address stays one term.
    """
    repairs: list[str] = []

    def replace(m: re.Match) -> str:
        start = m.start()
        if start > 0 and (query[start - 1].isalnum() or query[start - 1] == "_"):
            return "\\" + m.group(0)
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
        ['dropped an unbalanced ": a phrase search needs both quotes'],
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

    The words `OR`, `AND` and `NOT` are read first, by :func:`_rewrite_boolean_words`,
    and each rewrite is one line of `repairs`.

    Escaping is unchanged and stays last: `\\` and `'` are what could break out of the
    SQL string literal, and that is a separate concern from the query language living
    inside it.
    """
    if not query or not query.strip():
        return PreparedMatch("", error="query is empty")

    cleaned, repairs = _rewrite_boolean_words(query)
    cleaned, field_repairs = _rewrite_field_operators(cleaned)
    cleaned, quote_repairs = _balance_quotes(cleaned)
    cleaned, paren_repairs = _balance_parens(cleaned)
    repairs = repairs + field_repairs + quote_repairs + paren_repairs

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
