"""Translate the instructions of the research agent from English with a chat model.

Usage, from the repository root:

    uv run --no-project --with fluent.syntax --with requests \\
        python scripts/i18n/translate_agent.py main_services/agents/research_agent/research_agent \\
        --base-url <OpenAI-compatible URL> --model ornith --key-file <path> [--languages de,ar]

The tool writes, for each language, the files that `research_agent.localization` reads:

* `prompts/<code>/agent.md.j2` and `prompts/<code>/role_lines.json`,
* `skills/<code>/<name>.md.j2` and `skills/<code>/partials/<name>.j2`,
* `tool_texts/<code>.json`, from the English list `tool_texts/en.json`
  (`scripts/i18n/agent_tool_texts.py` writes that list).

Jinja tags, Jinja comments, code spans in backticks and `{name}` fields are replaced by
numbered markers before the model sees the text. A reply must return every marker once,
keep the number of lines, and keep each line that holds only a Jinja tag. A part that fails
twice stays English. A skill keeps its English front matter except `description`, `terms`
and `not_for`. `translations.json` in the package folder records the producer, the
parameters and the English text hash of each translated file and text, so a second run
translates only what changed. The glossary is the one of `translate_catalogs.py` and the
agent terms of `glossary_agent.json`. A line that continues an unfinished sentence is joined
to the line before it, so a translated template can have fewer lines than English.
"""

from __future__ import annotations

import argparse
import ast as python_ast
import concurrent.futures
import json
import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from translate_catalogs import HERE, LANGUAGES, Model, glossary, sha, strip_fence  # noqa: E402

#: A Jinja tag or comment, a code span, or a `{name}` field.
PROTECTED = re.compile(r"\{%-?.*?-?%\}|\{\{.*?\}\}|\{#.*?#\}|`[^`\n]+`|\{[a-z_]+\}", re.S)
MARKER = re.compile(r"⟦(\d+)⟧")
#: The longest part of a template that one request translates, in characters.
PART_CHARS = 2400
TEXT_BATCH = 20

SYSTEM = """You translate the instructions of an AI research assistant from English into {language}.
The assistant searches document collections and the web for investigative journalists.
Rules:
- Reply with the translation only, with no explanation and no code fence.
- The text holds markers such as ⟦3⟧. Each marker stands for code. Keep every marker exactly once, at the place where its code belongs in the {language} sentence.
- Keep the same number of lines. Translate each line into one line. Keep empty lines empty. A line that holds only markers stays as it is.
- Keep Markdown list markers, heading markers and indentation.
- Markers inside a sentence can choose between words, as in "on ⟦4⟧an internal⟦5⟧a⟦6⟧ document". Translate the words between such markers so that each choice gives a correct {language} sentence. Put the whole noun phrase inside each choice when the grammar needs it.
- Keep tool names, argument names, file names, URLs, JSON keys and quoted search syntax in English.
- Write clear, direct instructions. Address the assistant in the second person, in the form that technical documentation in {language} uses.
- Use the glossary terms below for these concepts.

Glossary (English term: {language} term):
{glossary}"""

PROOF_SYSTEM = """You proofread {language} instructions for an AI research assistant.
Rules:
- Reply with the corrected text only, with no explanation and no code fence.
- Correct spelling, grammar, inflection and word order. Use the imperative of the second person singular consistently.
- Keep the meaning. Do not add or remove sentences.
- The text holds markers such as ⟦3⟧. Each marker stands for code. Keep every marker exactly once, at its place.
- Keep the same number of lines. Keep empty lines empty. Keep a line that holds only markers as it is.
- Keep tool names, argument names, file names, URLs, JSON keys and quoted search syntax in English."""

TEXT_SYSTEM = """You translate the descriptions of the tools of an AI research assistant from English into {language}.
Rules:
- The input is a JSON object of numbered English texts. Reply with one JSON object only, with the same keys and the {language} texts.
- Each text may hold markers such as ⟦3⟧. Each marker stands for code. Keep every marker exactly once.
- Keep tool names, argument names, enum values, file formats, URLs and quoted search syntax in English.
- Keep line breaks and list markers.
- Use the glossary terms below for these concepts.

Glossary (English term: {language} term):
{glossary}"""


def agent_glossary(model: Model, code: str) -> dict[str, str]:
    """The terms of `glossary_agent.json` in the target language, asked once and then read
    from `glossary/agent-<code>.json`."""
    path = HERE / "glossary" / f"agent-{code}.json"
    terms = json.loads((HERE / "glossary_agent.json").read_text())["terms"]
    revision = sha(json.dumps(terms, sort_keys=True))
    if path.exists():
        stored = json.loads(path.read_text())
        if stored.get("glossary_revision") == revision:
            return stored["terms"]
    listing = "\n".join(f"- {t['term']}: {t['meaning']}" for t in terms)
    reply = model.ask(
        "You are a software localization expert. Reply with one JSON object only.",
        f"Give one standard {LANGUAGES[code]} term for each English term below, for the "
        f"instructions of an AI research assistant. Use the term that technical documentation "
        f"in {LANGUAGES[code]} uses. Reply as a JSON object that maps each English term to its "
        f"{LANGUAGES[code]} term.\n\n{listing}",
        max_tokens=2000,
    )
    found = json.loads(strip_fence(reply))
    result = {t["term"]: str(found.get(t["term"], t["term"])) for t in terms}
    path.write_text(json.dumps({"glossary_revision": revision, "terms": result}, ensure_ascii=False, indent=1) + "\n")
    return result


