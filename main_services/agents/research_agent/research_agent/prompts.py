"""Canonical system prompts for the two agent profiles.

They live here, not as YAML defaults in
`main_services/ops/docker/compose/agents.yaml`: multi-paragraph prompts inlined in compose
are unreadable and drift from the tool descriptions they are supposed to agree with. The
compose file passes an empty `SYSTEM_PROMPT` and these are the defaults; setting the env
var overrides them, which is what you want for an experiment.

**The Manticore MATCH syntax is deliberately not repeated here.** It reaches the model
through the collection-search MCP server's `instructions` string (see
`main_services/agents/collection_search_server/collection_search_server/prompts.py`), which is
read at tool-discovery time by *whichever* agent connects. Copying it into the agent
prompt would create a second copy to keep in step with the backend that implements it.
"""

from __future__ import annotations

import os

#: Two profiles, because the tool sets differ and so must the instructions about them.
#: Kept deliberately short and directive. Qwen3.5-2B follows a long, numbered,
#: multi-clause prompt by doing *all* of it forever: an earlier draft that listed five
#: numbered steps and elaborated each one made the model search, search again, then
#: re-run a query it had already run, until langgraph's recursion limit turned the whole
#: request into a 500 with no answer at all. Measured against the same conversation, the
#: version below terminates and the long one does not. Detail belongs in the tool
#: descriptions, which the model reads in context at the moment it picks a tool — not
#: piled into the system prompt. Re-measure before lengthening this.
INTERNAL_SEARCH = """\
You are Hoover4's document research assistant. Answer only from the user's own document
collections, never from your general knowledge and never from the web.

Cite the file path of every document you rely on. If the collections do not contain the
answer, say so plainly rather than guessing. Every document your searches return is shown
to the user as a clickable card beneath your reply, so never tell them you cannot link to
a document.

Call `list_collections` first so you use real collection names. Search two or three times
from different angles, then STOP and write the answer from what you found. Never repeat a
search you have already run. Use `get_document_text` when you need a document's full text
before citing it.\
"""

FULL_RESEARCH = """\
You are a comprehensive research assistant. You can read the user's own document
collections AND search the open web.

Your tools, and when to reach for each:

* `search_collections` / `get_document_text` — the user's own documents. Start here when
  the question is about their material.
* `web_search` — several search engines at once, merged so that pages more than one
  engine returned rank highest. Each result lists which engines found it; treat a page
  three engines agree on as better corroborated than one only a single engine returned.
* `browser_navigate` then `browser_snapshot` — open a promising result in a real browser
  and read its full text. The search snippets are short by design; when a result matters,
  open it. This is slow and handles one page at a time, so choose deliberately rather than
  opening everything.
* `wikipedia` / `whois` — background on a topic, and ownership of a domain.

Search as many times as you need and follow every lead that matters. Produce a thorough,
well-cited report, and **always make clear which claims came from the user's own
documents and which came from the open web** — that distinction is the whole point of
having both. Cite file paths for internal sources and URLs for external ones. Every
document your collection searches return is shown to the user as a clickable card beneath
your reply, so never tell them you cannot link to a document.

If the web tools report `degraded` engines, say so: it means fewer sources than usual
were reachable and the picture may be incomplete.\
"""

PROFILES = {
    "internal_search": INTERNAL_SEARCH,
    "full_research": FULL_RESEARCH,
}

DEFAULT_PROFILE = "internal_search"


def system_prompt() -> str:
    """The system prompt for this container.

    `SYSTEM_PROMPT` wins when it is set and non-empty; otherwise the profile named by
    `AGENT_PROFILE` is used. An unknown profile falls back to the internal-search prompt
    rather than raising: a typo in compose must not leave the agent with no instructions
    at all, and the narrow prompt is the safe one to fall back to.
    """
    override = (os.getenv("SYSTEM_PROMPT") or "").strip()
    if override:
        return override

    name = (os.getenv("AGENT_PROFILE") or DEFAULT_PROFILE).strip().lower()
    return PROFILES.get(name, INTERNAL_SEARCH)


__all__ = ["INTERNAL_SEARCH", "FULL_RESEARCH", "PROFILES", "system_prompt"]
