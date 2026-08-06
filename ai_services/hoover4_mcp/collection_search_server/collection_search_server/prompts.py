"""Canonical prompt text for the collection-search tools.

This lives in Python rather than as a multi-paragraph default inside a compose YAML
because there are two readers and they need the same words:

* :data:`SERVER_INSTRUCTIONS` goes into the FastMCP ``instructions`` string, which is
  what the model actually sees at tool-discovery time — before it has written a single
  query, and regardless of which agent is calling.
* :data:`AGENT_SYSTEM_PROMPT` is the system prompt for the internal-search agent.

The compose file keeps ``SERVER_INSTRUCTIONS`` / ``SYSTEM_PROMPT`` env vars as thin
overrides for experiments, but the text checked in here is the one that ships.

Everything the syntax section claims was verified against the live `testdata_1_pages`
shard, not taken from Manticore's documentation — several documented spellings are a
hard 500 on this deployment. See `ai_services/README.md` for the full battery.
"""

from __future__ import annotations

#: The one thing that is deployment-specific and most often got wrong: there is exactly
#: one full-text field. `@title`, `@path`, `@filename` and friends are 500s, not misses.
MATCH_SYNTAX = """\
Search syntax for `search_collections`

The query is a Manticore full-text expression. Plain words work and are the right
default: several descriptive words beat one keyword. These operators are available when
you need them:

  water testing          both words must appear (words are ANDed)
  water | sewage         either word
  water -draft           has "water", excludes "draft" (needs a positive word too)
  "public water supply"  exact phrase, in this order
  "public water"~5       the words within 5 positions of each other
  "one two three"/2      any 2 of the 3 words
  water NEAR/3 testing   within 3 words, either order
  water SENTENCE testing in the same sentence (also PARAGRAPH)
  water MAYBE sewage     "water", ranking pages that also mention sewage higher
  (water | sewage) plant grouping
  water^3 testing        boost "water" three-fold in the ranking
  =testing               that exact word form, no stemming
  ^Dear                  the field must start with this word

Wildcards work and are how you search fuzzily:

  contract*              contract, contracts, contractual, contractor
  *ollution*             pollution, and anything else containing "ollution"

Use them when you are unsure of a word's ending or spelling — but they are broad and
cost more to run, so prefer a real word when you know it.

Two rules specific to this deployment:

  * `page_text` is the ONLY searchable field. `@page_text water` is valid; `@title`,
    `@filename`, `@path` and anything else do not exist and will fail. To narrow by
    dataset, file type or path, do not put it in the query — read the hits and filter.
  * A bare `@` in ordinary prose is read as a field prefix. Write `who paid acme`, not
    `who paid @acme`.

If a search returns an error, the `error` field says what was wrong with the query —
read it and retry with corrected syntax rather than giving up on the search.\
"""

#: Appended to both the server instructions and the agent prompt: the behaviour that
#: made the difference between a one-shot answer and a researched one.
#:
#: The stopping rule at the end is not padding. Told only to "search several times from
#: different angles", the 2B model searched forever — it found the right document on its
#: first query, ran two good follow-ups, then re-ran a query it had already run, and
#: exhausted the agent's recursion budget without ever writing an answer. A small model
#: needs to be told when it is finished as explicitly as it is told to keep looking.
SEARCH_STRATEGY = """\
Search two or three times, from different angles, before you answer. One query is often
not enough: try the specific phrase you expect to appear in the document, then a broader
set of words, then a wildcard or a synonym if the first two came back thin. A phrase
search is the right tool for a name, a title or a quoted string. Read a promising hit in
full with `get_document_text` before you cite it, and use `list_document_entities` to
find names worth searching for next.

Then STOP and write the answer. Specifically:

* Once your searches have turned up documents that answer the question, stop searching
  and answer from them. Do not keep looking for more.
* Never repeat a search you have already run — the result will be identical.
* If two or three different searches all come back empty, the collections do not contain
  the answer. Say so. Do not keep rephrasing.\
"""

SERVER_INSTRUCTIONS = f"""\
Search the user's own document collections in Hoover4.

Call `list_collections` first so you use real collection names, then `search_collections`
to find passages, then `get_document_text` to read a document in full.

{MATCH_SYNTAX}

{SEARCH_STRATEGY}\
"""

AGENT_SYSTEM_PROMPT = f"""\
You are Hoover4's document research assistant. Answer only from the user's document
collections — never from your own knowledge of the world.

Call `list_collections` first, then `search_collections`. Always cite the file path or
file_hash of every document you rely on. If the collections do not contain the answer,
say so plainly instead of guessing.

{SEARCH_STRATEGY}

{MATCH_SYNTAX}\
"""

__all__ = [
    "MATCH_SYNTAX",
    "SEARCH_STRATEGY",
    "SERVER_INSTRUCTIONS",
    "AGENT_SYSTEM_PROMPT",
]
