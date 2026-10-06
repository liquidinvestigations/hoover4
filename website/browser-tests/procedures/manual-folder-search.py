"""Manual procedure manual-folder-search."""

from __future__ import annotations

import json

from manual_qa_runtime import (
    FIND,
    folder_route,
    route,
)

PROCEDURE_NAME = 'manual-folder-search'


async def run(r):
    async def baseline():
        await folder_route(r, "testdata_manualqa", "/entity-fixtures")
        await r.type('input[placeholder="Search in folder…"]', "invoice")
        await r.text("1 matches in this folder and below")
        await r.click("invoice-batch.docx", "table")
        await r.action("wait_css", FIND)
        await r.check("return document.querySelector('input[placeholder=\"Search in folder…\"]')?.value==='invoice';")
        expected = {x["hash"] for x in r.metadata()["files"] if x["path"] in ('/entity-fixtures/generate.py', '/entity-fixtures/invoice-batch.docx')}
        async def inspect(child):
            await r.h.wait_css(child, '#x-search-panel-results-wrapper a[href^="/view_document/"]')
            hrefs = await r.h.js(child, "return [...document.querySelectorAll('#x-search-panel-results-wrapper a[href^=\"/view_document/\"]')].map(a=>a.getAttribute('href'));")
            from manual_qa_runtime import unroute
            actual = {unroute(href.split('/')[2])["file_hash"] for href in hrefs}
            if actual != expected:
                raise AssertionError(f"folder result identities differ: {actual} != {expected}")
            return {"identities": sorted(actual)}
        result = await r.popup('a[title="Search the whole corpus, filtered to this folder and everything below it"]', "documents found", inspect=inspect)
        await r.check("return location.pathname.startsWith('/file_browser/')&&document.querySelector('input[placeholder=\"Search in folder…\"]')?.value==='invoice';")
        return result

    await r.phase("baseline", "Folder search selects the invoice and transfers the folder constraint to global search.", baseline)
    await r.phase("handoff", "Open in Search returns the source metadata identities below the selected folder.", baseline)
    async def return_clear():
        await baseline()
        await r.action("click_css", '.x-search-input button[title="Clear search"]')
        await r.check("return document.querySelector('input[placeholder=\"Search in folder…\"]')?.value==='';")
        await r.type('input[placeholder="Search in folder…"]', "invoice")
        await r.text("1 matches in this folder and below")
        await r.click("invoice-batch.docx", "table")
        root = route({"container_hash": "", "path": "/"})
        await r.action("click_css", f'a[href="/file_browser/testdata_manualqa/{root}/9g==/9g=="]')
        await r.check("return location.pathname.split('/')[3]===%s;" % json.dumps(root))
        await r.action("history_back")
        return await r.check("return document.querySelector('input[placeholder=\"Search in folder…\"]')?.value==='invoice';")

    await r.phase("return-and-clear", "Closing Search preserves the folder query. Clearing and history navigation preserve the expected folder state.", return_clear)
