"""The citation handles of a workspace file, and their check against the session citations.

The parse follows the transcript renderer (`website/frontend/.../markdown_text.rs`,
`parse_inline` and `as_handles`), so a handle that the check accepts is a handle that the
page shows as a citation.

* A handle is `[D1]` or `[W2]`, or a list such as `[D1, W2]`.
* Text in a fenced code block or in an inline code span is literal.
* A bracket written after a backslash, such as `\\[D9]`, is literal.
* A bracketed text that a parenthesis follows is a Markdown link, not a handle.
* Other bracketed words stay text.

`check` resolves each handle against the successful citation results of the session
(`tasks.P_agent.reports.session_citation_entries`). A handle resolves when one source holds
it and that citation has a verified quote. The check does not show that a claim follows from
its source.
"""

from __future__ import annotations

import re
from typing import Iterable

FENCE = re.compile(r"^\s*(```|~~~)")
HANDLE_VALUE = re.compile(r"[DW]\d+")


def _as_handles(inner: str) -> list[str] | None:
    values = [value.strip() for value in inner.split(",")]
    if not values or not all(HANDLE_VALUE.fullmatch(value) for value in values):
        return None
    return [f"[{value}]" for value in values]


def handles(text: str) -> list[tuple[str, int]]:
    """Each citation handle of `text` with its line number from 1, in text order."""
    out: list[tuple[str, int]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        i = 0
        while i < len(line):
            c = line[i]
            if c == "\\" and i + 1 < len(line) and line[i + 1] in "[]":
                i += 2
                continue
            if c == "`":
                end = line.find("`", i + 1)
                if end != -1:
                    i = end + 1
                    continue
            if c == "[":
                close = line.find("]", i + 1)
                if close != -1 and not line.startswith("(", close + 1):
                    found = _as_handles(line[i + 1:close])
                    if found is not None:
                        out.extend((handle, number) for handle in found)
                        i = close + 1
                        continue
            i += 1
    return out


def _source(reference: dict) -> str:
    if reference.get("url") and reference.get("version"):
        return f"web:{reference['url']}:{reference['version']}"
    return str(reference.get("file_hash") or "")[:16]


def check(name: str, text: str, entries: Iterable[dict]) -> tuple[list[dict], list[dict]]:
    """The findings and the resolved citations of the handles of a file.

    A finding names the file, the line, the handle and the action that corrects it. A
    resolved citation holds the handle and the reference of its successful citation result.
    """
    found: dict[str, list[dict]] = {}
    for entry in entries:
        reference = entry.get("reference") or {}
        handle = str(reference.get("handle") or "")
        if entry.get("kind") == "citation" and entry.get("status") == "ok" and handle:
            found.setdefault(handle, []).append(reference)
    findings: list[dict] = []
    resolved: list[dict] = []
    seen: set[str] = set()
    for handle, line in handles(text):
        if handle in seen:
            continue
        seen.add(handle)
        references = found.get(handle) or []
        sources = {_source(reference) for reference in references} - {""}
        web = handle.startswith("[W")
        tool = "cite_pages" if web else "cite_documents"
        if not references:
            findings.append({"file": name, "line": line, "handle": handle,
                             "action": f"No successful {tool} call of this conversation gave "
                                       f"{handle}. Cite the source with {tool} and use the "
                                       "handle that it returns, or write the bracket as "
                                       f"\\{handle} when it is text of a source."})
            continue
        if len(sources) > 1:
            findings.append({"file": name, "line": line, "handle": handle,
                             "action": f"{handle} names more than one source in this "
                                       f"conversation. Cite the source again with {tool} "
                                       "and use the new handle."})
            continue
        verified = [r for r in references if r.get("quote_verified") is True]
        if not verified:
            findings.append({"file": name, "line": line, "handle": handle,
                             "action": f"The quote of {handle} was not found in its source. "
                                       f"Call {tool} again with an exact quote from the "
                                       "source, or remove the claim that depends on it."})
            continue
        reference = verified[-1]
        keep = ("handle", "collectionname", "collection_dataset", "file_hash", "path",
                "page_id", "quote", "url", "final_url", "version", "artifact_id")
        resolved.append({key: reference[key] for key in keep if reference.get(key) not in (None, "")})
    return findings, resolved


__all__ = ["check", "handles"]
