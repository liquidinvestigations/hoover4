#!/usr/bin/env python3
"""Compare the operation kind and input registries in Python and Rust.

Also compare the `[operations]` cap keys of `DEFAULTS` in `deploy.py` with `KINDS`:
each kind has one key named `<kind>_cap`, in `KINDS` order.
"""

import ast
import re
import sys
from pathlib import Path


ROOT = Path.cwd()
PYTHON_OPERATIONS = ROOT / "main_services/processing/database/operations.py"
PYTHON_INPUTS = ROOT / "main_services/processing/database/operation_inputs.py"
RUST_OPERATIONS = ROOT / "website/backend/src/api/admin/operations.rs"
DEPLOY = ROOT / "deploy.py"


class ParseError(Exception):
    """A registry source does not have the expected literal table."""


def python_assignment(path: Path, name: str):
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError) as error:
        raise ParseError(f"cannot parse {path}: {error}") from error
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        if isinstance(target, ast.Name) and target.id == name and value is not None:
            try:
                return ast.literal_eval(value)
            except ValueError as error:
                raise ParseError(f"cannot parse {name} in {path}") from error
    raise ParseError(f"cannot parse {name} in {path}")


def deploy_cap_keys(path: Path) -> list[str]:
    """The keys of `DEFAULTS["operations"]` in `deploy.py`, in source order."""
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError) as error:
        raise ParseError(f"cannot parse {path}: {error}") from error
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "DEFAULTS" and isinstance(node.value, ast.Dict)):
            for key, value in zip(node.value.keys, node.value.values):
                if isinstance(key, ast.Constant) and key.value == "operations":
                    try:
                        return list(ast.literal_eval(value))
                    except ValueError as error:
                        raise ParseError(f"cannot parse DEFAULTS['operations'] in {path}") from error
    raise ParseError(f"cannot parse DEFAULTS['operations'] in {path}")


def rust_array(source: str, name: str) -> str:
    match = re.search(rf"const {name}:.*?=\s*&\[(.*?)\];", source, re.DOTALL)
    if match is None or not match.group(1).strip():
        raise ParseError(f"cannot parse {name} in {RUST_OPERATIONS}")
    return match.group(1)


def parse_rust(source: str):
    kinds = {
        name: (target, destructive == "true")
        for name, target, destructive in re.findall(
            r'\("([^"]+)",\s*"([^"]+)",\s*(true|false)\),',
            rust_array(source, "KINDS"),
        )
    }
    driven = set(re.findall(r'"([^"]+)"\s*,', rust_array(source, "DRIVEN_KINDS")))
    inputs = {
        name: tuple(re.findall(r'"([^"]+)"', values))
        for name, values in re.findall(
            r'\("([^"]+)",\s*&\[(.*?)\]\),',
            rust_array(source, "INPUT_KEYS"),
            re.DOTALL,
        )
    }
    if not kinds or not driven or not inputs:
        raise ParseError(f"cannot parse a registry in {RUST_OPERATIONS}")
    return kinds, driven, inputs


def main() -> int:
    try:
        python_kinds = python_assignment(PYTHON_OPERATIONS, "KINDS")
        python_driven = set(python_assignment(PYTHON_OPERATIONS, "DRIVEN_KINDS"))
        python_inputs = python_assignment(PYTHON_INPUTS, "INPUT_KEYS")
        rust_kinds, rust_driven, rust_inputs = parse_rust(RUST_OPERATIONS.read_text())
        cap_keys = deploy_cap_keys(DEPLOY)
    except (OSError, ParseError) as error:
        print(error)
        return 2

    differences: list[str] = []
    for name in sorted(set(python_kinds) | set(rust_kinds)):
        if name not in rust_kinds:
            differences.append(f"kinds: {name} only in python")
        elif name not in python_kinds:
            differences.append(f"kinds: {name} only in rust")
        elif python_kinds[name] != {
            "target_kind": rust_kinds[name][0], "destructive": rust_kinds[name][1]
        }:
            differences.append(f"kinds: {name} differs")
    for name in sorted(python_driven | rust_driven):
        if name not in rust_driven:
            differences.append(f"driven: {name} only in python")
        elif name not in python_driven:
            differences.append(f"driven: {name} only in rust")
    for kind in sorted(set(python_inputs) | set(rust_inputs)):
        python_keys = set(python_inputs.get(kind, ()))
        rust_keys = set(rust_inputs.get(kind, ()))
        for key in sorted(python_keys - rust_keys):
            differences.append(f"inputs: {kind} {key} only in python")
        for key in sorted(rust_keys - python_keys):
            differences.append(f"inputs: {kind} {key} only in rust")
    expected_caps = [f"{name}_cap" for name in python_kinds]
    for key in expected_caps:
        if key not in cap_keys:
            differences.append(f"caps: {key} missing from deploy.py DEFAULTS['operations']")
    for key in cap_keys:
        if key not in expected_caps:
            differences.append(f"caps: {key} in deploy.py is not a kind of KINDS")
    if not differences and cap_keys != expected_caps:
        differences.append("caps: deploy.py DEFAULTS['operations'] is not in KINDS order")
    print("\n".join(differences))
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
