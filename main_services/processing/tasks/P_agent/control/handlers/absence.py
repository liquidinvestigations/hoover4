"""Verify named things and prepare a note with their indexed close forms."""
from __future__ import annotations

import asyncio
import difflib
import re

from tasks.P_agent.control.model import Action, freeze, plain


def _collection_named(name, request):
    return re.search(r"\b(?:collection|dataset)\s+[\"']?" + re.escape(name)
                     + r"\b|\b" + re.escape(name) + r"[\"']?\s+(?:collection|files|documents|dataset)",
                     request, re.I)


async def check_names(names, context, services):
    """Return verified absence records. A partial or failed lookup establishes no absence.

    The `options` of a name record are `(form, documents)` pairs, closest form first."""
    records = []
    scopes = set()
    for fact in context.results:
        values = fact.args.get("collection", [])
        values = [values] if isinstance(values, str) else values or []
        scopes.update(value for value in values if value in context.collections)
    selected = [name for name in context.collections if _collection_named(name, context.request)]
    scopes = sorted(scopes) or selected or list(context.collections)
    for name in dict.fromkeys(names):
        if not name or len(name) > 150:
            continue
        lower = name.casefold()
        if lower in {c.casefold() for c in context.collections}:
            continue
        if _collection_named(name, context.request):
            candidates = difflib.get_close_matches(lower, list(context.collections), n=4, cutoff=0.6)
            records.append({"name": name, "kind": "collection", "options": candidates})
            continue
        if not context.collections or "search_collections" not in context.callable_tools:
            continue
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
        options = [(form, -candidates[form][1])
                   for form in sorted(candidates, key=lambda c: (candidates[c], c))[:4]]
        records.append({"name": name, "kind": "name", "options": options,
                        "word_counts": plain(counts)})
    return records


def note_action(records, context):
    """A note for each name that the selected collections do not hold, with the indexed
    close forms and their document counts."""
    if not records:
        return ()
    lines = []
    for record in records:
        name = record["name"]
        if record["kind"] == "collection":
            lines.append(f"No permitted collection is named {name!r}. "
                         f"The permitted collections are {', '.join(context.collections)}.")
            continue
        forms = ", ".join(f"{form!r} ({count} documents)" for form, count in record["options"])
        line = f"The selected collections have no indexed match for {name!r}."
        if forms:
            line += (f" Indexed close forms: {forms}. Do not use a close form as the requested "
                     "name. When you search one, name it in the answer as a different spelling.")
        if "web" in context.capabilities:
            line += " The web tools of this turn can search the name."
        lines.append(line)
    return (Action("append_note", "absent-names", freeze({"text": "\n".join(lines)})),)
