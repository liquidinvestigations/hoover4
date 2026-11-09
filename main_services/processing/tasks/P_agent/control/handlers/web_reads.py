"""R1: automatic reads of web search results after a model batch.

The candidates are the result addresses of the batch's successful `web_search` results,
merged by page address and kept at their best rank. Addresses with a successful read, and
addresses that a `read_page` call of the turn requested, are left out. The order is the
search rank, then the order of the searches in the batch (`mode` `rank`).

The handler proposes one `read_page` call with at most `max_urls` addresses, the maximum of
one call. It runs after a model batch only, so a policy batch never starts another one.
"""

from __future__ import annotations

from typing import Any, Mapping

from tasks.P_agent.control import facts as F
from tasks.P_agent.control.handlers_common import read_urls
from tasks.P_agent.control.model import API_VERSION, Action, CheckResult, PolicyResult, freeze


def candidates(context, batch) -> list[dict]:
    """The unread result addresses of the batch, each once, at its best rank."""
    read = {F.page_address(k) for k in F.satisfactory_reads(context.results)}
    requested = {F.page_address(u) for f in context.results if f.name == "read_page"
                 for u in read_urls(f)}
    best: dict[str, dict] = {}
    for order, fact in enumerate(f for f in batch if f.name == "web_search" and f.status == "ok"):
        for rank, url in enumerate(fact.urls):
            address = F.page_address(url)
            if address in read or address in requested:
                continue
            key = (rank, order)
            if address not in best or key < best[address]["key"]:
                best[address] = {"url": url, "address": address, "key": key,
                                 "idx": fact.idx, "rank": rank}
    return sorted(best.values(), key=lambda c: c["key"])


class Handler:
    api_version = API_VERSION

    def validate(self, parameters: Mapping[str, Any]) -> None:
        if parameters.get("mode", "rank") != "rank":
            raise ValueError("mode must be rank")
        max_urls = parameters.get("max_urls", 6)
        if not isinstance(max_urls, int) or not 1 <= max_urls <= 6:
            raise ValueError("max_urls must be an integer from 1 to 6")
        if not isinstance(parameters.get("pool", 10), int):
            raise ValueError("pool must be an integer")

    async def evaluate(self, event, context, parameters, services) -> PolicyResult:
        if event.origin != "model" or "read_page" not in context.callable_tools:
            return PolicyResult()
        pool = candidates(context, list(context.batch))[:int(parameters.get("pool", 10))]
        if not pool:
            return PolicyResult()
        chosen = pool[:int(parameters.get("max_urls", 6))]
        checks = [CheckResult(event.id, c["address"], "pass", None, (str(c["idx"]),),
                              "rank", freeze({"rank": c["rank"]})) for c in chosen]
        urls = [c["url"] for c in chosen]
        return PolicyResult(
            checks=tuple(checks),
            actions=(Action("call_tools", "read_page", freeze({
                "calls": [{"name": "read_page", "args": {"urls": urls}}],
                "mode": "rank"})),))
