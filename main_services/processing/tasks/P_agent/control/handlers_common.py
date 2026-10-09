"""Text helpers of the built-in policy handlers: read addresses, web result details, page
sections and answer blocks. A handler module imports this module and no other handler
module."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

HEADING = re.compile(r"^\s*#{1,6}\s")
LIST_ITEM = re.compile(r"^([ \t]*)(?:[-+*]|\d+[.)])\s+")
#: The opening of a block that states a shortage or a method, not a sourced claim.
NOT_A_CLAIM = re.compile(
    r"^\s*(?:i\s+(?:could|did)\s+not|no\s+(?:document|source|page|result)s?\b|"
    r"the\s+(?:collections?|documents?|sources?|searches)\s+(?:do|did)\s+not|"
    r"(?:would|do)\s+you\b|please\b|if\s+you\b|note:)", re.IGNORECASE)


def read_urls(fact) -> list[str]:
    """The addresses that one `read_page` call requested."""
    args = fact.args if isinstance(fact.args, Mapping) else {}
    urls = args.get("urls") or args.get("url") or []
    return [urls] if isinstance(urls, str) else [u for u in urls if isinstance(u, str)]


def web_results(services, pool: list[dict]) -> list[dict]:
    """Title, address and snippet of each candidate, from its stored search result."""
    cache: dict[int, list] = {}
    out = []
    for cand in pool:
        idx = cand["idx"]
        if idx not in cache:
            try:
                parsed = json.loads(services.message_text(idx) or "{}")
            except ValueError:
                parsed = {}
            rows = parsed.get("results", parsed.get("items", [])) if isinstance(parsed, dict) else []
            cache[idx] = rows if isinstance(rows, list) else []
        row = next((r for r in cache[idx] if isinstance(r, dict) and r.get("url") == cand["url"]), {})
        out.append({"title": str(row.get("title") or ""), "url": cand["url"],
                    "snippet": str(row.get("snippet") or "")[:300]})
    return out


def page_sections(content: str) -> list[tuple[str, str, str]]:
    """(title, address, body) of each page section of a `read_page` result."""
    from tasks.P_agent.reports import _page_blocks

    try:
        parsed: Any = json.loads(content)
    except (TypeError, ValueError):
        parsed = content
    out = []
    for block in _page_blocks(parsed):
        lines = block.split("\n", 2)
        out.append((lines[0][3:].strip(), lines[1].strip(), lines[2].strip() if len(lines) > 2 else ""))
    return out


def answer_blocks(answer: str) -> list[dict]:
    """The paragraphs and list items of an answer, in order, with their position.

    A heading is no block. A block that states a shortage, a question to the person or an
    instruction is marked `claim` false, so a support check skips it."""
    blocks = []
    for number, paragraph in enumerate(re.split(r"\n\s*\n", answer or ""), 1):
        parts = re.split(r"\n(?=[ \t]*(?:[-+*]|\d+[.)])\s+)", paragraph)
        for position, part in enumerate(parts):
            text = part.strip()
            lines = [line for line in text.splitlines() if line.strip()]
            if not lines or all(HEADING.match(line) for line in lines):
                continue
            text = "\n".join(line for line in lines if not HEADING.match(line)).strip()
            if not text:
                continue
            body = LIST_ITEM.sub("", text, count=1)
            claim = (bool(re.search(r"[A-Z][a-z]+|\d", body)) and not NOT_A_CLAIM.match(body)
                     and not body.rstrip().endswith("?"))
            blocks.append({"id": f"b{len(blocks) + 1}", "paragraph": number,
                           "item": position if LIST_ITEM.match(text) else None,
                           "text": text, "claim": claim})
    return blocks
