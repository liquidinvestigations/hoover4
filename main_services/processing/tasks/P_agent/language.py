"""The supported languages and the code check of the agent language.

The website resolves the agent language of a turn with `website/common/src/language.rs`
and sends the code in the `AgentRun` input. The worker checks it again with
`supported_code`, so an unknown value runs the turn in English. Both test suites read the
cases in `language_vectors.json`.
"""

from __future__ import annotations

from typing import Optional

#: The fallback language and the source of every catalog.
DEFAULT_LANGUAGE = "en"

#: The 21 supported codes with their own name and their English name.
LANGUAGES: dict[str, tuple[str, str]] = {
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

_ALIASES = {"no": "nb", "nn": "nb", "iw": "he"}


def supported_code(tag: Optional[str]) -> Optional[str]:
    """The supported code of a language tag, or `None`.

    The comparison ignores case and takes the primary subtag. `no` and `nn` select `nb`,
    and `iw` selects `he`.
    """
    if not tag:
        return None
    primary = tag.strip().lower().replace("_", "-").split("-")[0]
    primary = _ALIASES.get(primary, primary)
    return primary if primary in LANGUAGES else None


def from_accept_language(header: Optional[str]) -> Optional[str]:
    """The first supported language of an `Accept-Language` header by quality, then position."""
    ranges = []
    for position, part in enumerate((header or "").split(",")):
        fields = part.split(";")
        tag = fields[0].strip()
        quality = 1.0
        for field in fields[1:]:
            field = field.strip()
            if field.startswith("q="):
                try:
                    quality = float(field[2:].strip())
                except ValueError:
                    quality = 0.0
                break
        if quality > 0 and tag and tag != "*":
            ranges.append((-quality, position, tag))
    for _, _, tag in sorted(ranges):
        code = supported_code(tag)
        if code:
            return code
    return None


def interface_language(saved: Optional[str], accept_language: Optional[str]) -> str:
    """The saved interface language, else the browser header, else English."""
    return supported_code(saved) or from_accept_language(accept_language) or DEFAULT_LANGUAGE


def agent_language(saved_agent: Optional[str], interface: str) -> str:
    """The saved agent language, else the interface language."""
    return supported_code(saved_agent) or supported_code(interface) or DEFAULT_LANGUAGE


def turn_language(code: Optional[str]) -> str:
    """The language of a turn from the code in its input. An unknown code selects English."""
    return supported_code(code) or DEFAULT_LANGUAGE


def english_name(code: str) -> str:
    """The English name of a supported code."""
    return LANGUAGES[turn_language(code)][1]
