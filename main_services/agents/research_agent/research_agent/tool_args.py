"""Decode tool arguments that the model sends as JSON strings.

The served model often writes a non-string argument as a string. It sends
`"collectionname": "[\\"testdata\\"]"` or `"collectionname": "testdata"` for a parameter
that takes a list of strings, and `"filename_only": "True"` for a boolean. The MCP server
validates the arguments with pydantic in lax mode, which refuses a string for a list or an
object, so the tool call fails and the model gets a validation error in place of a result.

The served model writes the token `<|"|>` around a string. The tool call parser of the
model server does not always remove it. A value or a key can then hold the token, a key
can keep a quote (`id"`), and a value can keep one layer of quotes. `repair_arguments`
removes the token and that one layer. It returns one line for each repair, and
`/tool_call` puts the lines in the measure of the call.

`decode_string_arguments` converts such a string to the value the schema asks for, before
the arguments leave the agent. It changes a value only when the parameter's schema does not
allow a string and the decoded value has an allowed type. For a list of strings, a string
that does not decode to an allowed type becomes a one-item list. Every other value stays as
it was, so the server's own validation error still reaches the model.
"""

import json
from json import JSONDecodeError
from typing import Any, Dict, List, Optional, Set, Tuple

#: A marker in an allowed-type set. It means that one branch of the schema accepts any
#: value, so a string is already valid and nothing is decoded.
ANY_TYPE = "any"

_BOOLEAN_WORDS = {"true": True, "false": False}


def _resolve_ref(schema: dict, root: dict) -> dict:
    """Return the local definition that a `$ref` points to, or the schema itself."""
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return schema
    node: Any = root
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            return schema
        node = node[part]
    return node if isinstance(node, dict) else schema


def _branches(schema: Any, root: dict, depth: int = 0) -> list:
    """Return the leaf schemas of `schema`, following `$ref`, `anyOf` and `oneOf`."""
    if not isinstance(schema, dict) or depth > 8:
        return [{}]
    schema = _resolve_ref(schema, root)
    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list) and options:
            leaves = []
            for option in options:
                leaves.extend(_branches(option, root, depth + 1))
            return leaves
    return [schema]


def _types_of(leaf: dict) -> Set[str]:
    """Return the JSON types that one leaf schema allows."""
    declared = leaf.get("type")
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return {t for t in declared if isinstance(t, str)}
    if "enum" in leaf or "const" in leaf:
        values = leaf.get("enum", [leaf.get("const")])
        return {_json_type(v) for v in values}
    if "properties" in leaf or "additionalProperties" in leaf:
        return {"object"}
    if "items" in leaf:
        return {"array"}
    return {ANY_TYPE}


def _json_type(value: Any) -> str:
    """Return the JSON type name of a decoded value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _is_allowed(value: Any, types: Set[str]) -> bool:
    """Tell whether a decoded value has one of the allowed types. `null` never counts."""
    kind = _json_type(value)
    if kind == "null":
        return False
    if kind in types:
        return True
    return kind == "integer" and "number" in types


def _array_allows_strings(leaves: list, root: dict) -> bool:
    """Tell whether one of the array leaves takes string items."""
    for leaf in leaves:
        if "array" not in _types_of(leaf):
            continue
        items = leaf.get("items", {})
        for item in _branches(items, root):
            item_types = _types_of(item)
            if "string" in item_types or ANY_TYPE in item_types:
                return True
    return False


def _decode_one(value: str, schema: Any, root: dict) -> Any:
    """Return the decoded value for one string argument, or the string unchanged."""
    leaves = _branches(schema, root)
    types: Set[str] = set()
    for leaf in leaves:
        types |= _types_of(leaf)
    types.discard("null")
    if not types or "string" in types or ANY_TYPE in types:
        return value

    if "boolean" in types:
        word = _BOOLEAN_WORDS.get(value.strip().lower())
        if word is not None:
            return word

    try:
        decoded = json.loads(value)
    except (JSONDecodeError, TypeError, ValueError):
        if _array_allows_strings(leaves, root):
            return [value]
        return value
    if _is_allowed(decoded, types):
        return decoded
    if _array_allows_strings(leaves, root):
        return [value]
    return value


def decode_string_arguments(args: Dict[str, Any], schema: Optional[dict]) -> Dict[str, Any]:
    """Return `args` with each JSON-string value decoded to the type its schema allows.

    `schema` is the tool's JSON input schema. A parameter that the schema does not name and
    a value that is not a string stay unchanged. A string that does not decode to an allowed
    type becomes a one-item list when the parameter takes a list of strings, and otherwise
    stays unchanged.
    """
    if not isinstance(args, dict) or not isinstance(schema, dict):
        return args
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return args
    decoded = dict(args)
    for name, value in args.items():
        if isinstance(value, str) and name in properties:
            decoded[name] = _decode_one(value, properties[name], schema)
    return decoded


#: The string token of the served model, which the tool call parser can leave in a value
#: or a key.
QUOTE_TOKEN = '<|"|>'

#: The keys whose string values keep their quotes: a quoted phrase in a search query and a
#: quote copied from a document are part of the value.
QUOTED_TEXT_KEYS = frozenset({"query", "queries", "quote", "find"})


def _unquoted(text: str) -> str:
    """`text` with one layer of double quotes removed, when the quotes wrap a word that
    holds no other quote and no space. Any other text comes back unchanged."""
    if len(text) < 3 or text[0] != '"' or text[-1] != '"':
        return text
    inner = text[1:-1]
    if '"' in inner or any(c.isspace() for c in inner):
        return text
    return inner


def _repair_key(key: str, where: str, repairs: List[str]) -> str:
    fixed = key.replace(QUOTE_TOKEN, "")
    stripped = fixed.strip('"')
    if stripped and '"' not in stripped:
        fixed = stripped
    if fixed != key:
        repairs.append(f"key {where}{key!r} became {fixed!r}")
    return fixed


def _repair_value(value: Any, key: str, where: str, repairs: List[str]) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for raw_key, item in value.items():
            name = _repair_key(raw_key, where, repairs) if isinstance(raw_key, str) else raw_key
            if name in out:
                repairs.append(f"key {where}{raw_key!r} was dropped, because {name!r} is set")
                continue
            out[name] = _repair_value(item, name, f"{where}{name}.", repairs)
        return out
    if isinstance(value, list):
        return [_repair_value(item, key, f"{where[:-1]}[{i}].", repairs)
                for i, item in enumerate(value)]
    if not isinstance(value, str):
        return value
    fixed = value.replace(QUOTE_TOKEN, "")
    if fixed != value:
        repairs.append(f"value {where[:-1]} lost the quote token")
    if key not in QUOTED_TEXT_KEYS:
        inner = _unquoted(fixed)
        if inner != fixed:
            repairs.append(f"value {where[:-1]} lost one layer of quotes")
            fixed = inner
    return fixed


def repair_arguments(args: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Return `args` with the served model's quote token removed from every key and string
    value, the quotes stripped from each key, and one layer of quotes removed from each
    string value that is one quoted word. The values under `QUOTED_TEXT_KEYS` keep their
    quotes. The second item names each repair, and is empty when nothing changed."""
    if not isinstance(args, dict):
        return args, []
    repairs: List[str] = []
    fixed = _repair_value(args, "", "", repairs)
    return fixed, repairs
