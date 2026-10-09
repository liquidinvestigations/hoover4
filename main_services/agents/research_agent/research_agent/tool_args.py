"""Normalize the tool arguments that the served model sends, before a call is classified
and before it is validated.

`normalize_arguments` runs three steps, and it returns the arguments, one line for each
change, and a problem when the arguments cannot be used as they are. It gives the same
result when it runs again on its own output, so `/model_step` and `/tool_call` can both run
it.

1. `repair_arguments`. The served model writes the token `<|"|>` around a string. The tool
   call parser of the model server does not always remove it, so a value or a key can hold
   the token, a key can keep a quote (`id"`), and a value can keep one layer of quotes. The
   repair removes the string delimiter tokens and retains literal phrase quotes.
   It separates merged query values at paired delimiter tokens.
   It refuses conflicting duplicate keys and damaged argument names.
   Raw JSON repair adds missing key quotes outside string contents.
2. `rename_aliases` retains repairs for unchanged file-hash arguments.
   Changed collection argument names have no compatibility aliases.
3. `decode_string_arguments`. The model often writes a non-string argument as a string: it
   sends `"collection": "[\\"testdata\\"]"` or `"collection": "testdata"` for a
   list of strings, and `"filename_only": "True"` for a boolean. The MCP servers validate the
   arguments with pydantic in lax mode, which refuses a string for a list or an object. A
   value changes only when the parameter's schema does not allow it as it is. A string
   becomes the JSON value it holds when that value has an allowed type. A single value
   becomes a one-item list when the parameter takes a list and the value is a valid item.
   A list never becomes a single value, and one call never becomes several calls.

`model_schema` is a separate concern: the schema of a tool as the model is shown it. See its
docstring.
"""

import json
import re
from json import JSONDecodeError
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

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


def _array_item_accepts(leaves: list, root: dict, value: Any) -> bool:
    """Tell whether one of the array leaves takes `value` as one item. `null` and an empty
    string are never an item."""
    kind = _json_type(value)
    if kind in ("null", "unknown") or (kind == "string" and not value):
        return False
    for leaf in leaves:
        if "array" not in _types_of(leaf):
            continue
        for item in _branches(leaf.get("items", {}), root):
            item_types = _types_of(item)
            if ANY_TYPE in item_types or _is_allowed(value, item_types):
                return True
    return False


def _decode_one(value: Any, schema: Any, root: dict) -> Any:
    """Return the value that one argument gets, or the value unchanged."""
    leaves = _branches(schema, root)
    types: Set[str] = set()
    for leaf in leaves:
        types |= _types_of(leaf)
    types.discard("null")
    if not types or ANY_TYPE in types:
        return value
    if not isinstance(value, str):
        if _is_allowed(value, types) or value is None:
            return value
        return [value] if _array_item_accepts(leaves, root, value) else value
    if "string" in types:
        return value

    if "boolean" in types:
        word = _BOOLEAN_WORDS.get(value.strip().lower())
        if word is not None:
            return word

    try:
        decoded = json.loads(value)
    except (JSONDecodeError, TypeError, ValueError):
        decoded = None
    else:
        if _is_allowed(decoded, types):
            return decoded
        if _array_item_accepts(leaves, root, decoded):
            return [decoded]
    if _array_item_accepts(leaves, root, value):
        return [value]
    return value


def decode_string_arguments(args: Dict[str, Any], schema: Optional[dict]) -> Dict[str, Any]:
    """Return `args` with each top-level value converted to the type its schema allows.

    `schema` is the tool's JSON input schema. A parameter that the schema does not name
    stays unchanged. A string becomes the JSON value that it holds, when that value has an
    allowed type. A single value becomes a one-item list, when the parameter takes a list
    and the value, or the JSON value of the string, is a valid item. Every other value
    stays unchanged, so the validation error names it.
    """
    if not isinstance(args, dict) or not isinstance(schema, dict):
        return args
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return args
    decoded = dict(args)
    for name, value in args.items():
        if name in properties:
            decoded[name] = _decode_one(value, properties[name], schema)
    return decoded


#: The string token of the served model, which the tool call parser can leave in a value
#: or a key.
QUOTE_TOKEN = '<|"|>'

#: The keys whose string values keep their quotes: a quoted phrase in a search query and a
#: quote copied from a document are part of the value.
QUOTED_TEXT_KEYS = frozenset({"query", "queries", "quote", "find"})

