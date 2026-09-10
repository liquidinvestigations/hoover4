"""Manual procedure manual-folder-search."""

from __future__ import annotations

import json

from manual_qa_runtime import (
    FIND,
    folder_route,
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
        await r.click("Open in Search")
        await r.check("return location.pathname.startsWith('/search/');")
        expected = {x["hash"] for x in r.metadata()["files"] if x["path"] in ('/entity-fixtures/generate.py', '/entity-fixtures/invoice-batch.docx')}
        result = await r.expected_results(expected)
        await r.text("File location", "#x-filter-chips")
        return {"expected_folder_documents": result, "draft_members": ["generate.py", "invoice-batch.docx"]}
    await r.phase("baseline", "Folder search selects the invoice and transfers the folder constraint to global search.", baseline)
    await r.phase("handoff", "Open in Search returns the source metadata identities below the selected folder.", baseline)
    async def return_clear():
        await baseline()
        destination = await r.action("eval", "return location.pathname;")
        await r.action("history_back")
        await r.check("return location.pathname.startsWith('/file_browser/');")
        await r.check("return document.querySelector('input[placeholder=\"Search in folder…\"]')?.value==='invoice';")
        await r.action("history_forward")
        await r.check("return location.pathname===%s;" % json.dumps(destination))
        await r.action("click_css", '#x-filter-chips button[title="Remove this filter"]')
        return await r.check("return !document.querySelector('#x-filter-chips')?.innerText.includes('File location');")
    await r.phase("return-and-clear", "Back restores the folder filter text. Forward restores search and the folder chip can be removed.", return_clear)
