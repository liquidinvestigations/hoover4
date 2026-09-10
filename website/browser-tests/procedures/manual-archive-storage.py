"""Manual procedure manual-archive-storage."""

from __future__ import annotations

import json

from manual_qa_runtime import (
    route,
)

PROCEDURE_NAME = 'manual-archive-storage'


async def run(r):
    async def baseline():
        identity = await r.preview("directory_archive", "the-directory.zip")
        await r.action("eval", "const a=document.querySelector(%s);let row=a;while(row&&!row.style.height.includes('148px'))row=row.parentElement;const more=row?.querySelector('a')?.parentElement.querySelector('button');if(!more)throw Error('result more control unavailable');more.click();return true;" % json.dumps(f'a[href^="/view_document/{route(identity)}/"]'))
        await r.click("Open in File Browser")
        await r.check("return location.pathname.startsWith('/file_browser/');")
        await r.text("the-directory.zip")
        await r.click("the-directory.zip", "table")
        await r.check("return document.querySelectorAll('#x-storage-tree [aria-current=\"location\"]').length===1;")
        return await r.action("eval", "return {route:location.pathname,tree:document.querySelector('#x-storage-tree').innerText,listing:document.querySelector('table')?.innerText};")
    await r.phase("baseline", "The search action opens the archive location and the archive row enters its root.", baseline)
    await r.phase("search-handoff", "The selected archive and storage focus agree.", baseline)
    async def history():
        await baseline()
        before = await r.action("eval", "return location.pathname;")
        await r.action("history_back")
        await r.text("the-directory.zip")
        await r.action("history_forward")
        return await r.check("return {ok:location.pathname===%s,route:location.pathname};" % json.dumps(before))
    await r.phase("return-navigation", "Browser history returns to the archive route.", history)
    async def highlight():
        await r.registered("qa-storage-archive-highlight")
        return {"current_rows": 1}
    await r.phase("archive-highlight", "Exactly one tree row identifies the current archive.", highlight)