#: Characters that no argument name holds. A repaired key that holds one of them is text
#: that the parser put in the place of a key.
_NOT_IN_A_KEY = frozenset(" \t\n,:{}[]")


class DamagedArguments(ValueError):
    """The arguments cannot be used as they are. The message says why, for the model."""


def _strip_token(text: str) -> Tuple[str, bool]:
    """`text` without the quote token at its start and at its end, and whether a token is
    left inside it."""
    fixed = text
    while fixed.startswith(QUOTE_TOKEN):
        fixed = fixed[len(QUOTE_TOKEN):]
    while fixed.endswith(QUOTE_TOKEN):
        fixed = fixed[:-len(QUOTE_TOKEN)]
    return fixed, QUOTE_TOKEN in fixed


def _unquoted(text: str) -> str:
    """`text` with one layer of double quotes removed, when the quotes wrap a word that
    holds no other quote and no space. Any other text comes back unchanged."""
    if len(text) < 3 or text[0] != '"' or text[-1] != '"':
        return text
    inner = text[1:-1]
    if '"' in inner or any(c.isspace() for c in inner):
        return text
    return inner


def _damaged(where: str, what: str) -> DamagedArguments:
    return DamagedArguments(
        f"The call was not run, because its arguments arrived damaged: {what} at "
        f"{where or 'the top level'}. The tool call parser split the call in the wrong "
        "place, so no value of it is certain. Send the call again, with each argument as "
        "plain JSON.")


def _repair_key(key: str, where: str, repairs: List[str]) -> str:
    fixed, inside = _strip_token(key)
    if inside:
        raise _damaged(where[:-1], f"the key {key!r} holds a string delimiter")
    stripped = fixed.strip('"')
    if stripped and '"' not in stripped:
        fixed = stripped
    if fixed.startswith("{ "):
        fixed = fixed[2:]
    elif fixed.startswith("{"):
        fixed = fixed[1:]
    elif fixed.startswith("],"):
        fixed = fixed[2:]
    if not fixed or any(c in _NOT_IN_A_KEY for c in fixed):
        raise _damaged(where[:-1], f"the key {key!r} is not an argument name")
    if fixed != key:
        repairs.append(f"key {where}{key!r} became {fixed!r}")
    return fixed


def repair_json_arguments(text: str) -> Tuple[dict, List[str]]:
    """Repair unquoted JSON keys without changing quoted string contents."""
    decoder = json.JSONDecoder()
    parts, repairs = [], []
    index, previous = 0, ""
    while index < len(text):
        character = text[index]
        if character == '"':
            try:
                _value, end = decoder.raw_decode(text, index)
            except JSONDecodeError as exc:
                raise DamagedArguments(f"The arguments contain invalid JSON at position {exc.pos}.") from exc
            parts.append(text[index:end])
            index, previous = end, '"'
            continue
        if previous in ("{", ","):
            key = re.match(r'([A-Za-z_][A-Za-z_0-9]*)"?\s*:', text[index:])
            if key:
                parts.append(json.dumps(key.group(1)) + ":")
                repairs.append(f"The key at position {index} received its opening quote.")
                index += key.end()
                previous = ":"
                continue
        parts.append(character)
        if not character.isspace():
            previous = character
        index += 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result and result[key] != value:
                raise DamagedArguments(f"The argument {key!r} has conflicting values.")
            result[key] = value
        return result

    try:
        value = json.loads("".join(parts), object_pairs_hook=pairs)
    except JSONDecodeError as exc:
        raise DamagedArguments(f"The arguments contain invalid JSON at position {exc.pos}.") from exc
    if not isinstance(value, dict):
        raise DamagedArguments("The arguments of a tool call must be a JSON object.")
    return value, repairs


