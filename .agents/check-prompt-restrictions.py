#!/usr/bin/env python3
"""Print model instructions that need a person to review their restrictions."""

from pathlib import Path
import ast
import re


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "main_services/agents"
SOURCES = (
    AGENTS / "research_agent/research_agent/prompts",
    AGENTS / "research_agent/research_agent/skills",
    AGENTS / "collection_search_server/collection_search_server/prompts",
)
ROLE_LINES = AGENTS / "research_agent/research_agent/prompts/__init__.py"
DESCRIPTION_ROOTS = (
    AGENTS / "research_agent/research_agent",
    AGENTS / "collection_search_server/collection_search_server",
    AGENTS / "agent_todo_server/agent_todo_server",
    AGENTS / "browser_use_server/browser_use_server",
)
RESTRICTION = re.compile(
    r"\b(?:only|never|do not|must|cannot|refuse\w*|always|exactly|at least|at most)\b"
    r"|\b(?:first|then|before|after|last)\b.+\b(?:call|search|read|answer|report)\b"
    r"|\b(?:answer|report|reply|output)\b.+\b(?:format|shape|section|paragraph|sentence)\b",
    re.IGNORECASE,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`{])")


def source_files():
    """Yield the templates, skills, role lines and tool description source files."""
    found = set()
    for directory in SOURCES:
        found.update(directory.rglob("*.j2"))
    for directory in DESCRIPTION_ROOTS:
        for path in directory.rglob("*.py"):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            if "description=" in text or "DESCRIPTIONS =" in text or "@mcp.tool" in text:
                found.add(path)
    return sorted(found)


def python_text(path: Path):
    """Yield role lines, tool descriptions and tool docstrings from Python source."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any("tool" in ast.unparse(decorator).lower() for decorator in node.decorator_list):
                doc = ast.get_docstring(node)
                if doc:
                    yield node.lineno + 1, doc
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "Field":
                continue
            for keyword in node.keywords:
                if keyword.arg == "description" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        yield keyword.value.lineno, keyword.value.value
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(target, ast.Name) and target.id in
                       {"ROLE_LINES", "DESCRIPTIONS"} for target in targets):
                continue
            value = node.value
            if isinstance(value, ast.Dict):
                for item in value.values:
                    for child in ast.walk(item):
                        if isinstance(child, ast.Constant) and isinstance(child.value, str):
                            yield child.lineno, child.value


def template_text(path: Path):
    """Yield lines that can reach a rendered prompt or skill description."""
    source = path.read_text(encoding="utf-8")
    source = re.sub(r"\{#.*?#\}",
                    lambda match: "\n" * match.group().count("\n"),
                    source, flags=re.DOTALL)
    return enumerate(source.splitlines(), 1)


def main() -> None:
    count = 0
    for path in sorted(set(source_files()) | {ROLE_LINES}):
        rows = python_text(path) if path.suffix == ".py" else template_text(path)
        for line_no, line in rows:
            for sentence in SENTENCE.split(re.sub(r"\s+", " ", line.strip())):
                if RESTRICTION.search(sentence):
                    print(f"{path.relative_to(ROOT)}:{line_no}: {sentence}")
                    count += 1
    print(f"Flagged sentences: {count}")


if __name__ == "__main__":
    main()
