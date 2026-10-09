"""R1: automatic reads of web search results after a model batch.

The candidates are the result addresses of the batch's successful `web_search` results,
merged by page address and kept at their best rank. Addresses with a successful read, and
addresses that a `read_page` call of the turn requested, are left out. `mode` selects the
order:

* `rank`: the search rank, then the order of the searches in the batch.
* `classifier`: one systemone `noul` question for each candidate, then the full-precision
  score, highest first, with the rank order for equal scores. A failed request reads nothing.

The handler proposes one `read_page` call with at most `max_urls` addresses, the maximum of
one call. It runs after a model batch only, so a policy batch never starts another one.
"""

from __future__ import annotations

from typing import Any, Mapping

from tasks.P_agent.control import facts as F
from tasks.P_agent.control.handlers_common import read_urls, web_results
from tasks.P_agent.control.model import (
    API_VERSION, Action, CheckResult, PolicyResult, freeze, noul,
)

INSTRUCTIONS = ("A research agent searched the web for the request below. `results` are the "
                "search results, each with title, URL and snippet.")
QUESTION = ("Should the agent read result {rid}, because its page likely states facts that "
            "answer the request?")


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
        if parameters.get("mode", "rank") not in ("rank", "classifier"):
            raise ValueError("mode must be rank or classifier")
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
        mode = parameters.get("mode", "rank")
        max_urls = int(parameters.get("max_urls", 6))
        checks = []
        if mode == "classifier":
            details = web_results(services, pool)
            state = {"request": context.request[:1500],
                     "results": {f"r{k + 1}": details[k] for k in range(len(pool))}}
            questions = {f"r{k + 1}_read=": {"type": "noul",
                                            "instructions": QUESTION.format(rid=f"r{k + 1}")}
                         for k in range(len(pool))}
            result = await services.ask(state, questions, INSTRUCTIONS)
            scored = []
            for k, cand in enumerate(pool):
                score = noul(result, f"r{k + 1}_read=")
                checks.append(CheckResult(event.id, cand["address"],
                                          "pass" if score is not None else "unknown", score,
                                          (str(cand["idx"]),), result.status,
                                          freeze({"rank": cand["rank"]})))
                if score is not None:
                    scored.append((cand, score))
            if result.status != "ok" or not scored:
                return PolicyResult(checks=tuple(checks))
            chosen = [c for c, _ in sorted(scored, key=lambda cs: (-cs[1], cs[0]["key"]))][:max_urls]
        else:
            chosen = pool[:max_urls]
            checks = [CheckResult(event.id, c["address"], "pass", None, (str(c["idx"]),),
                                  "rank", freeze({"rank": c["rank"]})) for c in chosen]
        urls = [c["url"] for c in chosen]
        return PolicyResult(
            checks=tuple(checks),
            actions=(Action("call_tools", "read_page", freeze({
                "calls": [{"name": "read_page", "args": {"urls": urls}}],
                "mode": mode})),))
