"""Manual procedure manual-entities."""

from __future__ import annotations

import json

from manual_qa_runtime import (
    ABSENT,
    FIND,
    UnmetPrerequisite,
)

PROCEDURE_NAME = 'manual-entities'


async def run(r):
    async def baseline():
        await r.full("easychair_office")
        await r.action("wait_css", 'input[placeholder="Filter Entities ..."]')
        expected = r.profile.get("source_expectations", {}).get("easychair_entities")
        if not expected:
            raise UnmetPrerequisite("The Easychair entity-value and source-text count oracle is unavailable.")
        observed = []
        for item in expected:
            await r.type('input[placeholder="Filter Entities ..."]', item["value"])
            await r.text(item["value"])
            await r.check("const e=[...document.querySelectorAll('.x-entity-chip')].find(x=>x.title===%s);return {ok:!!e&&e.lastElementChild?.textContent.trim()===%s,text:e?.innerText};" % (json.dumps(item["value"]), json.dumps(str(item["count"]))))
            await r.action("click_css", '.x-entity-chip[title=%s]' % json.dumps(item["value"]))
            await r.check("return document.querySelector(%s)?.value.includes(%s);" % (json.dumps(FIND), json.dumps(item["value"])))
            await r.text(item["value"])
            observed.append(item)
            await r.action("press_key", "Escape")
        return observed
    await r.phase("baseline", "Known Easychair values and counts match the original DOCX text.", baseline)
    await r.phase("multiple-values", "Two selected entity values open their own cards and counts.", baseline)
    async def stale():
        await r.full("easychair_office", selected_entity=ABSENT)
        await r.text("has no entity")
        return {"missing_value": ABSENT}
    await r.phase("stale-entity", "An absent selected entity produces the explicit missing-value state.", stale)
    async def appearance():
        await r.full("easychair_office")
        await r.action("wait_css", ".x-entity-chip")
        await r.action("click_css", ".x-entity-chip")
        return await r.palette('.x-entity-chip')
    await r.phase("appearance", "Entity values and cards render under both color preferences.", appearance)
