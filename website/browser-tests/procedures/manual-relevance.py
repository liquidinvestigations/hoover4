"""Manual procedure manual-relevance."""

from __future__ import annotations

from manual_qa_runtime import (
    UnmetPrerequisite,
    query,
)

PROCEDURE_NAME = 'manual-relevance'


async def run(r):
    async def baseline():
        await r.search("child")
        await r.click("Sort", "#x-search-input-top-bar")
        await r.click("Relevance")
        await r.action("eval", "const b=[...document.querySelectorAll('#x-search-input-top-bar button')].find(b=>b.textContent.trim()==='Search');if(b&&!b.disabled)b.click();return true;")
        await r.check("return document.querySelector('button[aria-label=\"Sort direction: descending\"]')?.disabled===true;")
        expected = [row["file_hash"] for row in r.metadata().get("raw_relevance", [])]
        if not expected:
            raise UnmetPrerequisite("Refresh the independent raw relevance-score oracle.")
        actual = await r.identities()
        if actual != expected:
            raise AssertionError(f"relevance differs from raw scores: expected {expected}, observed {actual}")
        await r.reload()
        await r.check("return document.querySelector('button[aria-label=\"Sort direction: descending\"]')?.disabled===true;")
        return {"identities": actual, "raw_scores": r.metadata()["raw_relevance"],
                "draft_first": "parent.zip", "prepared_parent_ordinal": actual.index(r.fixture("parent_archive")[1]["file_hash"]) + 1}
    await r.phase("baseline", "The child query follows independent raw relevance scores in descending order.", baseline)
    await r.phase("explicit-relevance", "Explicit relevance and reload retain descending order.", baseline)
    async def empty():
        await r.registered("qa-sort-empty-default")
        await r.registered("qa-sort-legacy-ascending-relevance")
        return {"current_and_legacy_direction": "descending"}
    await r.phase("empty-query", "Current and legacy empty relevance routes expose a disabled descending direction.", empty)