def system_text(template: str, code: str, terms: dict) -> str:
    return (template.replace("{language}", LANGUAGES[code])
            .replace("{glossary}", "\n".join(f"{k}: {v}" for k, v in terms.items())))


def mask(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def keep(match: re.Match) -> str:
        tokens.append(match.group(0))
        return f"⟦{len(tokens) - 1}⟧"

    return PROTECTED.sub(keep, text), tokens


def unmask(text: str, tokens: list[str]) -> str:
    return MARKER.sub(lambda m: tokens[int(m.group(1))], text)


def marker_problem(english: str, translated: str, count: int, lines: bool) -> str | None:
    found = [int(n) for n in MARKER.findall(translated)]
    if sorted(found) != list(range(count)):
        return "the markers differ"
    if not lines:
        return None
    source_lines, target_lines = english.split("\n"), translated.split("\n")
    if len(source_lines) != len(target_lines):
        return f"{len(target_lines)} lines for {len(source_lines)}"
    for a, b in zip(source_lines, target_lines):
        if MARKER.sub("", a).strip() == "" and a.strip() != b.strip():
            return "a line of markers changed"
        if (a.strip() == "") != (b.strip() == ""):
            return "an empty line moved"
    return None


_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def unwrap(masked: str) -> str:
    """Join each line that continues an unfinished sentence to the line before it. A list
    item, a line of markers only, and a line after one stay on their own line."""
    out: list[str] = []
    for line in masked.split("\n"):
        previous = out[-1] if out else ""
        joins = (previous.strip() and line.strip() and not _LIST_ITEM.match(line)
                 and MARKER.sub("", line).strip() and MARKER.sub("", previous).strip()
                 and not previous.rstrip().endswith((".", "!", "?", ":")))
        if joins:
            out[-1] = previous.rstrip() + " " + line.strip()
        else:
            out.append(line)
    return "\n".join(out)


def parts(body: str) -> list[str]:
    """The body split at empty lines into parts of at most PART_CHARS characters."""
    out: list[str] = []
    current = ""
    for paragraph in re.split(r"(?<=\n\n)", body):
        if current and len(current) + len(paragraph) > PART_CHARS:
            out.append(current)
            current = ""
        current += paragraph
    if current:
        out.append(current)
    return out


def translate_part(model: Model, code: str, terms: dict, part: str, problems: list, where: str) -> str:
    masked, tokens = mask(part)
    if not MARKER.sub("", masked).strip():
        return part
    # The edge newlines are kept outside the request and put back after it.
    lead = masked[:len(masked) - len(masked.lstrip("\n"))]
    tail = masked[len(masked.rstrip("\n")):]
    core = unwrap(masked.strip("\n"))
    for _attempt in range(2):
        reply = strip_fence(model.ask(system_text(SYSTEM, code, terms), core)).strip("\n")
        reason = marker_problem(core, reply, len(tokens), lines=True)
        if reason is None:
            # A proofread that breaks a marker or a line is dropped, and the translation stays.
            checked = strip_fence(model.ask(system_text(PROOF_SYSTEM, code, terms), reply)).strip("\n")
            if marker_problem(core, checked, len(tokens), lines=True) is None:
                reply = checked
            return unmask(lead + reply + tail, tokens)
    # A part of several paragraphs is tried again paragraph by paragraph.
    paragraphs = re.split(r"(?<=\n\n)", part)
    if len(paragraphs) > 1:
        return "".join(translate_part(model, code, terms, p, problems, where) for p in paragraphs)
    problems.append(f"{code} {where}: {reason}, the English part stays")
    return part


def strip_comments(text: str) -> str:
    """The template without Jinja comments, which the model need not read."""
    return re.sub(r"\{#.*?#\}\n?", "", text, flags=re.S)


def translate_template(model: Model, code: str, terms: dict, text: str, problems: list, where: str) -> str:
    return "".join(translate_part(model, code, terms, part, problems, where)
                   for part in parts(strip_comments(text)))


def translate_texts(model: Model, code: str, terms: dict, texts: list[str], problems: list, where: str) -> dict:
    """English text to translation for a list of short texts, in batches."""
    out: dict[str, str] = {}
    for start in range(0, len(texts), TEXT_BATCH):
        batch = texts[start:start + TEXT_BATCH]
        masked = [mask(text) for text in batch]
        request = {str(i): m for i, (m, _) in enumerate(masked)}
        print(f"  {code} {where}: texts {start + 1}-{start + len(batch)} of {len(texts)}", flush=True)
        for _attempt in range(2):
            try:
                reply = json.loads(strip_fence(model.ask(system_text(TEXT_SYSTEM, code, terms),
                                                         json.dumps(request, ensure_ascii=False))))
            except ValueError:
                continue
            missing = []
            for key in request:
                masked_text, tokens = masked[int(key)]
                value = reply.get(key)
                english = batch[int(key)]
                if english in out:
                    continue
                if isinstance(value, str) and marker_problem(masked_text, value, len(tokens), False) is None:
                    out[english] = unmask(value, tokens)
                else:
                    missing.append(key)
            request = {k: request[k] for k in missing}
            if not request:
                break
        for key in request:
            problems.append(f"{code} {where}: text {start + int(key)} stays English")
    return out


def front_matter(text: str) -> tuple[list[str], str]:
    lines = text.split("\n")
    end = lines.index("---", 1)
    return lines[:end + 1], "\n".join(lines[end + 1:])


def translate_skill(model: Model, code: str, terms: dict, text: str, problems: list, where: str) -> str:
    head, body = front_matter(text)
    fields = [line for line in head[1:-1] if line.split(":", 1)[0].strip() in ("description", "terms", "not_for")]
    values = [line.split(":", 1)[1].strip() for line in fields]
    translated = translate_texts(model, code, terms, values, problems, where) if values else {}
    out_head = []
    for line in head:
        key = line.split(":", 1)[0].strip()
        if line in fields:
            value = line.split(":", 1)[1].strip()
            out_head.append(f"{key}: {translated.get(value, value)}")
        else:
            out_head.append(line)
    return "\n".join(out_head) + "\n" + translate_template(model, code, terms, body, problems, where)


def role_lines(package: Path) -> dict:
    tree = python_ast.parse((package / "prompts" / "__init__.py").read_text())
    for node in tree.body:
        if isinstance(node, python_ast.AnnAssign) and getattr(node.target, "id", "") == "ROLE_LINES":
            return python_ast.literal_eval(node.value)
    raise SystemExit("ROLE_LINES not found")


def translate_language(model: Model, package: Path, code: str, record: dict, lock: threading.Lock) -> list[str]:
    problems: list[str] = []
    terms = {**glossary(model, code), **agent_glossary(model, code)}
    with lock:
        hashes = record.setdefault("sources", {}).setdefault(code, {})

    def wanted(key: str, english: str) -> bool:
        return hashes.get(key) != sha(english)

    def done(key: str, english: str) -> None:
        with lock:
            hashes[key] = sha(english)

    sources = [("prompts/agent.md.j2", package / "prompts" / "agent.md.j2", package / "prompts" / code / "agent.md.j2", "template")]
    for path in sorted((package / "skills").glob("*.md.j2")):
        sources.append((f"skills/{path.name}", path, package / "skills" / code / path.name, "skill"))
    for path in sorted((package / "skills" / "partials").glob("*.j2")):
        sources.append((f"skills/partials/{path.name}", path, package / "skills" / code / "partials" / path.name, "template"))
    for key, source, target, kind in sources:
        english = source.read_text()
        if not wanted(key, english) and target.exists():
            continue
        print(f"  {code} {key}", flush=True)
        before = len(problems)
        text = (translate_skill if kind == "skill" else translate_template)(model, code, terms, english, problems, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        if len(problems) == before:
            done(key, english)

    roles = role_lines(package)
    english = json.dumps(roles, sort_keys=True)
    target = package / "prompts" / code / "role_lines.json"
    if wanted("prompts/role_lines", english) or not target.exists():
        before = len(problems)
        out = {name: translate_template(model, code, terms, source, problems, f"role line {name}")
               for name, source in roles.items()}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
        if len(problems) == before:
            done("prompts/role_lines", english)

    # A tool text is keyed by its English text, so a changed text is a new key.
    texts = json.loads((package / "tool_texts" / "en.json").read_text())
    target = package / "tool_texts" / f"{code}.json"
    existing = json.loads(target.read_text()) if target.exists() else {}
    missing = [t for t in texts if t not in existing]
    if missing:
        existing.update(translate_texts(model, code, terms, missing, problems, "tool_texts"))
    kept = {t: existing[t] for t in texts if t in existing}
    target.write_text(json.dumps(kept, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("package", type=Path, help="the research_agent package folder")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--languages", default=",".join(LANGUAGES))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--producer", default="", help="the model description for the record, without credentials")
    args = parser.parse_args()
    model = Model(args.base_url, args.model, args.key_file.read_text().strip(), args.temperature)
    record_path = args.package / "translations.json"
    record = json.loads(record_path.read_text()) if record_path.exists() else {}
    record.update({
        "producer": args.producer or f"model {args.model}",
        "parameters": {"temperature": args.temperature, "thinking": False},
        "review": "not reviewed by a native speaker",
    })
    lock = threading.Lock()
    codes = [c for c in args.languages.split(",") if c in LANGUAGES]
    problems: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        for found in pool.map(lambda code: translate_language(model, args.package, code, record, lock), codes):
            problems.extend(found)
            with lock:
                record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"{len(problems)} parts or texts stay English")
    for problem in problems:
        print(f"  {problem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
