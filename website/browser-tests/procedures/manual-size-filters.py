"""Manual procedure manual-size-filters."""

from __future__ import annotations

import json

from manual_qa_runtime import (
    FIND,
)

PROCEDURE_NAME = 'manual-size-filters'


async def run(r):
    async def baseline():
        await r.search()
        await r.expected_results(x["hash"] for x in r.metadata()["files"])
        await r.preview("easychair_odt", "easychair")
        await r.find("Mac", 2)
        await r.modal("File size")
        await r.type('input[placeholder="min"]', "1")
        await r.type('input[placeholder="max"]', "10")
        await r.action("press_key", "Tab")
        await r.apply()
        await r.count(0)
        return await r.check("return {ok:!document.querySelector(%s),chips:document.querySelector('#x-filter-chips')?.innerText};" % json.dumps(FIND))
    await r.phase("baseline", "The selected ODT has two Mac hits. The size filter clears its preview and returns zero hits.", baseline)
    async def clear():
        await baseline()
        await r.action("eval", "const p=[...document.querySelectorAll('#x-filter-chips [title]')].find(x=>x.textContent.includes('Collections'));const b=p?.querySelector('button[title=\"Remove this filter\"]');if(!b)throw Error('collection chip remove control unavailable');b.click();return true;")
        await r.check("return document.querySelector('#x-filter-chips')?.innerText.includes('File size');")
        await r.click("Clear all", "#x-filter-chips")
        return await r.check("return {ok:!document.querySelector('#x-filter-chips')?.innerText.trim(),url:location.href};")
    await r.phase("find-zero-clear", "Removing Collections retains the size filter. Clear all removes every chip.", clear)
    async def reload():
        await baseline()
        before = await r.action("eval", "return location.pathname;")
        await r.reload()
        await r.count(0)
        await r.check("return location.pathname===%s;" % json.dumps(before))
        await r.modal("File size")
        return await r.check("return {ok:document.querySelector('input[placeholder=min]')?.value==='1'&&document.querySelector('input[placeholder=max]')?.value==='10'};")
    await r.phase("reload-persistence", "The applied size interval survives a reload.", reload)
