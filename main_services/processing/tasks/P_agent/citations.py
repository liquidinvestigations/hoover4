"""The citation check of an answer, and the text of its repair note.

`reports.check_labels` compares the `[Dn]` labels of an answer with the successful
`cite_documents` results of the whole chat session. A label that no successful result gives
is unresolved. A label that results give for more than one document conflicts. A call that
failed gives no label, so a failed call does not satisfy the check, and a call that exists
does not stop it.

An answer needs a repair round (`needs_repair`) when it has an unresolved or a conflicting
label, or when it has no label and names a document or follows a document read. These
rules ask for citations. They do not show that the claims of the answer are supported.
The note of the round asks for the citations and the whole answer again. A reply with
no text keeps the earlier answer. A reply with invalid labels or raw call text keeps
that answer with a notice. A reply without labels shows its citation status.
Another invalid reply does not repeat an identical notice.

The note of a round is stored with its marker (`REPAIR_MARKER_KEY` in its usage), and
`is_citation_note` reads this marker. The policy coordinator (`control.coordinator`) runs this
check after each answer or question, counts the rounds of the turn from the stored notes, and
combines these findings with the other checks in one note. The evidence includes earlier
turns' tool reads, without their repair notes.
A web check compares every answer link with readable page evidence and names each unread link.
A stopped run and a run that ended at a limit get no round. The rules here are pure.
"""

from __future__ import annotations

import json
import re

#: The note of the repair round of an answer that names a document with no label.
CITATION_NOTE = (
    "Your answer names documents, but it has no citation handle, so the reader sees no "
    "document card. Call `cite_documents` now with each document that your answer names, "
    "quotes or relies on. Then write the whole answer again, with the handles that the "
    "successful calls returned."
)

#: The usage key and value of the note of the repair round.
REPAIR_MARKER_KEY = "repair_marker"
REPAIR_MARKER = "citation"

#: A citation handle as the answer writes it, for example `[D1]`.
HANDLE_PATTERN = re.compile(r"\[\s*[DW]\d+(?:\s*,\s*[DW]\d+)*\s*\]")
DOCUMENT_HANDLE_PATTERN = re.compile(r"\[D\d+\]")
PAGE_ZERO_PATTERN = re.compile(r"\bpage\s+0\b", re.IGNORECASE)

#: A file hash as the answer writes it.
HASH_PATTERN = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")

#: The shortest file name of a tool result that counts as a document name in an answer.
#: A shorter name, such as `12.`, also matches ordinary prose.
MIN_NAME_CHARS = 6

#: The shortest part of a file hash that counts as a document name in an answer.
MIN_HASH_CHARS = 12


def _result_documents(message) -> list[dict]:
    """The document references of one stored tool result."""
    from tasks.P_agent.trajectory import extract_doc_refs

    try:
        result = json.loads(message.content or "")
    except ValueError:
        return []
    return extract_doc_refs(message.tool_name or "", result)


def names_documents(answer: str, messages) -> bool:
    """Whether an answer names a document: a `[Dn]` handle, a file hash, or the file hash,
    path or file name of a document that a tool result of the thread returned."""
    if DOCUMENT_HANDLE_PATTERN.search(answer) or HASH_PATTERN.search(answer):
        return True
    for message in messages:
        if message.role != "tool":
            continue
        for ref in _result_documents(message):
            file_hash = ref.get("file_hash") or ""
            if len(file_hash) >= MIN_HASH_CHARS and file_hash[:MIN_HASH_CHARS] in answer:
                return True
            path = (ref.get("path") or "").strip()
            name = path.rstrip("/").rsplit("/", 1)[-1]
            if len(path) >= MIN_NAME_CHARS and path in answer:
                return True
            if len(name) >= MIN_NAME_CHARS and name in answer:
                return True
    return False


def read_documents(messages) -> bool:
    """Whether a content reader gives successful document-read evidence."""
    for message in messages:
        if message.role != "tool":
            continue
        if message.usage.get("status") == "error":
            continue
        if any(e.get("kind") == "document_read" and e.get("status") in ("ok", "partial")
               and (e.get("reference") or {}).get("file_hash")
               for e in (message.usage.get("evidence") or []) if isinstance(e, dict)):
            return True
    return False


def is_citation_note(message) -> bool:
    """Whether a thread message is the note of the repair round."""
    return message.role == "human" and (
        message.usage.get(REPAIR_MARKER_KEY) == REPAIR_MARKER
)


