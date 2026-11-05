"""Generate reader fixtures from the unchanged Python index producer."""
import ast
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[3]
namespace = {"re": re}
for relative, names in [
    ("main_services/processing/tasks/plan_utils.py", {"clean_text"}),
    ("main_services/processing/database/manticore.py", {"limit_encoded_runs", "ENCODED_LINE_MIN", "ENCODED_RUN_KEEP", "ENCODED_INLINE_MIN", "_ENCODED_LINE", "_ENCODED_RUN"}),
]:
    path = root / relative
    tree = ast.parse(path.read_text())
    selected = [node for node in tree.body if
                isinstance(node, ast.FunctionDef) and node.name in names or
                isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)

sources = [
    "  quokka café quokka\r\n quokka\tquokka  ",
    "\u001c\u0085quokka\u00a0\u2028quokka\u2029quokka\vquokka\u001f",
    "quokka " + "A" * 205 + " quokka\r\nquokka quokka",
    "quokka\r\n  " + "A" * 60 + "\r\n\t" + "B" * 80 + "\nquokka quokka quokka",
    "A" * 300,
    " \r\n\t ",
    "quokka\n" + "A" * 80 + "\u2028quokka",
]
fixtures = [{"source": source, "indexed": namespace["limit_encoded_runs"](namespace["clean_text"](source))} for source in sources]
Path(__file__).with_name("text_projection.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=2) + "\n")
