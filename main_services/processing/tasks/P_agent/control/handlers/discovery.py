"""The discovery note L4.

`tool_batch_completed` (L4): a model batch whose only `read_page` call reads one address,
while two or more result addresses of the turn's searches are still unread. The note asks
for one `read_page` call with two or more addresses.

The note is a proposal. The coordinator merges the notes of one event into one note, and a
`turn` frequency in the definition keeps the rule to one note in a turn.
"""

from __future__ import annotations

from typing import Any, Mapping

from tasks.P_agent.control import facts as F
from tasks.P_agent.control.handlers_common import read_urls
from tasks.P_agent.control.model import API_VERSION, Action, CheckResult, PolicyResult, freeze
from tasks.P_agent.notes import note

#: The English note. A run reads it in its own language (`tasks.P_agent.notes`).
L4 = note("en", "note-discovery-l4")


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


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        if not isinstance(parameters.get("min_unread", 2), int):
            raise ValueError("min_unread must be an integer")

    async def evaluate(self, event, context, parameters, services) -> PolicyResult:
        if event.hook == "tool_batch_completed":
            return self._l4(event, context, parameters)
        return PolicyResult()

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
            actions=(Action("append_note", "L4", freeze({"text": note(context.language, "note-discovery-l4")})),))