def repair_note(check: dict) -> str:
    """The note of a repair round for the citation check `check`."""
    problems = []
    if check.get("page_zero"):
        problems.append("The answer names page 0. Use the 1-based page from the verified cite_documents result.")
    if check.get("web_missing") or (check.get("web_used") and check.get("unsupported_paragraphs")):
        problems.append('Call `cite_pages` before answering. Use one page per call: {"url":"COPY_READ_URL","terms":["COPY_EXACT_SOURCE_WORDS"]}. Copy a short phrase from read_page text. A title, paraphrase, or guessed wording can fail. If the call returns an error, correct it and retry. Only returned handles are valid.')
    if check.get("web_missing") and check.get("read_page_urls"):
        problems.append("Already read page URLs: " + ", ".join(check["read_page_urls"]) + ". Cite the supporting pages from this list.")
    for url in check.get("web_unread") or []:
        problems.append(f"The answer links an unread page: {url}. Call `read_page` for that address before you use its claims, or remove those claims.")
    for url in check.get("web_undiscovered") or []:
        problems.append(f"No successful search found this page: {url}. Find it with `web_search` before using it as a source.")
    if check.get("web_unmarked"):
        problems.append("Replace bare source URLs with handles returned by `cite_pages`. Copy exact supporting text into its terms field.")
    for paragraph in (check.get("unsupported_paragraphs") or [])[:3]:
        location = (f"List item {paragraph['item']} in paragraph {paragraph['number']}"
                    if "item" in paragraph else f"Paragraph {paragraph['number']}")
        problems.append(f"{location} has a name or number without a source: {paragraph['text']} Add its citation or remove the claim.")
    if check.get("unsupported_paragraphs"):
        problems.append("Give every factual paragraph and list item a verified source handle, including items beyond these examples. Retry each failed citation entry before answering.")
        if check.get("web_used") or check.get("web_missing"):
            problems.append("After another read_page call, call cite_pages again.")
        problems.append("Remove claims that have no verified source.")
    if check.get("unresolved"):
        problems.append("No successful citation result gives "
                        + ", ".join(check["unresolved"]) + ".")
    if check.get("conflicting"):
        problems.append("Results give " + ", ".join(check["conflicting"])
                        + " for more than one document.")
    if check.get("unsupported_paragraphs") and (check.get("documents_read") or
            (not check.get("web_used") and not check.get("web_missing"))):
        problems.append('Call cite_documents with {"citations":[{"collection":"COPY_COLLECTION","file_hash":"COPY_HASH","quote":"COPY_EXACT_SOURCE_SENTENCE","why":"What it supports"}]}. The quote field is required. Find is an optional part of quote.')
    if not problems:
        return CITATION_NOTE
    return " ".join(problems) + " Write the complete answer again with the sources that support its claims."


URL_PATTERN = re.compile(r"https?://[^\s<>\]]+")
NAME_PATTERN = re.compile(r"\b[^\W\d_][^\W\d_'-]{2,}\b")
OPENING_WORDS = frozenset({"The", "This", "There", "These", "Those", "However", "It", "They", "Their", "For", "From", "With", "Not", "None", "Some"})
LIST_ITEM_PATTERN = re.compile(r"^([ \t]*)(?:[-+*]|\d+[.)])\s+(.+)")


def page_address(url: str) -> str:
    """Compare page addresses without a fragment or trailing sentence punctuation."""
    url = url.rstrip(".,;:!?")
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    return url.split("#", 1)[0]


def unsupported_paragraphs(answer: str) -> list[dict]:
    """Identify uncited names or numbers in each paragraph or list item."""
    findings = []
    for number, paragraph in enumerate(re.split(r"\n\s*\n", answer), 1):
        parts = re.split(r"\n(?=[ \t]*(?:[-+*]|\d+[.)])\s+)", paragraph)
        for position, part in enumerate(parts):
            item = LIST_ITEM_PATTERN.match(part)
            text = part[item.start(2):] if item else part
            if len(parts) > 1 and not item and all(
                    line.lstrip().startswith("#") for line in text.splitlines() if line.strip()):
                continue
            following = LIST_ITEM_PATTERN.match(parts[position + 1]) if position + 1 < len(parts) else None
            if (item and following and len(following[1]) > len(item[1])
                    and text.rstrip(" *_`").endswith(":")):
                continue
            if HANDLE_PATTERN.search(text) or URL_PATTERN.search(text):
                continue
            names = {word for word in NAME_PATTERN.findall(text) if word[0].isupper()} - OPENING_WORDS
            if names or re.search(r"\b\d+(?:[.,]\d+)*\b", text):
                finding = {"number": number, "text": part[:500]}
                if item:
                    finding["item"] = position + (0 if not LIST_ITEM_PATTERN.match(parts[0]) else 1)
                findings.append(finding)
    return findings


def web_evidence(messages) -> tuple[bool, list[str]]:
    """Return web use and the addresses of pages that supplied readable evidence."""
    used, urls = False, []
    for message in messages:
        if message.role != "tool":
            continue
        if message.tool_name in ("web_search", "read_page", "cite_pages"):
            used = True
        if message.usage.get("status") == "error":
            continue
        for entry in message.usage.get("evidence") or []:
            if entry.get("kind") == "document_read" and entry.get("status") in ("ok", "partial"):
                url = (entry.get("reference") or {}).get("url")
                if url:
                    used = True
                    urls.append(url)
    return used, list(dict.fromkeys(urls))


