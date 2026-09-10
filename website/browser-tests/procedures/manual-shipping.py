"""Manual procedure manual-shipping."""

from __future__ import annotations

import json

from manual_qa_runtime import (
    ABSENT,
    FIND,
    query,
    route,
)

PROCEDURE_NAME = 'manual-shipping'


async def run(r):
    async def baseline():
        await r.preview("shipping_manifest", "CSQU3054383")
        await r.find("is", 4)
        await r.hit("next", 2, 4)
        await r.hit("previous", 1, 4)
        return {"query": "CSQU3054383", "find_hits": 4}
    await r.phase("baseline", "The manifest is selected and document find navigates four occurrences.", baseline)
    await r.phase("keyboard-find", "Enter submits the find and next/previous change the counter.", baseline)
    async def popup():
        identity = await r.preview("shipping_manifest", "CSQU3054383")
        await r.find("is", 4)
        expected = next(x for x in r.contract["fixtures"] if x["name"] == "shipping_manifest")["expected"]["entity_values"]
        result = await r.popup(f'a[href^="/view_document/{route(identity)}/"]', "Entities", [x["value"] for x in expected])
        await r.text("1 / 4")
        result["expected_entities"] = expected
        text = "\n".join(result["child"]["lines"])
        missing = [x["value"] for x in expected if x["value"] not in text]
        if missing:
            raise AssertionError(f"entity values absent from full viewer: {missing}")
        return result
    await r.phase("popup-return", "The full viewer has the declared entities and the preview retains its find.", popup)
    async def no_match():
        await r.preview("shipping_manifest", "CSQU3054383")
        await r.find(ABSENT, 0)
        return await r.check("const p=document.querySelector('#x-search-results-right-panel');const counter=[...p.querySelectorAll('div')].find(e=>e.children.length===0&&e.textContent.trim()==='- / -');const buttons=[...counter.parentElement.querySelectorAll('button')];return {ok:!p.querySelector('.x-hit-span-active-match')&&buttons.length===2&&buttons.every(b=>b.disabled),query:document.querySelector(%s).value};" % json.dumps(FIND))
    await r.phase("no-match", "An absent term clears the active hit.", no_match)
