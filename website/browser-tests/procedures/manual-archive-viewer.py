"""Manual procedure manual-archive-viewer."""

from __future__ import annotations

from manual_qa_runtime import (
    folder_route,
    route,
    unroute,
)

PROCEDURE_NAME = 'manual-archive-viewer'


async def run(r):
    async def baseline():
        await folder_route(r, "testdata_manualqa", "/archives")
        await r.text("parent.zip")
        await r.action("eval", "const row=[...document.querySelectorAll('tr')].find(x=>x.innerText.includes('parent.zip'));const b=[...row.querySelectorAll('button')].find(x=>x.innerText.includes('View Details'));if(!b)throw Error('archive preview control unavailable');b.click();return true;")
        await r.text("parent.zip")
        _, identity = r.fixture("parent_archive")
        return await r.popup(f'a[href^="/view_document/{route(identity)}/"]', "parent.zip")
    await r.phase("baseline", "View Details opens the archive preview and its full document viewer.", baseline)
    await r.phase("no-source-archive", "The archive document title and right-side tabs load without an endless pending state.", baseline)
    async def separate():
        await folder_route(r, "testdata_manualqa", "/archives")
        await r.click("parent.zip", "table")
        expected = r.fixture("parent_archive")[1]["file_hash"]
        descriptor = await r.action("eval", "return location.pathname.split('/')[3];")
        if unroute(descriptor)["container_hash"] != expected:
            raise AssertionError("archive row did not enter its container")
        return {"container": expected}
    await r.phase("separate-container-action", "Clicking the archive row enters the container independently of View Details.", separate)
