"""Verify document controls, search selection, and folder disclosure."""

from __future__ import annotations

import json
import math
import re

from manual_qa_runtime import ABSENT, FIND, folder_route

PROCEDURE_NAME = "viewer-regressions"


async def run(r):
    async def sources():
        await r.full("stanley_pdf_with_ocr")
        await r.action("wait_css", '[data-source-list="true"]')
        await r.check("return !document.querySelector('[data-source-trigger=true]');")
        await r.preview("stanley_pdf_with_ocr", "stanley")
        await r.action("click_css", '[data-source-trigger="true"]')
        await r.action("wait_css", '[data-source-list="true"]')
        await r.action("press_key", "Escape")
        return await r.check("return !document.querySelector('[data-source-list=true]');")
    await r.phase("source-controls", "The full viewer has a source list. The preview dropdown opens once and closes with Escape.", sources)

    async def selection():
        await r.search("child", ["testdata_manualqa"])
        await r.action("click_css", 'button[aria-label="Next Result"]')
        await r.action("wait_css", FIND)
        return await r.check("return location.pathname.split('/')[4]!=='9g==';")
    await r.phase("first-result", "Next selects the first result when no result is selected.", selection)

    async def inputs():
        await r.search("child", ["testdata_manualqa"])
        await r.action("click_css", '#x-search-input-search-box button[title="Clear search"]')
        await r.check("return document.querySelector('#x-search-input-search-box input')?.value==='';")
        await r.full("easychair_office", find_query="Mac")
        await r.action("click_css", '.x-search-input button[title="Clear search"]')
        await r.check("return document.querySelector(%s)?.value==='';" % json.dumps(FIND))
        await folder_route(r, "testdata_manualqa")
        await r.type('input[placeholder="Search in folder…"]', "invoice")
        await r.action("click_css", '.x-search-input button[title="Clear search"]')
        return await r.check("return document.querySelector('input[placeholder=\"Search in folder…\"]')?.value==='';")
    await r.phase("shared-inputs", "The main search, document find, and folder search each submit and clear through the shared input.", inputs)

    async def headers():
        expected = r.profile["source_expectations"]["romanian_email"]["envelope"]
        parties = [party for people in expected.values() for party in people]
        address = next(party["address"] for party in parties if party.get("address"))
        term = re.findall(r"[\w]+", address.split("@", 1)[0])[0]
        await r.full("romanian_email", find_query=term)
        await r.action("wait_css", ".x-email-header-hit")
        await r.action("wait_css", ".x-email-details-panel")
        return await r.check("const hits=[...document.querySelectorAll('.x-email-header-hit')].map(e=>e.textContent);return {ok:hits.some(text=>text.toLowerCase().includes(%s)),hits};" % json.dumps(term.lower()))
    await r.phase("email-header-highlights", "A matching header value is highlighted and opens email details.", headers)

    async def hits():
        await r.full("easychair_odt")
        await r.find("Mac", 2)
        await r.hit("next", 2, 2)
        await r.check("const hit=document.querySelector('[data-text-hit=\"1\"]');const root=document.querySelector('#x-document-text-viewer');if(!hit||!root)return false;const a=hit.getBoundingClientRect(),b=root.getBoundingClientRect();return {ok:a.bottom>=b.top&&a.top<=b.bottom,hit:[a.top,a.bottom],viewer:[b.top,b.bottom]};")
        await r.find(ABSENT, 0)
        await r.find("Mac", 2)
        return await r.check("const active=document.querySelector('.x-hit-span-active-match');return {ok:!!active,text:active?.textContent};")
    await r.phase("text-hit-scroll", "Text hit navigation scrolls the current span after the query changes.", hits)

    async def table():
        await r.preview("manual_table_substitute")
        await r.text("A-01")
        await r.check("return document.querySelector(%s)?.value==='';" % json.dumps(FIND))
        await r.type(FIND, ABSENT, True)
        await r.text("No rows match the current filters.")
        await r.click("Clear filters")
        await r.text("A-01")
        return await r.check("return document.querySelectorAll('tbody tr').length===3;")
    await r.phase("filename-table-and-empty-filter", "A filename match opens all table rows. A zero-row filter offers a working clear action.", table)

    async def snippets():
        await r.search("canicula", ["testdata_manualqa"])
        await r.action("wait_css", '#x-search-panel-results-wrapper li')
        return await r.check("const cards=[...document.querySelectorAll('#x-search-panel-results-wrapper li')];return {ok:cards.length>0&&cards.every(card=>!card.innerText.includes('Content-Transfer-Encoding:')&&!card.innerText.includes('Content-Type:')),snippets:cards.map(card=>card.innerText)};")
    await r.phase("parsed-snippets", "Email search snippets show readable parsed text without MIME headers.", snippets)

    async def entity():
        await r.full("shipping_manifest")
        await r.action("wait_css", '.x-entity-chip[title="+24762889"]')
        await r.action("click_css", '.x-entity-chip[title="+24762889"]')
        await r.action("wait_css", '[data-entity-card-value="true"]')
        return await r.check("const value=document.querySelector('[data-entity-card-value=true]');const chip=document.querySelector('.x-entity-chip[title=\"+24762889\"]');return {ok:!!value&&parseFloat(getComputedStyle(value).fontSize)===16&&value.textContent==='+24762889'&&chip.innerText.includes('mentions in all sources'),value:value?.textContent,chip:chip?.innerText};")
    await r.phase("entity-value-and-count", "The entity value appears first at 16 pixels. The count names all sources.", entity)

    async def pages():
        await r.search("", ["testdata_manualqa"])
        count = await r.action("eval", "return Number(document.querySelector('#x-search-panel-left-title-row h1').textContent.replaceAll(',','').match(/[0-9]+/)[0]);")
        maximum = math.ceil(min(count, 1000) / 20)
        return await r.check("const e=document.querySelector('[data-result-page-counter=true]');const style=e&&getComputedStyle(e);return {ok:!!e&&e.textContent.replaceAll(' ','').trim()===%s&&parseFloat(style.borderLeftWidth)>0,text:e?.textContent,border:style?.borderLeftWidth};" % json.dumps(f"1/{maximum}"))
    await r.phase("page-counter", "The bordered page counter uses ceiling division and limits reachable results to 1,000.", pages)

    async def tree():
        await folder_route(r, "testdata_manualqa")
        await r.action("wait_css", '#x-storage-tree [data-subfolder-count]')
        return await r.check("const rows=[...document.querySelectorAll('#x-storage-tree [data-subfolder-count]')];return {ok:rows.length>0&&rows.every(row=>!!row.querySelector('button[aria-expanded]')===(Number(row.dataset.subfolderCount)>0)),rows:rows.map(row=>({path:row.title,subfolders:Number(row.dataset.subfolderCount),disclosure:!!row.querySelector('button[aria-expanded]')}))};")
    await r.phase("folder-disclosure", "Only nodes with child folders or containers have a disclosure control.", tree)
