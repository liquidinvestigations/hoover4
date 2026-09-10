"""Manual procedure manual-type-filters."""

from __future__ import annotations

PROCEDURE_NAME = 'manual-type-filters'


async def run(r):
    async def incremental():
        await r.search()
        types = []
        records = []
        for kind in ("text", "doc", "email"):
            await r.modal("File types")
            await r.click(kind, "#x-filter-modal")
            await r.apply()
            types.append(kind)
            records.append(await r.expected_results(x["hash"] for x in r.metadata()["types"] if x["file_type"] in types))
        await r.select("security_incident")
        return {"source_metadata_counts": records, "draft_counts": [18, 22, 24]}
    await r.phase("baseline", "Cumulative file types retain previous selections and select the expected email.", incremental)
    await r.phase("incremental-types", "Each applied type set matches the independent canonical-type rows.", incremental)
    async def appearance():
        await r.search()
        await r.modal("File types")
        return await r.palette("#x-filter-modal")
    await r.phase("popover-appearance", "The file-type pane renders under both color preferences.", appearance)
