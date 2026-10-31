"""Translate Fluent catalogs from English with a chat model, and record the producer.

Usage, from the repository root:

    uv run --no-project --with fluent.syntax --with requests \\
        python scripts/i18n/translate_catalogs.py website/frontend/i18n \\
        --base-url <OpenAI-compatible URL> --model ornith --key-file <path> [--languages de,ar]

A catalog folder has `en/<name>.ftl` and one folder for each other language. The tool
translates each English message that a language lacks, and each message whose English
text changed since its last translation. It removes messages that English no longer has.
`translations.json` in the catalog folder records the producer, the parameters, the
glossary and the English text hash of each translated message.

The model gets the terms of `glossary.json` in the target language. The tool asks for those
terms once for each language and stores them in `glossary/<code>.json`, so every batch uses
the same words. Each returned message must parse as Fluent, keep the variables of the
English message, and use only the plural categories of the target language. A message that
fails twice stays absent, and the interface shows its English text.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests
from fluent.syntax import FluentParser, FluentSerializer, ast
from fluent.syntax.visitor import Visitor

HERE = Path(__file__).resolve().parent

#: The supported languages other than English, with their English names.
LANGUAGES = {
    "de": "German", "es": "Spanish", "fr": "French", "pl": "Polish", "pt": "Portuguese (Portugal)",
    "ar": "Arabic", "he": "Hebrew", "hi": "Hindi", "zh": "Simplified Chinese", "it": "Italian",
    "nl": "Dutch", "da": "Danish", "nb": "Norwegian Bokmål", "sv": "Swedish", "el": "Greek",
    "hr": "Croatian", "ro": "Romanian",
}

#: The CLDR cardinal plural categories of each language.
PLURALS = {
    "en": {"one", "other"}, "de": {"one", "other"}, "es": {"one", "many", "other"},
    "fr": {"one", "many", "other"}, "pl": {"one", "few", "many", "other"},
    "pt": {"one", "many", "other"}, "ar": {"zero", "one", "two", "few", "many", "other"},
    "he": {"one", "two", "other"}, "hi": {"one", "other"}, "zh": {"other"},
    "it": {"one", "many", "other"}, "nl": {"one", "other"}, "da": {"one", "other"},
    "nb": {"one", "other"}, "sv": {"one", "other"}, "el": {"one", "other"},
    "hr": {"one", "few", "other"}, "ro": {"one", "few", "other"},
}

BATCH = 30
PARSER = FluentParser(with_spans=False)
SERIALIZER = FluentSerializer()


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def messages(path: Path) -> dict[str, ast.Message]:
    """The messages of one catalog file, by id, in file order."""
    if not path.exists():
        return {}
    resource = PARSER.parse(path.read_text(encoding="utf-8"))
    junk = [entry for entry in resource.body if isinstance(entry, ast.Junk)]
    if junk:
        raise SystemExit(f"{path}: {len(junk)} entries do not parse: {junk[0].content[:200]!r}")
    return {entry.id.name: entry for entry in resource.body if isinstance(entry, ast.Message)}


def source(message: ast.Message) -> str:
    return SERIALIZER.serialize_entry(message)


def variables(message: ast.Message) -> set[str]:
    return set(re.findall(r"\$([A-Za-z][A-Za-z0-9_-]*)", source(message)))


def plural_keys(message: ast.Message) -> set[str]:
    """The non-numeric variant keys of every selector in a message."""
    keys: set[str] = set()

    class Keys(Visitor):
        def visit_Variant(self, node):  # noqa: N802 (the visitor names the node class)
            if isinstance(node.key, ast.Identifier):
                keys.add(node.key.name)
            self.generic_visit(node)

    Keys().visit(message)
    return keys


def check(code: str, english: ast.Message, translated: ast.Message) -> str | None:
    """Why a translated message is not usable, or `None`."""
    if variables(translated) != variables(english):
        return f"variables {sorted(variables(translated))} differ from {sorted(variables(english))}"
    keys = plural_keys(translated)
    english_keys = plural_keys(english)
    if english_keys and english_keys <= PLURALS["en"]:
        extra = keys - PLURALS[code]
        if extra:
            return f"plural keys {sorted(extra)} are not categories of {code}"
        if "other" not in keys:
            return "the plural selector has no other variant"
    elif keys != english_keys:
        return f"selector keys {sorted(keys)} differ from {sorted(english_keys)}"
    if bool(translated.attributes) != bool(english.attributes):
        return "attributes differ"
    if code not in UNCASED and starts_upper(english) and not starts_upper(translated):
        return "the English text starts with a capital letter and the translation does not"
    return None


#: The languages whose scripts have no letter case.
UNCASED = {"ar", "he", "hi", "zh"}


def starts_upper(message: ast.Message) -> bool:
    """Whether the first letter of the message value is a capital letter."""
    text = source(message).split("=", 1)[1].lstrip()
    letter = next((c for c in text if c.isalpha()), "")
    return letter.isupper()


class Model:
    def __init__(self, base_url: str, model: str, key: str, temperature: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.key = key
        self.temperature = temperature

    def ask(self, system: str, user: str, max_tokens: int = 12000) -> str:
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "chat_template_kwargs": {"enable_thinking": False},
        }
        for attempt in range(4):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json=body,
                    timeout=(10, 600),
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"] or ""
            except (requests.RequestException, KeyError, ValueError) as error:
                if attempt == 3:
                    raise
                print(f"  model request failed ({error}), retrying", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        return ""


def strip_fence(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", text, re.S)
    return match.group(1) if match else text


def glossary(model: Model, code: str) -> dict[str, str]:
    """The glossary terms in the target language, asked once and then read from disk."""
    path = HERE / "glossary" / f"{code}.json"
    terms = json.loads((HERE / "glossary.json").read_text())["terms"]
    revision = sha(json.dumps(terms, sort_keys=True))
    if path.exists():
        stored = json.loads(path.read_text())
        if stored.get("glossary_revision") == revision:
            return stored["terms"]
    listing = "\n".join(
        f"- {t['term']}: {t['meaning']}" + (" Keep this term in English." if t.get("keep") else "")
        for t in terms
    )
    reply = model.ask(
        "You are a software localization expert. Reply with one JSON object only.",
        f"Give the standard {LANGUAGES[code]} term for each English software term below, for the "
        f"interface of a document search and investigation application. Use the form that a "
        f"button label or heading would use. Reply as a JSON object that maps each English term "
        f"to its {LANGUAGES[code]} term.\n\n{listing}",
        max_tokens=4000,
    )
    found = json.loads(strip_fence(reply))
    result = {t["term"]: (t["term"] if t.get("keep") else str(found.get(t["term"], t["term"]))) for t in terms}
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"glossary_revision": revision, "terms": result}, ensure_ascii=False, indent=1) + "\n")
    return result


SYSTEM = """You translate Fluent (.ftl) localization messages for a document search and investigation website.
Rules:
- Reply with the translated messages in Fluent syntax only, with no explanation and no code fence.
- Keep every message id exactly. Translate only the text after `=`.
- Keep every placeable such as { $count } and every variable name exactly. Do not add or remove variables.
- For a plural selector such as { $count -> [one] ... *[other] ... } use the CLDR plural categories of the target language: {plurals}. Keep *[other] as the default variant.
- Keep product names, file format names, code, paths, keyboard keys and quoted protocol values in English.
- Use the glossary terms below for these concepts.
- Write plain, short interface text in the register of professional software. Use the formal or neutral form of address that software in this language uses.
- Keep multi-line messages as multi-line messages, with each continuation line indented by four spaces.

