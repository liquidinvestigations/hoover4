"""Manual procedure manual-archive-viewer."""

from __future__ import annotations

from manual_qa_runtime import (
    folder_route,
    route,
    unroute,
    viewer_state,
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
    async def section():
        _, identity = r.fixture("parent_archive")
        await r.action("goto", f"/view_document/{route(identity)}/{route(viewer_state())}/{route({'selected_tab': 'Entities'})}")
        await r.action("wait_css", ".x-archive-section")
        observed = await r.check(
            "const sec=document.querySelector('.x-archive-section');const rows=[...sec.querySelectorAll('tr')]"
            ".map(tr=>[tr.cells[0].innerText.trim(),tr.cells[1].innerText.trim(),!!tr.cells[1].querySelector('code')]);"
            "const links=[...sec.querySelectorAll('.x-archive-links a')].map(a=>[a.innerText.trim(),a.getAttribute('target')]);"
            "const files=rows.find(x=>x[0]==='Extracted files');"
            "return {ok:sec.querySelector('h1').innerText.trim()==='Archive'&&!!files&&files[1]==='1'&&files[2]"
            "&&JSON.stringify(links)===JSON.stringify([['Browse the archive','_blank'],['search inside this zip file','_blank']])"
            "&&!document.body.innerText.includes('can be missing from search'),rows,links};")
        return observed
    await r.phase("metadata-section", "The Archive tab shows one metadata section titled Archive, with code values and two links that open new tabs.", section)
    async def browse():
        return await r.popup(".x-archive-browse", "parent")
    await r.phase("browse-new-tab", "The browse link opens the file browser inside the archive in a new tab.", browse)
    async def search():
        item, identity = r.fixture("parent_archive")
        async def filters(child):
            path = await r.h.js(child, "return location.pathname;")
            query = unroute(path.split("/")[2])
            paths = query["facet_filters"].get("file_paths", [])
            datasets = query["facet_filters"].get("collection_dataset", [])
            if query["collection_datasets"] != [item["dataset"]] or datasets != [{"String": item["dataset"]}] or len(paths) != 1:
                raise AssertionError(f"the search route does not scope the archive: {query}")
            return {"collection_datasets": query["collection_datasets"], "file_paths": paths, "collection_dataset": datasets}
        return await r.popup(".x-archive-search", "child.txt", inspect=filters)
    await r.phase("search-new-tab", "The search link opens a new tab that lists the file inside the archive, scoped by the archive folder and its dataset.", search)
