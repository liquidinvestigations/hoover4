"""The agent language of a run, and the translated texts that the model reads.

The worker sends the language code of the run in every step request (`StepRun.language`).
The website resolves it when the turn starts, so the whole run keeps one language. An empty
or unknown code selects English.

Three kinds of translated text exist for each language. English is the source of each, and
a missing translation falls back to the English text.

* `prompts/<language>/agent.md.j2` and `prompts/<language>/role_lines.json`: the system
  prompt and the role lines (`prompts`).
* `skills/<language>/<name>.md.j2` and `skills/<language>/partials/`: the skills
  (`skill_store`). A translated file changes the description, the routing words and the
  body. The name, the group and the tools come from the English file.
* `tool_texts/<language>.json`: an English description of a tool or of an argument,
  mapped to its translation. It changes only the definitions that the model is shown
  (`steps.shown_tool`) and the tool summaries. Tool names, argument names, enum values and
  schema keys stay English, so a call validates and runs as before.

`catalog_revision` is a digest of these files for one language. It is part of the context
key of a run (`agent.MCPGatewayAgent._acl_key`) and of the revision of the control
snapshot, so a context or a pinned snapshot of one language is never reused for another.

The language table is a twin of `processing/tasks/P_agent/language.py`. Change both.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

#: The fallback language and the source of every translation.
DEFAULT_LANGUAGE = "en"

#: The supported codes with their own name and their English name.
LANGUAGES: Dict[str, tuple] = {
    "en": ("English", "English"),
    "de": ("Deutsch", "German"),
    "es": ("Español", "Spanish"),
    "fr": ("Français", "French"),
    "pl": ("Polski", "Polish"),
    "pt": ("Português", "Portuguese"),
    "ar": ("العربية", "Arabic"),
    "he": ("עברית", "Hebrew"),
    "hi": ("हिन्दी", "Hindi"),
    "zh": ("中文", "Chinese"),
    "it": ("Italiano", "Italian"),
    "nl": ("Nederlands", "Dutch"),
    "da": ("Dansk", "Danish"),
    "nb": ("Norsk bokmål", "Norwegian Bokmål"),
    "sv": ("Svenska", "Swedish"),
    "el": ("Ελληνικά", "Greek"),
    "hr": ("Hrvatski", "Croatian"),
    "ro": ("Română", "Romanian"),
    "ru": ("Русский", "Russian"),
    "ja": ("日本語", "Japanese"),
    "ko": ("한국어", "Korean"),
}

PACKAGE_DIR = Path(__file__).parent
PROMPT_DIR = PACKAGE_DIR / "prompts"
SKILL_DIR = PACKAGE_DIR / "skills"
TOOL_TEXT_DIR = PACKAGE_DIR / "tool_texts"


def run_language(code: Optional[str]) -> str:
    """The language of a run from the code of its request. An unknown code selects English."""
    code = (code or "").strip().lower()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def language_name(code: Optional[str]) -> str:
    """The name of a language for the prompt: its own name and its English name, or
    `English`."""
    own, english = LANGUAGES[run_language(code)]
    return english if own == english else f"{own} ({english})"


def translated_files(language: str) -> list:
    """The translated files of one language, sorted. English has none."""
    language = run_language(language)
    if language == DEFAULT_LANGUAGE:
        return []
    files = [path for folder in (PROMPT_DIR / language, SKILL_DIR / language)
             if folder.is_dir() for path in folder.rglob("*") if path.is_file()]
    texts = TOOL_TEXT_DIR / f"{language}.json"
    if texts.is_file():
        files.append(texts)
    return sorted(files)


@lru_cache(maxsize=None)
def catalog_revision(language: str) -> str:
    """A digest of the translated files of one language. Empty for English."""
    files = translated_files(language)
    if not files:
        return ""
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(PACKAGE_DIR)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


@lru_cache(maxsize=None)
def tool_texts(language: str) -> Dict[str, str]:
    """The translated tool texts of one language, by English text. Empty for English or for
    a language without a file. A file that does not parse logs an error and gives none."""
    path = TOOL_TEXT_DIR / f"{run_language(language)}.json"
    if run_language(language) == DEFAULT_LANGUAGE or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        log.error("the tool texts of %s do not parse: %s", language, exc)
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v}


def localize_text(text: str, language: str) -> str:
    """The translation of one English tool text, or the text itself."""
    if not text:
        return text
    return tool_texts(language).get(text.strip(), text)


def localize_schema(schema: Any, language: str) -> Any:
    """A copy of a JSON schema with each `description` translated. Every other key and value
    stays as it is."""
    if not tool_texts(language):
        return schema

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: (localize_text(value, language)
                          if key == "description" and isinstance(value, str) else walk(value))
                    for key, value in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(copy.deepcopy(schema))


__all__ = [
    "DEFAULT_LANGUAGE", "LANGUAGES", "catalog_revision", "language_name", "localize_schema",
    "localize_text", "run_language", "tool_texts", "translated_files",
]
