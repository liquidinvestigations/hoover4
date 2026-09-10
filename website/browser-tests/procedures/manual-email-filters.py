"""Manual procedure manual-email-filters."""

from __future__ import annotations

from manual_qa_runtime import (
    email_envelope,
)

PROCEDURE_NAME = 'manual-email-filters'


async def run(r):
    async def baseline():
        return await email_envelope(r)
    await r.phase("baseline", "The original email envelope and all three attachment hashes match source bytes.", baseline)
    async def attachments():
        observed = await email_envelope(r)
        records = []
        for item in observed["attachments"]:
            records.append(await r.popup(f'a[href="{item["href"]}"]', item["name"]))
        await r.action("wait_css", ".x-email-details-panel")
        return records
    await r.phase("attachment-tabs", "Each attachment opens its own full viewer and preserves the email tab.", attachments)
    async def combined():
        await r.search()
        await r.modal("Email")
        await r.click("Email has attachments", "#x-filter-modal")
        await r.apply()
        metadata = r.metadata()
        containers = {x["container_hash"] for x in metadata["files"] if x["container_hash"]}
        emails = {x["email_hash"] for x in metadata["emails"]} & containers
        first = await r.expected_results(emails)
        await r.modal("Email")
        await r.type('input[placeholder="Search senders…"]', "penultim_o@yahoo.com")
        await r.click("penultim_o@yahoo.com", "#x-filter-modal")
        await r.apply()
        senders = {x["email_hash"] for x in metadata["addresses"] if x["role"] == "from" and x["address"] == "penultim_o@yahoo.com"}
        second = await r.expected_results(emails & senders)
        await r.reload()
        await r.expected_results(emails & senders)
        await r.modal("Email")
        await r.text("penultim_o@yahoo.com", "#x-filter-modal")
        return {"has_attachments": first, "combined": second, "draft_counts": [5, 2]}
    await r.phase("combined-sender", "Attachment and sender filters combine and survive reload.", combined)