def _repair_value(value: Any, key: str, where: str, repairs: List[str]) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        sources: Dict[str, str] = {}
        for raw_key, item in value.items():
            name = _repair_key(raw_key, where, repairs) if isinstance(raw_key, str) else raw_key
            fixed = _repair_value(item, name, f"{where}{name}.", repairs)
            if name in out:
                if out[name] != fixed:
                    raise DamagedArguments(
                        f"The call was not run, because the keys {sources[name]!r} and "
                        f"{raw_key!r} both name the argument {where}{name} with different "
                        "values. Send the call again with one value for it.")
                repairs.append(f"key {where}{raw_key!r} repeated {name!r} with the same value")
                continue
            out[name] = fixed
            sources[name] = raw_key
        return out
    if isinstance(value, list):
        repaired = []
        for index, item in enumerate(value):
            items = item.split(QUOTE_TOKEN * 2) if key == "queries" and isinstance(item, str) else [item]
            if len(items) > 1:
                repairs.append(f"The query at {where[:-1]}[{index}] contained merged values.")
            for part in items:
                repaired.append(_repair_value(part, key, f"{where[:-1]}[{index}].", repairs))
        return repaired
    if not isinstance(value, str):
        return value
    fixed, inside = _strip_token(value)
    if inside:
        if key not in QUOTED_TEXT_KEYS:
            raise _damaged(where[:-1], "the value holds a string delimiter")
        fixed = fixed.replace(QUOTE_TOKEN, "")
        repairs.append(f"The value at {where[:-1]} contained a string delimiter.")
    if key in QUOTED_TEXT_KEYS and fixed.endswith('"') and fixed.count('"') % 2:
        fixed = '"' + fixed
        repairs.append(f"The value at {where[:-1]} received its opening phrase quote.")
    if fixed != value:
        repairs.append(f"value {where[:-1]} lost the quote token")
    if key not in QUOTED_TEXT_KEYS:
        inner = _unquoted(fixed)
        if inner != fixed:
            repairs.append(f"value {where[:-1]} lost one layer of quotes")
            fixed = inner
    return fixed


