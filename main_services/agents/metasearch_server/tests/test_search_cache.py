"""Verify provider dispatch counts across saved batches and chats."""

import asyncio

from agent_common.fusion import SearchResult
from metasearch_server import search_cache, sources


def test_exact_queries_reuse_provider_results_within_their_chat(monkeypatch):
    saved = {}
    dispatches = []

    async def load(scope, kind, key):
        return saved.get((scope, kind, key))

    async def retain(scope, kind, key, value):
        saved[scope, kind, key] = value

    async def fetch(query, names, **_kwargs):
        dispatches.append((query, names))
        return ({name: [SearchResult(title=query, url="https://example.test/")] if name == "a" else []
                for name in names}, {name: 1 for name in names}, [],
                {name: sources.NO_RESULTS for name in names if name != "a"},
                {name: "direct" for name in names})

    monkeypatch.setattr(search_cache, "cached", load)
    monkeypatch.setattr(search_cache, "retain", retain)

    async def query(chat, text, names, refresh=False):
        return await search_cache.fetch_providers(("user", chat), text, names, None, 10, refresh, fetch)

    async def trial():
        await query("one", "Ada", ["a", "b"])
        values, _, _, reasons, _ = await query("one", "Ada", ["a", "b", "c"])
        assert values["a"][0].title == "Ada"
        assert values["b"] == [] and reasons["b"] == sources.NO_RESULTS
        await query("two", "Ada", ["a"])
        await query("one", "Ada", ["a"], refresh=True)

    asyncio.run(trial())
    assert dispatches == [("Ada", ["a", "b"]), ("Ada", ["c"]), ("Ada", ["a"]), ("Ada", ["a"])]
