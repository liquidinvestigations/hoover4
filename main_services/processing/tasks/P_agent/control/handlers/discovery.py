"""The discovery notes L2, L3 and L4.

`answer_drafted` (L3) checks answers in turns that need documents or web sources.
It asks for a read when no read or reused verified citation supports the draft.
The note asks for reads before the answer is written again. A documents-only turn gets the
document wording, and a turn with web sources gets the `urls` wording. A turn whose
preparation gave no source class answers as before. L2 adds one sentence to the L3 note when
the top result addresses of the last two web searches all occurred in earlier searches.

`tool_batch_completed` (L4): a model batch whose only `read_page` call reads one address,
while two or more result addresses of the turn's searches are still unread. The note asks
for one `read_page` call with two or more addresses.

Each note is a proposal. The coordinator merges the notes of one event into one note, and a
`turn` frequency in the definition keeps each rule to one note in a turn.
"""

from __future__ import annotations

from typing import Any, Mapping

from tasks.P_agent.control import facts as F
from tasks.P_agent.control.handlers_common import read_urls
from tasks.P_agent.control.model import API_VERSION, Action, CheckResult, PolicyResult, freeze

L3_WEB = ("You answered before reading any source page. Call read_page once with the URLs of "
          "the pages that support your items, up to 6 in its `urls` list. Then write the answer "
          "again with the sources that support it.")
L3_DOCUMENTS = ("You answered before reading any document. Read the documents that support "
                "your items with read_documents, several file hashes in one call. Then write the "
                "answer again with the sources that support it.")
L2 = ("The last two searches found no new source. Read the best result pages now: put up to 6 "
      "of their URLs in one read_page call, in its `urls` list. Search again only with a "
      "different question.")
L4 = ("Read the result pages that may answer the request now: put up to 6 of their URLs in one "
      "read_page call, in its `urls` list. One call reads them all at the same time.")

DEFAULT_READ_TOOLS = ("read_page", "read_documents", "read_more", "table_page", "table_cell",
                      "doc_email", "doc_search_text", "pdf_search")


def unread_results(results, top: int = 10) -> list[str]:
    """Result addresses of successful web searches that no read covered, in rank order."""
    read = {F.page_address(k) for k in F.satisfactory_reads(results)}
    requested = {F.page_address(u) for f in results if f.name == "read_page" for u in read_urls(f)}
    out = []
    for fact in results:
        if fact.name != "web_search" or fact.status != "ok":
            continue
        for url in fact.urls[:top]:
            address = F.page_address(url)
            if address not in read and address not in requested and address not in out:
                out.append(address)
    return out


def repeated_searches(results, top: int = 3) -> list[dict]:
    """The evidence of L2: the last two successful web searches whose top addresses all
    occurred in earlier searches, or an empty list."""
    searches = [f for f in results if f.name == "web_search" and f.status == "ok" and f.urls]
    if len(searches) < 3:
        return []
    evidence = []
    for position in (len(searches) - 2, len(searches) - 1):
        seen = {F.page_address(u) for f in searches[:position] for u in f.urls}
        head = [F.page_address(u) for u in searches[position].urls[:top]]
        if not head or not all(u in seen for u in head):
            return []
        evidence.append({"call_id": searches[position].call_id, "top": head})
    return evidence


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        requires = parameters.get("requires_reads", ["documents", "web", "both"])
        if not isinstance(requires, (list, tuple)):
            raise ValueError("requires_reads must be a list of source classes")
        if not isinstance(parameters.get("min_unread", 2), int):
            raise ValueError("min_unread must be an integer")

    async def evaluate(self, event, context, parameters, services) -> PolicyResult:
        if event.hook == "answer_drafted":
            return self._l3(event, context, parameters)
        if event.hook == "tool_batch_completed":
            return self._l4(event, context, parameters)
        return PolicyResult()

    def _l3(self, event, context, parameters) -> PolicyResult:
        if event.draft_kind != "answer":
            return PolicyResult(checks=(CheckResult(event.id, "L3", "skipped", None, (),
                                                    "a question to the person needs no read"),))
        sources = ((context.turn.get("preparation") or {}).get("sources") or {}).get("choice")
        requires = tuple(parameters.get("requires_reads", ["documents", "web", "both"]))
        if sources not in requires:
            return PolicyResult(checks=(CheckResult(event.id, "L3", "skipped", None, (),
                                                    f"source class {sources!r}"),))
        if F.justified_absence(context) or (sources in ("web", "both") and "web" not in context.capabilities):
            return PolicyResult(checks=(CheckResult(event.id, "L3", "skipped", None, (),
                                                    "the answer states a verified absence or an unavailable source"),))
        read_tools = set(parameters.get("read_tools") or DEFAULT_READ_TOOLS)
        reads = F.satisfactory_reads(context.results)
        other = [f.call_id for f in context.results
                 if f.name in read_tools and f.status == "ok" and f.name != "read_page"
                 and not f.reads]
        prior = [p["handle"] for p in context.turn.get("passages") or []
                 if p.get("quotes") and p.get("handle") and p["handle"] in context.draft]
        if reads or other or prior:
            return PolicyResult(checks=(CheckResult(event.id, "L3", "pass", None,
                                                    tuple(reads[:6] or other[:6] or prior[:6]), "a read exists"),))
        web = "web" in context.capabilities and sources in ("web", "both") and "read_page" in context.callable_tools
        text = L3_WEB if web else L3_DOCUMENTS
        evidence = repeated_searches(context.results)
        if evidence and web:
            text = L2 + " " + text
        return PolicyResult(
            checks=(CheckResult(event.id, "L3", "defect", None, (), "an answer before any read",
                                freeze({"l2": evidence})),),
            actions=(Action("append_note", "L3", freeze({"text": text, "discovery": True,
                                                          "l2": bool(evidence and web)})),))

    def _l4(self, event, context, parameters) -> PolicyResult:
        if event.origin != "model" or "read_page" not in context.callable_tools:
            return PolicyResult()
        reads = [f for f in context.batch if f.name == "read_page"]
        if len(reads) != 1 or len(read_urls(reads[0])) != 1:
            return PolicyResult()
        unread = unread_results(context.results)
        if len(unread) < int(parameters.get("min_unread", 2)):
            return PolicyResult()
        return PolicyResult(
            checks=(CheckResult(event.id, "L4", "defect", None, tuple(unread[:6]),
                                f"one page read while {len(unread)} results are unread"),),
            actions=(Action("append_note", "L4", freeze({"text": L4})),))