def repair_arguments(args: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Return `args` with the served model's quote token removed from the start and the
    end of every key and string value, the quotes stripped from each key, and one layer of
    quotes removed from each string value that is one quoted word. The values under
    `QUOTED_TEXT_KEYS` keep their quotes. The second item names each repair, and is empty
    when nothing changed.

    Refuse interior delimiters outside query text, invalid keys, and conflicting duplicate values.
    """
    if not isinstance(args, dict):
        return args, []
    repairs: List[str] = []
    fixed = _repair_value(args, "", "", repairs)
    return fixed, repairs


#: Argument names that the served model writes in place of the name in the tool's schema.
KEY_ALIASES = {
    "file_hashes": "file_hash",
    "hash": "file_hash",
}


def rename_aliases(args: Dict[str, Any], schema: Optional[dict]) -> Tuple[Dict[str, Any], List[str]]:
    """Return `args` with each top-level key of `KEY_ALIASES` renamed to its schema name,
    when the schema has that name and not the alias. An alias with the same value as its
    name is removed. The second item names each change, and is empty when nothing changed.

    Raises `DamagedArguments` when the alias and its name hold different values.
    """
    properties = (schema or {}).get("properties") if isinstance(schema, dict) else None
    if not isinstance(args, dict) or not isinstance(properties, dict):
        return args, []
    out = dict(args)
    repairs: List[str] = []
    for alias, name in KEY_ALIASES.items():
        if alias not in out or alias in properties or name not in properties:
            continue
        if name in out:
            if out[name] != out[alias]:
                raise DamagedArguments(
                    f"The call was not run, because {alias!r} and {name!r} name the same "
                    "argument with different values. Send the call again with "
                    f"{name!r} only.")
            del out[alias]
            repairs.append(f"key {alias!r} repeated {name!r} with the same value")
            continue
        out[name] = out.pop(alias)
        repairs.append(f"key {alias!r} became {name!r}")
    return out, repairs


class Normalized(NamedTuple):
    """The arguments of one call after `normalize_arguments`."""

    #: The arguments to validate and send. The arguments as they came when `problem` is set.
    args: Dict[str, Any]
    #: One line for each change.
    repairs: List[str]
    #: Why the arguments cannot be used, for the model, or empty.
    problem: str = ""


def _embedded_collection_arguments(args: dict, schema: Optional[dict]) -> Tuple[dict, List[str]]:
    """Recover named arguments that the parser placed in the collection list."""
    properties = (schema or {}).get("properties", {})
    values = args.get("collection")
    if not isinstance(values, list):
        return args, []
    result, kept, repairs = dict(args), [], []
    for item in values:
        match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*):(.*)", item, re.DOTALL) if isinstance(item, str) else None
        if match is None or match[1] not in properties or match[1] == "collection":
            kept.append(item)
            continue
        key, raw = match[1], match[2].strip()
        if raw.startswith("[" + QUOTE_TOKEN) and raw.endswith(QUOTE_TOKEN):
            value = [raw[1 + len(QUOTE_TOKEN):-len(QUOTE_TOKEN)]]
        else:
            try:
                value = json.loads(raw)
            except JSONDecodeError:
                kept.append(item)
                continue
        if key in result and result[key] != value:
            raise DamagedArguments(f"The argument {key!r} has conflicting values.")
        result[key] = value
        repairs.append(f"The argument {key!r} moved out of the collection list.")
    result["collection"] = kept
    return result, repairs


def normalize_arguments(args: Any, schema: Optional[dict]) -> Normalized:
    """The arguments of one call, repaired, renamed and decoded for the tool's `schema`.

    A second run on the result changes nothing and names no repair. Damaged arguments come
    back unchanged, with `problem` set.
    """
    raw_repairs = []
    if isinstance(args, str):
        try:
            args, raw_repairs = repair_json_arguments(args)
        except DamagedArguments as exc:
            return Normalized({}, [], str(exc))
    if not isinstance(args, dict):
        return Normalized(args, [], "The arguments of a tool call must be a JSON object.")
    try:
        args, embedded_repairs = _embedded_collection_arguments(args, schema)
        fixed, repairs = repair_arguments(args)
        fixed, renames = rename_aliases(fixed, schema)
    except DamagedArguments as exc:
        return Normalized(dict(args), [], str(exc))
    return Normalized(decode_string_arguments(fixed, schema), raw_repairs + embedded_repairs + repairs + renames)


# ----------------------------------------------------------------- the schema shown to a model


#: The keys of a schema node that the model is not shown: the choices, which `model_schema`
#: resolves, and the definitions, which it copies into place.
_CHOICE_KEYS = ("anyOf", "oneOf")
_DEFINITION_KEYS = ("$defs", "definitions")


def _one_branch(branches: List[dict]) -> Optional[dict]:
    """The one branch that the model is shown for a choice, or None to keep the choice.

    A `null` branch is left out, because the parameter is optional. A string branch beside
    one list or object branch is left out, because the string form is only a tolerance of
    the server. Of several scalar branches, the string branch is kept.
    """
    kept = [b for b in branches if b.get("type") != "null"]
    if len(kept) == 1:
        return kept[0]
    structured = [b for b in kept if b.get("type") in ("array", "object")]
    strings = [b for b in kept if b.get("type") == "string"]
    if len(structured) == 1 and len(structured) + len(strings) == len(kept):
        return structured[0]
    if not structured and len(strings) == 1 and all(isinstance(b.get("type"), str) for b in kept):
        return strings[0]
    return None


def model_schema(schema: Any) -> Any:
    """The input schema of a tool as the model is shown it.

    The chat template of the served model renders each parameter from its `type`, and it
    renders a parameter with `anyOf` or `oneOf` as a parameter with an empty type, with no
    field names and no item type. The model then invents the names. This copy replaces each
    such choice with one branch (`_one_branch`), copies each local `$ref` into place, and
    keeps the description, the default and the other keys of the parameter. Arguments are
    still validated against the tool's own schema, so every form that the tool accepts
    stays valid.
    """
    if not isinstance(schema, dict):
        return schema
    root = schema

    def walk(node: Any, depth: int) -> Any:
        if not isinstance(node, dict) or depth > 12:
            return node
        if isinstance(node.get("$ref"), str):
            target = _resolve_ref(node, root)
            if target is not node:
                node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        out = {k: v for k, v in node.items()
               if k not in _CHOICE_KEYS and k not in _DEFINITION_KEYS}
        for key in _CHOICE_KEYS:
            options = node.get(key)
            if not isinstance(options, list) or not options:
                continue
            branches = [walk(o, depth + 1) for o in options]
            chosen = _one_branch([b for b in branches if isinstance(b, dict)])
            if chosen is None:
                out[key] = branches
            else:
                out = {**chosen, **{k: v for k, v in out.items() if k != "type"}}
        if isinstance(out.get("properties"), dict):
            out["properties"] = {k: walk(v, depth + 1) for k, v in out["properties"].items()}
        if isinstance(out.get("items"), dict):
            out["items"] = walk(out["items"], depth + 1)
        if isinstance(out.get("additionalProperties"), dict):
            out["additionalProperties"] = walk(out["additionalProperties"], depth + 1)
        return out

    return walk(schema, 0)
