"""Manual procedure manual-entity-filter."""

from __future__ import annotations

from manual_qa_runtime import (
    ABSENT,
    FIND,
)

PROCEDURE_NAME = 'manual-entity-filter'


async def run(r):
    async def baseline():
        await r.search()
        await r.modal("Entities")
        await r.click("Location", "#x-filter-modal")
        await r.type('input[placeholder="Search location…"]', "Manchester")
        await r.click("Manchester", "#x-filter-modal")
        await r.apply()
        expected = {x["file_hash"] for x in r.metadata()["entities"] if x["entity_type"] in ("LOC", "loc", "location") and "Manchester" in x["entity_values"]}
        result = await r.expected_results(expected)
        await r.select("easychair_odt")
        await r.type(FIND, "Manchester", True)
        await r.check("return [...document.querySelectorAll('div')].some(x=>x.children.length===0&&/^1 \\/ [1-9]/.test(x.textContent));")
        return result
    await r.phase("baseline", "The exact Manchester entity selects only documents carrying that source entity.", baseline)
    await r.phase("exact-entity", "The ODT document find locates the selected entity.", baseline)
    async def no_match():
        await r.search()
        await r.modal("Entities")
        await r.click("Location", "#x-filter-modal")
        await r.type('input[placeholder="Search location…"]', ABSENT)
        await r.text("No", "#x-filter-modal")
        await r.click("Cancel", "#x-filter-modal")
        await r.modal("Entities")
        return await r.check("return {ok:!document.querySelector('#x-filter-chips')?.innerText.includes('Entities')};")
    await r.phase("entity-no-match", "An absent location creates no hidden selection.", no_match)
    async def appearance():
        await r.search()
        await r.modal("Entities")
        return await r.palette("#x-filter-modal")
    await r.phase("popover-appearance", "Entity controls render under both color preferences.", appearance)