def web_discoveries(messages) -> set[str]:
    """Return page URLs from successful stored search results."""
    urls = set()
    for message in messages:
        if (message.role != "tool" or message.tool_name != "web_search"
                or message.usage.get("status") == "error"):
            continue
        for entry in message.usage.get("evidence") or []:
            if entry.get("kind") == "discovery" and entry.get("status") == "ok":
                url = (entry.get("reference") or {}).get("url")
                if url:
                    urls.add(page_address(url))
        try:
            parsed = json.loads(message.content or "{}")
        except ValueError:
            continue
        if not isinstance(parsed, dict) or parsed.get("success") is False or parsed.get("error"):
            continue
        rows = parsed.get("items", parsed.get("results", []))
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and isinstance(row.get("url"), str):
                urls.add(page_address(row["url"]))
    return urls


def needs_repair(answer: str, messages, session_entries) -> tuple[bool, dict]:
    """Whether an answer gets the repair round, and its citation check.

    `messages` is the thread, and `session_entries` the citation evidence of the session.
    The policy coordinator counts the rounds of a turn (`control.coordinator`), so a thread
    that holds a note is checked like any other.
    """
    from tasks.P_agent import reports

    check = reports.check_labels(answer, reports.label_bindings(session_entries),
                                 session_entries)
    check["page_zero"] = bool(PAGE_ZERO_PATTERN.search(answer))
    documents_read = read_documents(messages)
    check["documents_read"] = documents_read
    web_used, urls = web_evidence(messages)
    read_urls = {page_address(url) for url in urls}
    answer_urls = list(dict.fromkeys(page_address(url) for url in URL_PATTERN.findall(answer)))
    web_refs = [(entry.get("reference") or {}) for entry in session_entries
                if entry.get("kind") == "citation" and entry.get("status") == "ok"
                and (entry.get("reference") or {}).get("handle") in check["labels"]
                and (entry.get("reference") or {}).get("url")]
    cited_urls = [page_address(ref["url"]) for ref in web_refs]
    source_urls = list(dict.fromkeys(answer_urls + cited_urls))
    web_used = web_used or bool(web_refs) or bool(answer_urls)
    check["web_used"] = web_used
    check["web_unread"] = [url for url in source_urls if url not in read_urls] if web_used else []
    discovered = web_discoveries(messages)
    check["web_undiscovered"] = [url for url in source_urls if url not in discovered] if web_used else []
    check["web_unmarked"] = answer_urls
    check["web_missing"] = web_used and (not web_refs or bool(check["web_unread"])
                                         or bool(check["web_undiscovered"]) or bool(answer_urls))
    check["unsupported_paragraphs"] = unsupported_paragraphs(answer) if documents_read or web_used else []
    check["read_page_urls"] = list(dict.fromkeys(urls))[:12]
    if not answer.strip():
        return False, check
    if (check["unresolved"] or check["conflicting"] or check["page_zero"]
            or check["web_missing"] or check["unsupported_paragraphs"]):
        return True, check
    return (not any(label.startswith("[D") for label in check["labels"]) and
            (names_documents(answer, messages) or documents_read)), check


def answer_metadata(answer: str, messages, session_entries, internet_tools: bool) -> dict:
    """Return citation status and the available tool scope for an answer."""
    _, check = needs_repair(answer, messages, session_entries)
    if check["unresolved"] or check["conflicting"] or check["page_zero"]:
        status = "invalid"
    elif check["web_missing"] or check["unsupported_paragraphs"]:
        status = "missing"
    elif check["labels"] or URL_PATTERN.search(answer):
        status = "cited"
    elif read_documents(messages) or any(is_citation_note(m) for m in messages):
        status = "missing"
    else:
        status = "none"
    return {"citation_status": status,
            "tool_scope": "documents_and_web" if internet_tools else "documents_only"}


def repair_reply_problem(answer: str, session_entries) -> str:
    """The structural problem in a citation reply, or empty when it can be shown."""
    from tasks.P_agent import reports, thread_facts
    from tasks.P_agent.control.handlers.answer_review import unissued_markers

    if (thread_facts.RAW_CITATION_CALL.search(answer)
            or "<|tool_call>" in answer or "<|\"|>" in answer):
        return "raw_call"
    check = reports.check_labels(answer, reports.label_bindings(session_entries),
                                 session_entries)
    if check["unresolved"] or unissued_markers(answer):
        return "unresolved_label"
    if check["conflicting"]:
        return "conflicting_label"
    if PAGE_ZERO_PATTERN.search(answer):
        return "page_zero"
    return ""


__all__ = [
    "CITATION_NOTE", "answer_metadata",
    "REPAIR_MARKER",
    "REPAIR_MARKER_KEY", "is_citation_note", "names_documents",
    "needs_repair", "read_documents", "repair_note", "repair_reply_problem",
]
