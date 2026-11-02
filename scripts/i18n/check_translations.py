"""Check the translated texts of one or more languages against their English sources.

Usage, from the repository root, with Python 3 and Jinja2:

    python3 scripts/i18n/check_translations.py de [ru ...]
    python3 scripts/i18n/check_translations.py --all

The script reads only the text files. It checks:

* the website catalogs `website/frontend/i18n/<code>/*.ftl` and the worker notes
  `main_services/processing/tasks/P_agent/i18n/<code>/notes.ftl`: the same message ids as
  English, the same variables, a default variant in every selector, plural keys that the
  language has, and no selector in the notes;
* the research agent texts in `main_services/agents/research_agent/research_agent/`: the
  system prompt, the role lines, every skill and partial, and the tool texts. A template
  must parse and keep the Jinja statements and expressions of English in the same order.
  A skill keeps the `name`, `group` and `tools` of English. The tool texts have one
  translation for each English text;
* the term lists `scripts/i18n/glossary/<code>.json` and `agent-<code>.json` parse.

An error makes the exit status 1. A warning names a text to read again, for example a
message that is the same as English or a code span that English does not have.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from jinja2 import Environment, TemplateSyntaxError

ROOT = Path(__file__).resolve().parents[2]
WEBSITE = ROOT / "website/frontend/i18n"
NOTES = ROOT / "main_services/processing/tasks/P_agent/i18n"
AGENT = ROOT / "main_services/agents/research_agent/research_agent"
GLOSSARY = ROOT / "scripts/i18n/glossary"

LANGUAGES = ["de", "es", "fr", "pl", "pt", "ar", "he", "hi", "zh", "it", "nl", "da", "nb",
             "sv", "el", "hr", "ro", "ru", "ja", "ko", "tr"]

#: The CLDR cardinal plural categories of each language.
PLURALS = {
    "en": {"one", "other"}, "de": {"one", "other"}, "es": {"one", "many", "other"},
    "fr": {"one", "many", "other"}, "pl": {"one", "few", "many", "other"},
    "pt": {"one", "many", "other"}, "ar": {"zero", "one", "two", "few", "many", "other"},
    "he": {"one", "two", "other"}, "hi": {"one", "other"}, "zh": {"other"},
    "it": {"one", "many", "other"}, "nl": {"one", "other"}, "da": {"one", "other"},
    "nb": {"one", "other"}, "sv": {"one", "other"}, "el": {"one", "other"},
    "hr": {"one", "few", "other"}, "ro": {"one", "few", "other"},
    "ru": {"one", "few", "many", "other"}, "ja": {"other"}, "ko": {"other"},
    "tr": {"one", "other"},
}
ONE_FORM = {"zh", "ja", "ko"}

MESSAGE = re.compile(r"^([a-zA-Z][\w-]*)\s*=\s?(.*)$")
VARIABLE = re.compile(r"\$([a-zA-Z_][\w-]*)")
VARIANT = re.compile(r"^\s*\*?\[([^\]]+)\]")
CODE_SPAN = re.compile(r"`([^`\n]+)`")
JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
JINJA_TAG = re.compile(r"\{%-?\s*(.*?)\s*-?%\}|\{\{-?\s*(.*?)\s*-?\}\}", re.S)
JINJA_STRING = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'")
#: The edit hook of the repository refuses this character in a template.
EM_DASH = chr(0x2014)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, text: str) -> None:
        self.errors.append(f"ERROR {where}: {text}")

    def warn(self, where: str, text: str) -> None:
        self.warnings.append(f"warning {where}: {text}")


def messages(text: str) -> dict[str, str]:
    """The messages of a Fluent catalog, each with its value and continuation lines."""
    found: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        match = MESSAGE.match(line)
        if match:
            current = match.group(1)
            found[current] = [match.group(2)]
        elif current and line[:1] in (" ", "\t", "}") and line.strip():
            found[current].append(line)
        elif line.strip():
            current = None
    return {key: "\n".join(lines) for key, lines in found.items()}


def check_catalog(report: Report, code: str, english_path: Path, path: Path, notes: bool) -> None:
    where = str(path.relative_to(ROOT))
    if not path.is_file():
        report.error(where, "the file is missing")
        return
    english = messages(english_path.read_text(encoding="utf-8"))
    text = path.read_text(encoding="utf-8")
    header = f"# Translation of en/{english_path.name}. Change it together with the English catalog."
    if text.splitlines()[:1] != [header]:
        report.error(where, f"the first line must be: {header}")
    translated = messages(text)
    for key in sorted(set(english) - set(translated)):
        report.error(where, f"{key} is missing, so it shows in English")
    for key in sorted(set(translated) - set(english)):
        report.error(where, f"{key} is not an English message")
    for key in sorted(set(translated) & set(english)):
        value, source = translated[key], english[key]
        wanted, got = set(VARIABLE.findall(source)), set(VARIABLE.findall(value))
        if got != wanted:
            selector_only = {v for v in wanted - got
                             if source.count(f"${v}") == source.count(f"${v} ->")}
            if not (code in ONE_FORM and got <= wanted and wanted - got == selector_only):
                report.error(where, f"{key} has the variables {sorted(got)}, English has {sorted(wanted)}")
        if value.count("{") != value.count("}"):
            report.error(where, f"{key} has unbalanced braces")
        if re.search(r"->[ \t]*\*?\[", value):
            report.error(where, f"{key} has a variant on the line of its selector; start each variant on a new line")
        if "->" in value:
            if notes:
                report.error(where, f"{key} has a selector, which the worker cannot read")
            if "*[" not in value:
                report.error(where, f"{key} has a selector without a default variant (*[...])")
            for line in value.splitlines():
                variant = VARIANT.match(line)
                if variant:
                    name = variant.group(1).strip()
                    if not name.isdigit() and name not in PLURALS[code] and f"[{name}]" not in source:
                        report.error(where, f"{key} has the variant [{name}], {code} has {sorted(PLURALS[code])}")
        words = re.findall(r"(?<![$\w])[a-zA-Z]{2,}\b", re.sub(r"\{[^{}]*\}", " ", source))
        if value.strip() == source.strip() and len(words) >= 3:
            report.warn(where, f"{key} is the same as English: {value.strip()[:70]}")


def jinja_skeleton(text: str) -> list[str]:
    """The Jinja statements and expressions in order, with string literals replaced."""
    text = JINJA_COMMENT.sub("", text)
    parts = []
    for statement, expression in JINJA_TAG.findall(text):
        body = JINJA_STRING.sub("STR", (statement or expression)).strip()
        parts.append(("%" if statement else "=") + " ".join(body.split()))
    # `citation_artefact` is the English word `report` in every profile, so a translation
    # writes its own word for it (`skill_store.ROLE_CONTEXT`).
    return [part for part in parts if part != "=citation_artefact"]


def code_spans(text: str) -> set[str]:
    """The inline code spans outside fenced blocks. A fenced example may translate its values."""
    text = re.sub(r"```.*?```", " ", JINJA_COMMENT.sub("", text), flags=re.S)
    return set(CODE_SPAN.findall(text))


def check_template(report: Report, where: str, english: str, translated: str) -> None:
    try:
        Environment().parse(translated)
    except TemplateSyntaxError as error:
        report.error(where, f"the template does not parse: line {error.lineno}: {error.message}")
        return
    source, target = jinja_skeleton(english), jinja_skeleton(translated)
    if source != target:
        index = next((i for i, (a, b) in enumerate(zip(source, target)) if a != b), min(len(source), len(target)))
        report.error(where, f"the Jinja tags differ from English at tag {index + 1}: "
                            f"English {source[index:index + 1]}, translation {target[index:index + 1]}")
    missing = sorted(code_spans(english) - code_spans(translated))
    added = sorted(code_spans(translated) - code_spans(english))
    if missing:
        report.warn(where, f"English code spans not found: {missing[:8]}")
    if added:
        report.warn(where, f"code spans that English does not have: {added[:8]}")
    if EM_DASH in translated:
        report.error(where, "it has an em dash, which the repository edit hook refuses")


def front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    head, _, body = text[4:].partition("\n---\n")
    fields = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


def role_lines() -> dict[str, str]:
    tree = ast.parse((AGENT / "prompts/__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "ROLE_LINES":
            return ast.literal_eval(node.value)
    raise SystemExit("ROLE_LINES not found in prompts/__init__.py")


def check_agent(report: Report, code: str) -> None:
    prompt = AGENT / "prompts" / code / "agent.md.j2"
    where = str(prompt.relative_to(ROOT))
    if prompt.is_file():
        check_template(report, where, (AGENT / "prompts/agent.md.j2").read_text(encoding="utf-8"),
                       prompt.read_text(encoding="utf-8"))
    else:
        report.error(where, "the file is missing")

    lines_path = AGENT / "prompts" / code / "role_lines.json"
    where = str(lines_path.relative_to(ROOT))
    try:
        lines = json.loads(lines_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        report.error(where, f"cannot read: {error}")
        lines = {}
    for name, source in role_lines().items():
        if name not in lines:
            report.error(where, f"the role line {name} is missing")
        else:
            check_template(report, f"{where} {name}", source, lines[name])

    for english_path in sorted((AGENT / "skills").rglob("*.j2")):
        relative = english_path.relative_to(AGENT / "skills")
        if relative.parts[0] in PLURALS:
            continue
        path = AGENT / "skills" / code / relative
        where = str(path.relative_to(ROOT))
        if not path.is_file():
            report.error(where, "the file is missing, so the English text is used")
            continue
        english_fields, english_body = front_matter(english_path.read_text(encoding="utf-8"))
        fields, body = front_matter(path.read_text(encoding="utf-8"))
        for key in ("name", "group", "tools"):
            if fields.get(key) != english_fields.get(key):
                report.error(where, f"the header {key} must stay {english_fields.get(key)!r}")
        for key in ("description", "terms", "not_for"):
            if english_fields.get(key) and not fields.get(key):
                report.error(where, f"the header {key} is missing")
        for key in set(fields) - set(english_fields):
            report.error(where, f"the header {key} is not in English")
        check_template(report, where, english_body, body)

    texts_path = AGENT / "tool_texts" / f"{code}.json"
    where = str(texts_path.relative_to(ROOT))
    english_texts = json.loads((AGENT / "tool_texts/en.json").read_text(encoding="utf-8"))
    try:
        texts = json.loads(texts_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        report.error(where, f"cannot read: {error}")
        return
    for text in english_texts:
        value = texts.get(text)
        if not isinstance(value, str) or not value.strip():
            report.error(where, f"no translation for {text[:70]!r}")
        elif set(CODE_SPAN.findall(text)) - set(CODE_SPAN.findall(value)):
            report.warn(where, f"code spans of English not found in the translation of {text[:50]!r}")
    for text in sorted(set(texts) - set(english_texts)):
        report.error(where, f"{text[:70]!r} is not an English tool text")


def check_language(report: Report, code: str) -> None:
    for english_path in sorted((WEBSITE / "en").glob("*.ftl")):
        check_catalog(report, code, english_path, WEBSITE / code / english_path.name, notes=False)
    check_catalog(report, code, NOTES / "en/notes.ftl", NOTES / code / "notes.ftl", notes=True)
    check_agent(report, code)
    for name in (f"{code}.json", f"agent-{code}.json"):
        path = GLOSSARY / name
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            report.error(str(path.relative_to(ROOT)), f"cannot read: {error}")


def main(argv: list[str]) -> int:
    codes = LANGUAGES if argv == ["--all"] else argv
    if not codes or any(code not in LANGUAGES for code in codes):
        print(__doc__)
        return 2
    report = Report()
    for code in codes:
        check_language(report, code)
    for line in report.warnings + report.errors:
        print(line)
    print(f"{len(report.errors)} errors, {len(report.warnings)} warnings for {', '.join(codes)}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
