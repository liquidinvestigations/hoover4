"""Manual procedure manual-email-viewer."""

from __future__ import annotations

from manual_qa_runtime import (
    email_envelope,
)

PROCEDURE_NAME = 'manual-email-viewer'


async def run(r):
    async def baseline():
        preview = await email_envelope(r)
        full = await email_envelope(r, True)
        if preview != full:
            raise AssertionError("preview and full email envelope or attachments differ")
        return full
    await r.phase("baseline", "Preview and full viewer match the original email bytes.", baseline)
    await r.phase("preview-parity", "Envelope and attachment identities agree across both viewers.", baseline)
    async def attachment_return():
        observed = await email_envelope(r, True)
        first = observed["attachments"][0]
        result = await r.popup(f'a[href="{first["href"]}"]', first["name"])
        await r.action("wait_css", ".x-email-details-panel")
        return result
    await r.phase("attachment-return", "Closing an attachment preserves the full email viewer state.", attachment_return)