Glossary (English term: {language} term):
{glossary}"""


def translate_batch(model: Model, code: str, terms: dict[str, str], batch: list[ast.Message]) -> dict[str, ast.Message]:
    system = (
        SYSTEM.replace("{plurals}", ", ".join(sorted(PLURALS[code])))
        .replace("{language}", LANGUAGES[code])
        .replace("{glossary}", "\n".join(f"{k}: {v}" for k, v in terms.items()))
    )
    text = "".join(source(message) for message in batch)
    # Some models translate the ids of right-to-left languages. The request repeats the rule
    # after the messages, where the model reads it last.
    reply = strip_fence(model.ask(system, (
        f"Translate these messages into {LANGUAGES[code]}:\n\n{text}\n"
        "Start each message with its English id and ` = ` exactly as above. Do not translate the ids.")))
    resource = PARSER.parse(reply + "\n")
    found = {entry.id.name: entry for entry in resource.body if isinstance(entry, ast.Message)}
    # A reply to one single-line message can hold the value only. The id goes back in front,
    # and `check` then verifies the variables as for any other reply.
    if not found and len(batch) == 1 and "\n" not in reply.strip():
        resource = PARSER.parse(f"{batch[0].id.name} = {reply.strip()}\n")
        found = {entry.id.name: entry for entry in resource.body if isinstance(entry, ast.Message)}
    return found


def translate_language(model: Model, catalog: Path, name: str, code: str, record: dict, args) -> list[str]:
    english = messages(catalog / "en" / name)
    target_path = catalog / code / name
    existing = messages(target_path)
    hashes = record.setdefault("messages", {}).setdefault(code, {}).setdefault(name, {})
    wanted = [
        message for message_id, message in english.items()
        if message_id not in existing or hashes.get(message_id) != sha(source(message))
    ]
    problems: list[str] = []
    if wanted:
        terms = glossary(model, code)
        done: dict[str, ast.Message] = {}
        batches = [wanted[i:i + BATCH] for i in range(0, len(wanted), BATCH)]
        for index, batch in enumerate(batches, 1):
            print(f"  {code} {name}: batch {index}/{len(batches)} ({len(batch)} messages)", flush=True)
            result = translate_batch(model, code, terms, batch)
            for message in batch:
                candidate = result.get(message.id.name)
                reason = "missing from the reply" if candidate is None else check(code, message, candidate)
                if reason:
                    retry = translate_batch(model, code, terms, [message]).get(message.id.name)
                    reason = "missing from the reply" if retry is None else check(code, message, retry)
                    candidate = None if reason else retry
                if candidate is None:
                    problems.append(f"{code}/{name} {message.id.name}: {reason}")
                    continue
                done[message.id.name] = candidate
                hashes[message.id.name] = sha(source(message))
        existing.update(done)
    for message_id in list(existing):
        if message_id not in english:
            existing.pop(message_id)
            hashes.pop(message_id, None)
    header = (
        f"# Machine translation of en/{name}. Do not edit by hand: change the English catalog\n"
        f"# and run scripts/i18n/translate_catalogs.py. See translations.json for the producer.\n\n"
    )
    ordered = [existing[message_id] for message_id in english if message_id in existing]
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(header + "".join(source(message) for message in ordered), encoding="utf-8")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("catalog", type=Path, help="the catalog folder, with en/<name>.ftl")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--languages", default=",".join(LANGUAGES))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--producer", default="", help="the model description for the record, without credentials")
    args = parser.parse_args()

    codes = [code.strip() for code in args.languages.split(",") if code.strip()]
    unknown = [code for code in codes if code not in LANGUAGES]
    if unknown:
        raise SystemExit(f"unsupported languages: {unknown}")
    model = Model(args.base_url, args.model, args.key_file.read_text().strip(), args.temperature)
    record_path = args.catalog / "translations.json"
    record = json.loads(record_path.read_text()) if record_path.exists() else {}
    names = sorted(path.name for path in (args.catalog / "en").glob("*.ftl"))

    problems: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(translate_language, model, args.catalog, name, code, record, args) for code in codes for name in names]
        for future in concurrent.futures.as_completed(futures):
            problems.extend(future.result())

    record["producer"] = {
        "model": args.model,
        "description": args.producer,
        "temperature": args.temperature,
        "batch_messages": BATCH,
        "thinking": False,
        "glossary": "scripts/i18n/glossary.json",
        "review": "Machine translation. No native speaker has reviewed it.",
        "updated": time.strftime("%Y-%m-%d"),
    }
    record["catalog_revision"] = sha("".join(
        path.read_text(encoding="utf-8") for path in sorted(args.catalog.glob("*/*.ftl"))
    ))
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    for problem in sorted(problems):
        print(f"not translated: {problem}")
    print(f"catalog revision {record['catalog_revision']}, {len(problems)} messages not translated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
