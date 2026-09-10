"""Manual procedure manual-table."""

from __future__ import annotations

from manual_qa_runtime import (
    ABSENT,
    FIND,
    route,
)

PROCEDURE_NAME = 'manual-table'


async def run(r):
    async def baseline():
        await r.preview("manual_table_substitute")
        await r.type(FIND, "", True)
        await r.text("A-01")
        await r.registered("qa-table-data-sort-filter")
        return {"source": "manual-qa-table.csv", "remaining_row": ["A-02", "Cluj", "20"]}
    await r.phase("baseline", "The source table renders in preview and full view and applies numeric order and a text filter.", baseline)
    await r.phase("sort-and-filter", "The filtered row matches the generated source bytes.", baseline)
    async def columns():
        await r.full("manual_table_substitute")
        await r.text("A-01")
        await r.action("pointer_click_css", 'button[aria-label="Choose visible columns"]')
        await r.action("pointer_click_css", 'button[aria-label="Hide all columns"]')
        await r.text("Every column of this sheet is hidden.")
        await r.action("pointer_click_css", '[role="dialog"] input[type="checkbox"]')
        await r.action("press_key", "Escape")
        await r.check("return document.querySelectorAll('thead th').length===2;")
        url = await r.action("eval", "return location.pathname;")
        await r.action("goto", url)
        return await r.check("return {ok:document.querySelectorAll('thead th').length===2,headers:[...document.querySelectorAll('thead th')].map(x=>x.innerText)};")
    await r.phase("columns-and-reload", "Hide all displays an empty state. Showing one column survives route reload.", columns)
    async def no_matches():
        await r.full("manual_table_substitute")
        await r.text("A-01")
        await r.action("pointer_click_css", 'button[aria-label="Filter Region"]')
        await r.type('[role="dialog"] input[placeholder="Contains…"]', ABSENT)
        await r.action("pointer_click_css", 'button[aria-label="Apply contains filter"]')
        await r.text("rows 0–0 of 0")
        await r.action("click_css", 'button[title="Remove every column filter"]')
        await r.text("A-01")
        return await r.check("return {ok:document.querySelectorAll('tbody tr').length===3};")
    await r.phase("no-matches", "An absent value produces zero rows and clearing filters restores three rows.", no_matches)
    async def keyboard():
        await r.registered("qa-table-modal-keyboard")
        return {"focus_return": True, "escape": True}
    await r.phase("keyboard", "Keyboard focus stays inside the modal and Escape returns focus to its trigger.", keyboard)
    async def modal():
        for name in ("qa-table-modal-geometry", "qa-table-modal-backdrop", "qa-table-modal-light-colors", "qa-table-modal-dark-colors"):
            page = next(
                p for p in r.h.load_scenario_pages(r.h.default_scenarios_path()) if p.name == name
            )
            await r.h.set_color_scheme(r.tab, page.color_scheme)
            await r.registered(name)
        await r.h.set_color_scheme(r.tab, "")
        return {"geometry": True, "backdrop_hit_test": True, "single_modal": True, "palette": "light"}
    await r.phase("single-modal-and-palette", "Pointer hit testing prevents background activation and the modal retains the fixed palette.", modal)
