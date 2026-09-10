"""Manual procedure manual-pdf."""

from __future__ import annotations

import json

from manual_qa_runtime import (
    ABSENT,
    FIND,
    pdf_state,
    query,
)

PROCEDURE_NAME = 'manual-pdf'


async def run(r):
    async def baseline():
        await r.preview("stanley_pdf_with_ocr", "stanley")
        await r.find("MIT", 7)
        first = await pdf_state(r)
        await r.hit("next", 2, 7)
        second = await pdf_state(r)
        if first["search"].get("activeResultIndex") == second["search"].get("activeResultIndex"):
            raise AssertionError("the active PDF result did not advance")
        await r.full("stanley_pdf_with_ocr", find_query="MIT")
        await r.text("1 / 7")
        return {"preview_first": first, "preview_second": second, "full": await pdf_state(r)}
    await r.phase("baseline", "The Stanley PDF has seven MIT hits with visible highlights in preview and full view.", baseline)
    async def source_switch():
        results = []
        for preview in (False, True):
            if preview:
                await r.preview("stanley_pdf_with_ocr", "stanley")
            else:
                await r.full("stanley_pdf_with_ocr")
            await r.find("MIT", 7)
            original = await pdf_state(r)
            await r.pdf_source("PDF · OCR · Tesseract · eng", preview)
            await r.text("1 / 7")
            derived = await pdf_state(r)
            if original["search"]["results"] == derived["search"]["results"]:
                raise AssertionError("original and OCR search geometry unexpectedly match")
            await r.hit("next", 2, 7)
            await pdf_state(r)
            await r.pdf_source("PDF", preview)
            await r.text("1 / 7")
            results.append({"preview": preview, "original": original, "ocr": derived, "returned": await pdf_state(r)})
        await r.full("stanley_pdf_with_ocr")
        await r.action("eval", "window.__qa_original_fetch=window.fetch;window.__qa_held=false;window.__qa_released=false;window.fetch=(...args)=>{const u=typeof args[0]==='string'?args[0]:args[0].url;if(u.includes('search_document_pdf')&&!window.__qa_held){window.__qa_held=true;return new Promise((resolve,reject)=>{window.__qa_release=()=>window.__qa_original_fetch(...args).then(value=>{window.__qa_released=true;resolve(value)},reject);});}return window.__qa_original_fetch(...args)};return true;")
        try:
            await r.type(FIND, "MIT", True)
            await r.check("return window.__qa_held===true;")
            await r.pdf_source("PDF · OCR · Tesseract · eng")
            await r.text("1 / 7")
            current = await pdf_state(r)
            await r.action("eval", "window.__qa_release();return true;")
            await r.check("return window.__qa_released===true;")
            await r.hit("next", 2, 7)
            after = await pdf_state(r)
            if current["search"]["results"] != after["search"]["results"]:
                raise AssertionError("the delayed original request replaced current OCR geometry")
            results.append({"delayed_original": True, "current_before": current, "current_after": after})
        finally:
            await r.action("eval", "window.fetch=window.__qa_original_fetch;window.__qa_release?.();return true;")
        return results
    await r.phase("active-find-source-switch", "Both source orders preserve current geometry. A held original request cannot replace usable OCR results.", source_switch)
    async def controls():
        await r.full("stanley_pdf_with_ocr")
        await r.action("wait_css", "#x-pdf-viewer embedpdf-container")
        await r.check("return [...document.querySelectorAll('input')].some(e=>!e.placeholder&&e.value==='1');")
        await r.action("eval", "const e=[...document.querySelectorAll('input')].find(e=>!e.placeholder&&e.value==='1');if(!e)throw Error('page field unavailable');e.id='qa-pdf-page';e.parentElement.parentElement.id='qa-pdf-controls';return true;")
        await r.type("#qa-pdf-page", "3", True)
        await r.check("return document.querySelector('#qa-pdf-page')?.value==='3';")
        before = await r.action("eval", "return document.querySelector('#qa-pdf-controls').innerText;")
        await r.action("click_css", "#qa-pdf-controls button:nth-of-type(3)")
        await r.check("return document.querySelector('#qa-pdf-controls').innerText!==%s;" % json.dumps(before))
        await r.action("click_css", "#qa-pdf-controls button:nth-of-type(4)")
        await r.check("return document.querySelector('#qa-pdf-controls').innerText===%s;" % json.dumps(before))
        await r.full("born_digital_pdf_without_ocr")
        return await r.check("const row=[...document.querySelectorAll('[data-source-list=true] [data-source-label]')].find(e=>getComputedStyle(e).color==='rgb(17, 17, 17)');if(!row)throw Error('no selected pdf source row found');return {ok:!row.textContent.includes('PDF · OCR'),text:row.textContent};")
    await r.phase("page-and-zoom", "Page input and both zoom controls change once. The original-only PDF has no OCR source.", controls)
    async def no_match():
        await r.full("stanley_pdf_with_ocr")
        await r.find(ABSENT, 0)
        await r.pdf_source("PDF · OCR · Tesseract · eng")
        await r.text("- / -")
        observed = await pdf_state(r, 0)
        if observed["overlays"]:
            raise AssertionError("an absent term retained PDF highlight overlays")
        return observed
    await r.phase("no-match", "An absent query leaves no PDF highlight after a source change.", no_match)
    async def appearance():
        await r.preview("stanley_pdf_with_ocr", "stanley")
        await r.find("MIT", 7)
        await r.action("click_css", '[data-source-trigger="true"]')
        result = []
        for scheme in ("light", "dark"):
            await r.h.set_color_scheme(r.tab, scheme)
            result.append(await r.check("const list=document.querySelector('[data-source-list=true]');if(!list)return false;const rows=[...list.querySelectorAll('[data-source-label]')].map(e=>({label:e.dataset.sourceLabel,count:e.nextElementSibling?.textContent.trim(),background:getComputedStyle(e.parentElement).backgroundColor}));const box=list.getBoundingClientRect();return {ok:box.width>0&&box.left>=0&&box.right<=innerWidth&&rows.some(e=>e.label==='PDF'&&e.count==='7')&&rows.some(e=>e.label==='PDF · OCR · Tesseract · eng'&&e.count==='7')&&rows.every(e=>e.background==='rgb(255, 255, 255)'),scheme:%s,rows,width:box.width};" % json.dumps(scheme)))
        await r.h.set_color_scheme(r.tab, "")
        return result
    await r.phase("source-appearance", "The source selector renders under both color preferences.", appearance)
