"""Manual procedure manual-mail-search."""

from __future__ import annotations

import json

from manual_qa_runtime import (
    UnmetPrerequisite,
    route,
)

PROCEDURE_NAME = 'manual-mail-search'


async def run(r):
    async def baseline():
        await r.preview("enron_like_text_substitute", "hoover")
        await r.text("jeff.hoover@enron.com")
        await r.find("enron", 21)
        return {"substitute": True, "hits": 21, "draft_ordinal": 66}
    await r.phase("baseline", "The declared substitute contains the address and 21 Enron occurrences.", baseline)
    await r.phase("stable-identity", "Selection uses the pinned hash independently of result position.", baseline)
    async def page_return():
        original = r.profile.get("original_cases", {}).get("mail_page_return")
        if not original:
            raise UnmetPrerequisite("The original Enron corpus and its later-page document identity are unavailable.")
        identity = original["document"]
        ordinal = original["result_ordinal"]
        if not isinstance(ordinal, int) or ordinal <= 20 or not original.get("source_sha256"):
            raise UnmetPrerequisite("The original mail case needs a later-page ordinal and independently verified source provenance.")
        await r.search("hoover", [])
        for page_number in range((ordinal - 1) // 20):
            await r.action("eval", "const b=[...document.querySelectorAll('#x-search-panel-left-title-row button')].at(-1);if(!b||b.disabled)throw Error('next result page unavailable');b.click();return true;")
            await r.check("return location.pathname.split('/')[3]===%s;" % json.dumps(str(page_number + 1)))
        token = route(identity)
        await r.check("const links=[...document.querySelectorAll('#x-search-results-left-panel a[target=\"_blank\"][href^=\"/view_document/\"]')];return links[%d]?.getAttribute('href').split('/')[2]===%s;" % ((ordinal - 1) % 20, json.dumps(token)))
        await r.select_identity(identity)
        await r.find("hoover", 21)
        result = await r.popup(f'a[href^="/view_document/{token}/"]', "Entities")
        await r.text("1 / 21")
        result["expected_original"] = original
        return result
    await r.phase("page-return", "A later-page document returns through browser history.", page_return)
