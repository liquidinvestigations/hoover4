"""Keep minority-source results beyond the previous candidate limit."""

import asyncio

from metasearch_server import pipeline, sources as sources_mod
from metasearch_server.engines import SearchResult


def test_minority_source_survives_more_than_sixty_web_candidates(monkeypatch):
    rows = [SearchResult(f"t{i}", f"https://{i}.example") for i in range(70)]
    rows.append(SearchResult("reference", "https://reference.example", kind="reference"))
    async def fetch_all(query, names, **kwargs):
        return {"ddg": rows}, {"ddg": 1.0}, [], {}, {"ddg": "direct"}
    monkeypatch.setattr(sources_mod, "fetch_all", fetch_all)
    monkeypatch.setattr(sources_mod, "resolve_sources", lambda _: (["ddg"], []))
    outcome = asyncio.run(pipeline.run_search(["q"], max_results=5))
    assert outcome.total_after_dedupe == 71
    assert "https://reference.example" in [r.result.url for r in outcome.ranked]
    assert pipeline.detail_document(outcome)["source_routes"] == {"ddg": "direct"}
