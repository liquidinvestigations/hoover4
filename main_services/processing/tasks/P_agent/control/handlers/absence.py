"""Verify named things and prepare a clarification note from indexed close forms."""
from __future__ import annotations

import asyncio
import difflib
import re

from tasks.P_agent.control.model import Action, freeze, plain

ABSENCE_OPTION = "None of these: report that the collections do not hold it"


async def check_names(names, context, services):
    """Return verified absence records. A partial lookup establishes no absence."""
    records = []
    for name in dict.fromkeys(names):
        if not name or len(name) > 150:
            continue
        lower = name.casefold()
        if lower in {c.casefold() for c in context.collections}:
            continue
        collection_named = re.search(r"(?:collection|dataset)\s+[\"']?" + re.escape(name)
                                     + r"\b|\b" + re.escape(name) + r"[\"']?\s+(?:collection|files|documents|dataset)",
                                     context.request, re.I)
        if collection_named:
            candidates = difflib.get_close_matches(lower, list(context.collections), n=4, cutoff=0.6)
            records.append({"name": name, "kind": "collection", "options": candidates})
            continue
        if not context.collections or "search_collections" not in context.callable_tools:
            continue
        scopes = sorted({c for f in context.results for c in f.args.get("collectionname", [])})
        scopes = scopes or list(context.collections)
        replies = await asyncio.gather(*(services.suggestions([name], kind, scopes)
                                         for kind in ("pages", "entities", "folders")))
        if any(reply.get("partial") for reply in replies):
            continue
        counts = [c for reply in replies for c in reply.get("word_counts", [])]
        # A multiword name can occur only when every indexed word occurs.
        words = {c["word"].casefold() for c in counts}
        missing = {word for word in words if not any(c.get("documents", 0) > 0
                   for c in counts if c.get("word", "").casefold() == word)}
        if not missing:
            continue
        candidates = {}
        for reply in replies:
            for group in reply.get("suggestions", []):
                word = group.get("word", "")
                if word.casefold() not in missing:
                    continue
                for candidate in group.get("candidates", []):
                    if not candidate.get("documents"):
                        continue
                    form = re.sub(r"\b" + re.escape(word) + r"\b", candidate["word"], name, flags=re.I)
                    key = (candidate["distance"], -candidate["documents"])
                    if form not in candidates or key < candidates[form]:
                        candidates[form] = key
        options = sorted(candidates, key=lambda c: (candidates[c], c))[:4]
        records.append({"name": name, "kind": "name", "options": options,
                        "word_counts": plain(counts)})
    return records


def note_action(records, context):
    """Ask through the agent's existing clarification tool, with at most six options."""
    if not records or "ask_user" not in context.callable_tools:
        return ()
    lines = []
    for record in records:
        choices = list(record["options"])
        if choices:
            choices.append(ABSENCE_OPTION)
        else:
            choices = [ABSENCE_OPTION]
        if "web" in context.capabilities:
            choices.append("Search the web for this name")
        lines.append(f"The selected collections have no indexed match for {record['name']!r}. "
                     f"Call ask_user now with these options: {choices!r}. "
                     "Wait for the person's choice before searching a suggested spelling. "
                     "A suggestion does not establish which name the person means.")
    return (Action("append_note", "absent-names", freeze({"text": "\n".join(lines)})),)
