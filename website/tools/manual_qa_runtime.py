"""Execute manual browser procedures with independent fixture expectations."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from pathlib import Path


FIND = 'input[placeholder="Search in document"]'
ABSENT = "qa-absent-7ce8421"


def cbor(value):
    """Encode the route value types used by the website."""
    def head(major, size):
        if size < 24:
            return bytes([major * 32 + size])
        for additional, width in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if size < 1 << (8 * width):
                return bytes([major * 32 + additional]) + size.to_bytes(width, "big")
        raise ValueError("route integer exceeds 64 bits")
    if value is None:
        return b"\xf6"
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if isinstance(value, int):
        return head(0 if value >= 0 else 1, value if value >= 0 else -1 - value)
    if isinstance(value, str):
        data = value.encode()
        return head(3, len(data)) + data
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor(item) for item in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(type(value).__name__)


def route(value):
    return base64.urlsafe_b64encode(cbor(value)).decode()


def unroute(value):
    data = memoryview(base64.urlsafe_b64decode(value))
    offset = 0
    def read():
        nonlocal offset
        first = data[offset]
        offset += 1
        major, size = first >> 5, first & 31
        if major == 7:
            return {20: False, 21: True, 22: None}[size]
        if size >= 24:
            width = {24: 1, 25: 2, 26: 4, 27: 8}[size]
            size = int.from_bytes(data[offset:offset + width], "big")
            offset += width
        if major == 0:
            return size
        if major == 1:
            return -size - 1
        if major == 3:
            text = bytes(data[offset:offset + size]).decode()
            offset += size
            return text
        if major == 4:
            return [read() for _ in range(size)]
        if major == 5:
            return {read(): read() for _ in range(size)}
        raise ValueError("unsupported route value")
    value = read()
    if offset != len(data):
        raise ValueError("route has trailing bytes")
    return value


def query(text="", datasets=None, **extra):
    selected = datasets if datasets is not None else ["testdata_manualqa"]
    return {"collection_datasets": selected, "query_string": text,
            "facet_filters": {"collection_dataset": [{"String": item} for item in selected]} if selected else {}, **extra}


def viewer_state(**extra):
    return {"find_query": "", "selected_source": None, "selected_source_page": None,
            "table_state": None, "selected_entity": None, **extra}


class UnmetPrerequisite(OSError):
    """Identify an unavailable expected fixture or comparison value."""


class Run:
    def __init__(self, tab, base, network, directory, stem, harness, profile, contract):
        self.tab, self.base, self.network = tab, base, network
        self.directory, self.stem, self.h = directory, stem, harness
        self.profile, self.contract = profile, contract
        self.phases, self.current = [], None

    def fixture(self, name):
        item = next(x for x in self.contract["fixtures"] if x["name"] == name)
        rows = self.profile["datasets"].get(item["dataset"], [])
        matches = [r for r in rows if r["path"] == item["path"]]
        if not matches:
            raise UnmetPrerequisite(f"fixture {name} has no resolved document")
        return item, {"collection_dataset": item["dataset"], "file_hash": matches[0]["hash"]}

    def save(self):
        target = self.directory / f"{self.stem}.procedures.json"
        pending = target.with_suffix(".pending")
        pending.write_text(json.dumps(self.phases, ensure_ascii=False, indent=2) + "\n")
        pending.replace(target)

    async def phase(self, name, expected, procedure):
        record = {"procedure": name, "expected": expected, "status": "running", "steps": [],
                  "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        self.phases.append(record)
        self.current = record
        self.save()
        try:
            record["observed"] = await procedure()
            record["status"] = "passed"
        except Exception as error:
            record["status"] = "unmet_prerequisite" if isinstance(error, UnmetPrerequisite) else "application_error"
            record["error"] = str(error)
            try:
                record["failure_state"] = await asyncio.wait_for(self.h.js_async(self.tab, """
const viewer=window.x_pdf_viewer, container=document.querySelector('#x-pdf-viewer');
const result={url:location.href,generation:window.x_pdf_viewer_generation,hasViewer:!!viewer,
containerChildren:container?.childElementCount,containerHTML:container?.innerHTML.slice(0,2000),
selectedSource:document.querySelector('[data-source-trigger=true]')?.innerText,
resources:performance.getEntriesByType('resource').filter(x=>/pdf|worker|wasm/i.test(x.name)).map(x=>({name:x.name,duration:x.duration,transferSize:x.transferSize,decodedBodySize:x.decodedBodySize}))};
if(viewer){
 try{const registry=await Promise.race([viewer.registry,new Promise((_,reject)=>setTimeout(()=>reject(Error('registry timeout')),2000))]);
 const documents=registry.getPlugin('document-manager')?.provides?.();
 result.activeDocumentId=documents?.getActiveDocumentId?.();
 result.documentState=documents?.getDocumentState?.('x-pdf-viewer-doc-id');
 }catch(error){result.registryError=String(error);}
}
return result;
"""), 5)
            except Exception as diagnostic_error:
                record["failure_state_error"] = str(diagnostic_error)
        except asyncio.CancelledError:
            record.update(status="incomplete_execution", error="The procedure exceeded its capture time budget.")
            raise
        finally:
            try:
                evidence = f"{self.stem}.{len(self.phases):02d}"
                (self.directory / f"{evidence}.png").write_bytes(await self.h.screenshot(self.tab, False))
                snap = await self.h.snapshot(self.tab)
                (self.directory / f"{evidence}.snapshot.json").write_text(json.dumps(snap, indent=2, ensure_ascii=False))
                record["evidence"] = evidence
            except Exception as error:
                record["evidence_error"] = str(error)
                record["status"] = "incomplete_execution"
            self.save()

    async def action(self, verb, argument=""):
        step = {"action": verb, "input": argument, "before_api": self.network.api_summary(), "status": "running"}
        self.current["steps"].append(step)
        self.save()
        try:
            previous_origin = await self.h.js(self.tab, "return performance.timeOrigin;") if verb == "goto" else None
            if verb == "async_eval":
                step["observed"] = await self.h.js_async(self.tab, argument)
            else:
                step["observed"] = await self.h.run_action(self.tab, self.base, verb, argument)
            if verb == "goto":
                await self.h.wait_eval(self.tab, "return performance.timeOrigin!==%s&&document.readyState==='complete';" % json.dumps(previous_origin))
                await self.h.wait_for_app_mounted(self.tab)
            step["status"] = "passed"
            return step["observed"]
        except Exception as error:
            step.update(status="failed", error=str(error))
            raise
        finally:
            step["after_api"] = self.network.api_summary()
            self.save()

    async def check(self, expression):
        return await self.action("wait_eval", expression)

    async def text(self, value, scope="body"):
        await self.action("wait_text_in", f"{scope} :: {value}")

    async def click(self, text, scope="body"):
        await self.text(text, scope)
        await self.action("click_text_in", f"{scope} :: {text}")

    async def type(self, selector, value, enter=False):
        await self.action("type_css", f"{selector} :: {value}")
        if enter:
            await self.action("press_enter")

    async def search(self, text="", datasets=None, **extra):
        await self.action("goto", f"/search/{route(query(text, datasets, **extra))}/0/9g==/9g==")
        await self.check("const e=document.querySelector('#x-search-panel-left-title-row h1');return {ok:!!e&&/documents? found|No documents/.test(e.textContent),text:e?.textContent};")

    async def full(self, name, **state):
        _, identity = self.fixture(name)
        await self.action("goto", f"/view_document/{route(identity)}/{route(viewer_state(**state))}/{route({'selected_tab':'Entities'})}")
        await self.action("wait_css", FIND)

    async def preview(self, name, text=""):
        item, identity = self.fixture(name)
        await self.search(text or Path(item["path"]).name, [item["dataset"]])
        return await self.select(name)

    async def select(self, name):
        _, identity = self.fixture(name)
        return await self.select_identity(identity)

    async def select_identity(self, identity):
        token = route(identity)
        selector = f'a[href^="/view_document/{token}/"]'
        await self.action("wait_css", selector)
        await self.action("eval", "const a=document.querySelector(%s);let e=a;while(e&&!e.style.height.includes('148px'))e=e.parentElement;if(!e)throw Error('result card unavailable');e.click();return {selected:e.innerText};" % json.dumps(selector))
        await self.action("wait_css", FIND)
        return identity

    def metadata(self):
        metadata = self.profile.get("metadata_oracle")
        if not metadata:
            raise UnmetPrerequisite("Refresh the source metadata oracle before browser execution.")
        return metadata

    async def identities(self):
        hrefs = await self.action("eval", "return [...document.querySelectorAll('#x-search-results-left-panel a[target=\"_blank\"][href^=\"/view_document/\"]')].map(a=>a.getAttribute('href'));")
        return [unroute(href.split('/')[2])["file_hash"] for href in hrefs]

    async def expected_results(self, hashes):
        expected = set(hashes)
        await self.count(len(expected))
        tokens = [route({"collection_dataset": "testdata_manualqa", "file_hash": file_hash}) for file_hash in expected]
        await self.check("const expected=%s;const actual=[...document.querySelectorAll('#x-search-results-left-panel a[target=\"_blank\"][href^=\"/view_document/\"]')].map(a=>a.getAttribute('href').split('/')[2]);return {ok:actual.length===Math.min(20,expected.length)&&actual.every(x=>expected.includes(x)),actual};" % json.dumps(tokens))
        actual = await self.identities()
        if not set(actual).issubset(expected) or (len(expected) <= 20 and set(actual) != expected):
            raise AssertionError(f"result identities differ: expected {sorted(expected)}, observed {actual}")
        return {"expected_count": len(expected), "expected_identities": sorted(expected), "visible_identities": actual}

    async def find(self, term, count):
        await self.type(FIND, term, True)
        label = f"1 / {count}" if count else "- / -"
        await self.text(label)
        return await self.check("const q=document.querySelector(%s);return {ok:q?.value===%s,query:q?.value};" % (json.dumps(FIND), json.dumps(term)))

    async def hit(self, direction, number, total):
        await self.action("eval", "const root=document.querySelector('#x-search-results-right-panel')||document;const h=[...root.querySelectorAll('h1,div')].find(x=>x.children.length===0&&/^\\d+ \\/ \\d+$/.test(x.textContent.trim()));if(!h)throw Error('hit counter unavailable');let p=h.parentElement;while(p&&p.querySelectorAll('button').length<2)p=p.parentElement;const b=p?.querySelectorAll('button')[%d];if(!b||b.disabled)throw Error('hit navigation unavailable');b.click();return {clicked:true};" % (1 if direction == "next" else 0))
        await self.text(f"{number} / {total}")

    async def pdf_source(self, label, preview=False):
        if preview:
            await self.action("click_css", '[data-source-trigger="true"]')
        selector = '[data-source-list="true"] [data-source-label=%s]' % json.dumps(label, ensure_ascii=False)
        await self.action("wait_css", selector)
        await self.action("click_css", selector)

    async def modal(self, category):
        await self.action("click_css", "#x-search-open-filters")
        await self.text("All filters")
        await self.click(category, "#x-filter-modal")

    async def apply(self):
        await self.click("Show", "#x-filter-modal")
        await self.check("return !document.querySelector('#x-filter-modal');")
        await self.check("const e=document.querySelector('#x-search-panel-left-title-row h1');return {ok:!!e&&/documents? found|No documents/.test(e.textContent),text:e?.textContent};")

    async def count(self, expected):
        return await self.check("const t=document.querySelector('#x-search-panel-left-title-row h1')?.textContent||'';const n=Number(t.replaceAll(',','').match(/\\d+/)?.[0]||0);return {ok:/documents? found|No documents/.test(t)&&n===%d,actual:n,expected:%d,text:t};" % (expected, expected))

    async def palette(self, selector):
        result = []
        for scheme in ("light", "dark"):
            await self.h.set_color_scheme(self.tab, scheme)
            result.append(await self.check("const e=document.querySelector(%s);if(!e)return false;const s=getComputedStyle(e),r=e.getBoundingClientRect();return {ok:r.width>0&&r.height>0&&s.color!==s.backgroundColor,scheme:%s,color:s.color,background:s.backgroundColor,width:r.width,height:r.height};" % (json.dumps(selector), json.dumps(scheme))))
        await self.h.set_color_scheme(self.tab, "")
        return result

    async def reload(self):
        origin = await self.action("eval", "return performance.timeOrigin;")
        await self.action("eval", "location.reload();return true;")
        await self.check("return performance.timeOrigin!==%s&&document.readyState==='complete';" % json.dumps(origin))
        await self.h.wait_for_app_mounted(self.tab)

    async def registered(self, name):
        page = next(p for p in self.h.parse_pages(Path(__file__).with_name("screenshots.ini")) if p.name == name)
        if page.init_script:
            await self.h.navigate_document(self.tab, self.base + page.url, page.init_script)
        else:
            await self.action("goto", page.url)
        for verb, argument in page.actions:
            if verb == "click_text":
                await self.text(argument)
            elif verb == "click_text_in":
                scope, _, needle = argument.partition("::")
                await self.text(needle.strip(), scope.strip())
            elif verb in ("click_css", "pointer_click_css"):
                await self.action("wait_css", argument)
            await self.action(verb, argument)

    async def popup(self, selector, expected_text, expected_values=()):
        import nodriver.cdp.target as target_cdp
        existing = {str(x.target_id) for x in await self.tab.send(target_cdp.get_targets())}
        parent_path = await self.h.js(self.tab, "return location.pathname;")
        await self.action("click_css", selector)
        child = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            await self.tab.browser.update_targets()
            children = [t for t in self.tab.browser.tabs if str(t.target_id) not in existing and t.target.type_ == "page"]
            if children:
                child = children[0]
                break
            await asyncio.sleep(.2)
        if child is None:
            raise RuntimeError("the document link did not open a new tab")
        try:
            await self.h.set_exact_viewport(child, *(await self.h.measured_viewport(self.tab)))
            await self.h.wait_text(child, expected_text)
            for value in expected_values:
                await self.h.wait_text(child, value)
            observed = await self.h.snapshot(child)
            filename = f"{self.stem}.popup-{len(self.phases)}-{len(self.current['steps'])}.png"
            (self.directory / filename).write_bytes(await self.h.screenshot(child, False))
            return {"child": observed, "screenshot": filename}
        finally:
            await child.close()
            await self.tab.activate()
            actual_path = await self.action("eval", "return location.pathname;")
            before, after = parent_path.split('/'), actual_path.split('/')
            state_index = 3 if before[1] == "view_document" else 5
            if before[:state_index] != after[:state_index]:
                raise AssertionError("opening the child changed the parent route or selected document")
            previous_state = unroute(before[state_index]) or viewer_state()
            current_state = unroute(after[state_index]) or viewer_state()
            if previous_state["find_query"] != current_state["find_query"]:
                raise AssertionError(f"opening the child changed the parent find query: {previous_state['find_query']!r} to {current_state['find_query']!r}")
            if previous_state.get("selected_source") and previous_state["selected_source"] != current_state["selected_source"]:
                raise AssertionError("opening the child changed the selected source")


async def shipping(r):
    async def baseline():
        await r.preview("shipping_manifest", "CSQU3054383")
        await r.find("is", 4)
        await r.hit("next", 2, 4)
        await r.hit("previous", 1, 4)
        return {"query": "CSQU3054383", "find_hits": 4}
    await r.phase("baseline", "The manifest is selected and document find navigates four occurrences.", baseline)
    await r.phase("keyboard-find", "Enter submits the find and next/previous change the counter.", baseline)
    async def popup():
        identity = await r.preview("shipping_manifest", "CSQU3054383")
        await r.find("is", 4)
        expected = next(x for x in r.contract["fixtures"] if x["name"] == "shipping_manifest")["expected"]["entity_values"]
        result = await r.popup(f'a[href^="/view_document/{route(identity)}/"]', "Entities", [x["value"] for x in expected])
        await r.text("1 / 4")
        result["expected_entities"] = expected
        text = "\n".join(result["child"]["lines"])
        missing = [x["value"] for x in expected if x["value"] not in text]
        if missing:
            raise AssertionError(f"entity values absent from full viewer: {missing}")
        return result
    await r.phase("popup-return", "The full viewer has the declared entities and the preview retains its find.", popup)
    async def no_match():
        await r.preview("shipping_manifest", "CSQU3054383")
        await r.find(ABSENT, 0)
        return await r.check("const p=document.querySelector('#x-search-results-right-panel');const counter=[...p.querySelectorAll('div')].find(e=>e.children.length===0&&e.textContent.trim()==='- / -');const buttons=[...counter.parentElement.querySelectorAll('button')];return {ok:!p.querySelector('.x-hit-span-active-match')&&buttons.length===2&&buttons.every(b=>b.disabled),query:document.querySelector(%s).value};" % json.dumps(FIND))
    await r.phase("no-match", "An absent term clears the active hit.", no_match)


async def mail_search(r):
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


async def size_filters(r):
    async def baseline():
        await r.search()
        await r.expected_results(x["hash"] for x in r.metadata()["files"])
        await r.preview("easychair_odt", "easychair")
        await r.find("Mac", 2)
        await r.modal("File size")
        await r.type('input[placeholder="min"]', "1")
        await r.type('input[placeholder="max"]', "10")
        await r.action("press_key", "Tab")
        await r.apply()
        await r.count(0)
        return await r.check("return {ok:!document.querySelector(%s),chips:document.querySelector('#x-filter-chips')?.innerText};" % json.dumps(FIND))
    await r.phase("baseline", "The selected ODT has two Mac hits. The size filter clears its preview and returns zero hits.", baseline)
    async def clear():
        await baseline()
        await r.action("eval", "const p=[...document.querySelectorAll('#x-filter-chips [title]')].find(x=>x.textContent.includes('Collections'));const b=p?.querySelector('button[title=\"Remove this filter\"]');if(!b)throw Error('collection chip remove control unavailable');b.click();return true;")
        await r.check("return document.querySelector('#x-filter-chips')?.innerText.includes('File size');")
        await r.click("Clear all", "#x-filter-chips")
        return await r.check("return {ok:!document.querySelector('#x-filter-chips')?.innerText.trim(),url:location.href};")
    await r.phase("find-zero-clear", "Removing Collections retains the size filter. Clear all removes every chip.", clear)
    async def reload():
        await baseline()
        before = await r.action("eval", "return location.pathname;")
        await r.reload()
        await r.count(0)
        await r.check("return location.pathname===%s;" % json.dumps(before))
        await r.modal("File size")
        return await r.check("return {ok:document.querySelector('input[placeholder=min]')?.value==='1'&&document.querySelector('input[placeholder=max]')?.value==='10'};")
    await r.phase("reload-persistence", "The applied size interval survives a reload.", reload)


async def type_filters(r):
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


async def dates(r):
    async def bounds(start="2001-01-01", end="2010-12-31"):
        await r.search()
        await r.modal("Date")
        await r.click("Between…", "#x-filter-modal")
        await r.type('#x-filter-modal input[type="date"]:first-of-type', start)
        await r.action("eval", "const es=[...document.querySelectorAll('#x-filter-modal input[type=date]')];if(es.length!==2)throw Error('date inputs unavailable');es[1].id='qa-date-end';return true;")
        await r.type("#qa-date-end", end)
    async def baseline():
        from datetime import datetime, timezone
        start, end = "2001-01-01", "2010-12-31"
        await bounds(start, end)
        await r.apply()
        minimum = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
        maximum = int(datetime.fromisoformat(end).replace(tzinfo=timezone.utc).timestamp()) + 86399
        return await r.expected_results(x["hash"] for x in r.metadata()["dates"] if minimum <= int(x["date"]) <= maximum)
    await r.phase("baseline", "Each date-filter result has a confirmed source date within the inclusive bounds.", baseline)
    await r.phase("boundary-input", "Keyboard input applies both date boundaries.", baseline)
    async def reversed_dates():
        await bounds("2010-12-31", "2001-01-01")
        await r.text("The start date is after the end date.", "#x-filter-modal")
        await r.type("#qa-date-end", "2011-01-01")
        await r.apply()
        return await r.check("return !document.querySelector('.x-error-display');")
    await r.phase("reversed-dates", "An inverted interval displays an error and corrected bounds recover.", reversed_dates)


async def email_envelope(r, full=False):
    if full:
        await r.full("romanian_email")
    else:
        await r.preview("romanian_email", "canicula")
    await r.action("wait_css", ".x-email-details-toggle")
    await r.action("click_css", ".x-email-details-toggle")
    await r.action("wait_css", ".x-email-details-panel")
    expected = r.profile["source_expectations"]["romanian_email"]
    panel = await r.action("eval", "return document.querySelector('.x-email-details-panel').innerText;")
    for role, values in expected["envelope"].items():
        for address in values:
            value = address[1] if isinstance(address, list) else address.get("address", "") if isinstance(address, dict) else address
            if value and value not in panel:
                raise AssertionError(f"email {role} address absent: {value}")
    links = await r.action("eval", "return [...document.querySelectorAll('.x-email-attachment-card')].map(a=>({name:a.querySelector('div[title]').title,href:a.getAttribute('href')}));")
    if len(links) != 3:
        raise AssertionError(f"expected three attachments, observed {links}")
    for attachment in expected["attachments"]:
        actual = next((x for x in links if x["name"] == attachment["filename"]), None)
        if actual is None or unroute(actual["href"].split('/')[2])["file_hash"] != attachment["sha3_256"]:
            raise AssertionError(f"attachment identity differs: {attachment['filename']}")
    return {"envelope": panel, "attachments": links}


async def email_tabs(r):
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


async def email_viewer(r):
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


async def entity_filter(r):
    async def baseline():
        await r.search()
        await r.modal("Entities")
        await r.click("Location", "#x-filter-modal")
        await r.type('input[placeholder="Search location…"]', "Manchester")
        await r.click("Manchester", "#x-filter-modal")
        await r.apply()
        expected = {x["file_hash"] for x in r.metadata()["entities"] if x["entity_type"] in ("LOC", "loc", "location") and "Manchester" in x["entity_values"]}
        result = await r.expected_results(expected)
        await r.select("easychair_odt")
        await r.type(FIND, "Manchester", True)
        await r.check("return [...document.querySelectorAll('div')].some(x=>x.children.length===0&&/^1 \\/ [1-9]/.test(x.textContent));")
        return result
    await r.phase("baseline", "The exact Manchester entity selects only documents carrying that source entity.", baseline)
    await r.phase("exact-entity", "The ODT document find locates the selected entity.", baseline)
    async def no_match():
        await r.search()
        await r.modal("Entities")
        await r.click("Location", "#x-filter-modal")
        await r.type('input[placeholder="Search location…"]', ABSENT)
        await r.text("No", "#x-filter-modal")
        await r.click("Cancel", "#x-filter-modal")
        await r.modal("Entities")
        return await r.check("return {ok:!document.querySelector('#x-filter-chips')?.innerText.includes('Entities')};")
    await r.phase("entity-no-match", "An absent location creates no hidden selection.", no_match)
    async def appearance():
        await r.search()
        await r.modal("Entities")
        return await r.palette("#x-filter-modal")
    await r.phase("popover-appearance", "Entity controls render under both color preferences.", appearance)


async def sort_results(r, key):
    metadata = r.metadata()
    hashes = sorted({x["hash"] for x in metadata["files"]})
    def value(file_hash, descending):
        files = [x for x in metadata["files"] if x["hash"] == file_hash]
        if key == "FileSize":
            return max(int(x["file_size_bytes"]) for x in files)
        if key == "Name":
            return min(Path(x["path"]).name.strip().lower() for x in files)
        values = [int(x["date"]) for x in metadata["dates"] if x["hash"] == file_hash]
        return (max(values) if descending else min(values)) if values else -(1 << 63)
    async def ordered(descending):
        await r.search()
        await r.click("Sort", "#x-search-input-top-bar")
        await r.click("File size" if key == "FileSize" else key)
        direction = "descending" if descending else "ascending"
        opposite = "ascending" if descending else "descending"
        await r.action("eval", "const b=document.querySelector('button[aria-label=\"Sort direction: %s\"]');if(b)b.click();return true;" % opposite)
        await r.click("Search", "#x-search-input-top-bar")
        await r.count(len(hashes))
        expected = sorted(hashes, key=lambda h: value(h, descending), reverse=descending)
        actual = []
        for page_number in range((len(hashes) + 19) // 20):
            await r.check("const a=[...document.querySelectorAll('#x-search-results-left-panel a[target=\"_blank\"][href^=\"/view_document/\"]')];return a.length>0;")
            page = await r.identities()
            actual.extend(page)
            if page_number + 1 < (len(hashes) + 19) // 20:
                await r.action("eval", "const b=[...document.querySelectorAll('#x-search-panel-left-title-row button')].at(-1);if(!b||b.disabled)throw Error('next result page unavailable');b.click();return true;")
                await r.check("return location.pathname.split('/')[3]===%s;" % json.dumps(str(page_number + 1)))
                await r.check("return ![...document.querySelectorAll('#x-search-results-left-panel a[target=\"_blank\"][href^=\"/view_document/\"]')].some(a=>a.getAttribute('href').includes(%s));" % json.dumps(route({"collection_dataset": "testdata_manualqa", "file_hash": page[0]})))
        if actual != expected:
            raise AssertionError(f"{key} {direction} order differs: expected {expected}, observed {actual}")
        await r.check("return !!document.querySelector('button[aria-label=\"Sort direction: %s\"]');" % direction)
        return {"direction": direction, "identities": actual, "source_values": [value(h, descending) for h in actual]}
    async def baseline():
        return [await ordered(False), await ordered(True)]
    await r.phase("baseline", "Every result follows source metadata order across page boundaries in both directions.", baseline)
    variation = {"Date": "both-directions", "FileSize": "cross-page-order", "Name": "name-comparator"}[key]
    await r.phase(variation, "Equal values use document identity order within the selected dataset.", baseline)
    async def persistence():
        observed = await ordered(True)
        before = await r.action("eval", "return location.pathname;")
        await r.reload()
        await r.check("return location.pathname===%s;" % json.dumps(before))
        await r.check("return !!document.querySelector('button[aria-label=\"Sort direction: descending\"]');")
        if key == "FileSize":
            observed["metadata"] = []
            for file_hash in observed["identities"][:2]:
                identity = {"collection_dataset": "testdata_manualqa", "file_hash": file_hash}
                await r.action("goto", f"/view_document/{route(identity)}/9g==/{route({'selected_tab': 'Metadata'})}")
                expected_size = value(file_hash, True)
                observed["metadata"].append(await r.check("const cell=[...document.querySelectorAll('td')].find(e=>e.textContent.trim()==='blob_size_bytes');const size=Number(cell?.nextElementSibling?.textContent);return {ok:!!cell&&size===%s,size,expected:%s};" % (expected_size, expected_size)))
            await r.action("goto", before)
        return observed
    await r.phase("metadata-agreement" if key == "FileSize" else "reload-state" if key == "Date" else "state-persistence",
                  "Reload retains order. Size sorting also agrees with two document Metadata values.", persistence)


async def sort_dates(r):
    await sort_results(r, "Date")


async def sort_sizes(r):
    await sort_results(r, "FileSize")


async def sort_names(r):
    await sort_results(r, "Name")


async def relevance(r):
    async def baseline():
        await r.search("child")
        await r.click("Sort", "#x-search-input-top-bar")
        await r.click("Relevance")
        await r.action("eval", "const b=[...document.querySelectorAll('#x-search-input-top-bar button')].find(b=>b.textContent.trim()==='Search');if(b&&!b.disabled)b.click();return true;")
        await r.check("return document.querySelector('button[aria-label=\"Sort direction: descending\"]')?.disabled===true;")
        expected = [row["file_hash"] for row in r.metadata().get("raw_relevance", [])]
        if not expected:
            raise UnmetPrerequisite("Refresh the independent raw relevance-score oracle.")
        actual = await r.identities()
        if actual != expected:
            raise AssertionError(f"relevance differs from raw scores: expected {expected}, observed {actual}")
        await r.reload()
        await r.check("return document.querySelector('button[aria-label=\"Sort direction: descending\"]')?.disabled===true;")
        return {"identities": actual, "raw_scores": r.metadata()["raw_relevance"],
                "draft_first": "parent.zip", "prepared_parent_ordinal": actual.index(r.fixture("parent_archive")[1]["file_hash"]) + 1}
    await r.phase("baseline", "The child query follows independent raw relevance scores in descending order.", baseline)
    await r.phase("explicit-relevance", "Explicit relevance and reload retain descending order.", baseline)
    async def empty():
        await r.registered("qa-sort-empty-default")
        await r.registered("qa-sort-legacy-ascending-relevance")
        return {"current_and_legacy_direction": "descending"}
    await r.phase("empty-query", "Current and legacy empty relevance routes expose a disabled descending direction.", empty)


async def tables(r):
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
            page = next(p for p in r.h.parse_pages(Path(__file__).with_name("screenshots.ini")) if p.name == name)
            await r.h.set_color_scheme(r.tab, page.color_scheme)
            await r.registered(name)
        await r.h.set_color_scheme(r.tab, "")
        return {"geometry": True, "backdrop_hit_test": True, "single_modal": True, "palette": "light"}
    await r.phase("single-modal-and-palette", "Pointer hit testing prevents background activation and the modal retains the fixed palette.", modal)


async def pdf_state(r, count=7):
    deadline = time.monotonic() + 30
    state = None
    while time.monotonic() < deadline:
        state = await r.action("async_eval", """
const viewer=window.x_pdf_viewer;
if(!viewer)return {ready:false};
const registry=await viewer.registry;
const search=registry.getPlugin('search').provides().getState('x-pdf-viewer-doc-id');
const root=document.querySelector('embedpdf-container')?.shadowRoot;
const overlays=root?[...root.querySelectorAll('div')].filter(e=>e.style.mixBlendMode==='multiply').map(e=>{
 const b=e.getBoundingClientRect();return {color:getComputedStyle(e).backgroundColor,box:[b.x,b.y,b.width,b.height],visible:b.width>0&&b.height>0&&b.bottom>0&&b.top<innerHeight&&b.right>0&&b.left<innerWidth};
}):[];
return {ready:!!search,search,overlays};
""")
        if state.get("ready") and len(state.get("search", {}).get("results", [])) == count:
            if count == 0 or any(x["visible"] for x in state["overlays"]):
                return state
        await asyncio.sleep(.25)
    raise AssertionError(f"PDF search state or visible highlights did not become ready: {state}")


async def pdf(r):
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
        return await r.check("return {ok:!document.body.innerText.includes('PDF · OCR'),text:document.body.innerText};")
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


async def folder_route(r, dataset, path="/", container=""):
    await r.action("goto", f"/file_browser/{dataset}/{route({'container_hash':container,'path':path})}/9g==/9g==")
    await r.action("wait_css", 'input[placeholder="Search in folder…"]')


async def folder_search(r):
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


async def archive_viewer(r):
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


async def archive_storage(r):
    async def baseline():
        identity = await r.preview("directory_archive", "the-directory.zip")
        await r.action("eval", "const a=document.querySelector(%s);let row=a;while(row&&!row.style.height.includes('148px'))row=row.parentElement;const more=row?.querySelector('a')?.parentElement.querySelector('button');if(!more)throw Error('result more control unavailable');more.click();return true;" % json.dumps(f'a[href^="/view_document/{route(identity)}/"]'))
        await r.click("Open in File Browser")
        await r.check("return location.pathname.startsWith('/file_browser/');")
        await r.text("the-directory.zip")
        await r.click("the-directory.zip", "table")
        await r.check("return document.querySelectorAll('#x-storage-tree [aria-current=\"location\"]').length===1;")
        return await r.action("eval", "return {route:location.pathname,tree:document.querySelector('#x-storage-tree').innerText,listing:document.querySelector('table')?.innerText};")
    await r.phase("baseline", "The search action opens the archive location and the archive row enters its root.", baseline)
    await r.phase("search-handoff", "The selected archive and storage focus agree.", baseline)
    async def history():
        await baseline()
        before = await r.action("eval", "return location.pathname;")
        await r.action("history_back")
        await r.text("the-directory.zip")
        await r.action("history_forward")
        return await r.check("return {ok:location.pathname===%s,route:location.pathname};" % json.dumps(before))
    await r.phase("return-navigation", "Browser history returns to the archive route.", history)
    async def highlight():
        await r.registered("qa-storage-archive-highlight")
        return {"current_rows": 1}
    await r.phase("archive-highlight", "Exactly one tree row identifies the current archive.", highlight)


async def entities(r):
    async def baseline():
        await r.full("easychair_office")
        await r.action("wait_css", 'input[placeholder="Filter Entities ..."]')
        expected = r.profile.get("source_expectations", {}).get("easychair_entities")
        if not expected:
            raise UnmetPrerequisite("The Easychair entity-value and source-text count oracle is unavailable.")
        observed = []
        for item in expected:
            await r.type('input[placeholder="Filter Entities ..."]', item["value"])
            await r.text(item["value"])
            await r.check("const e=[...document.querySelectorAll('.x-entity-chip')].find(x=>x.title===%s);return {ok:!!e&&e.lastElementChild?.textContent.trim()===%s,text:e?.innerText};" % (json.dumps(item["value"]), json.dumps(str(item["count"]))))
            await r.action("click_css", '.x-entity-chip[title=%s]' % json.dumps(item["value"]))
            await r.check("return document.querySelector(%s)?.value.includes(%s);" % (json.dumps(FIND), json.dumps(item["value"])))
            await r.text(item["value"])
            observed.append(item)
            await r.action("press_key", "Escape")
        return observed
    await r.phase("baseline", "Known Easychair values and counts match the original DOCX text.", baseline)
    await r.phase("multiple-values", "Two selected entity values open their own cards and counts.", baseline)
    async def stale():
        await r.full("easychair_office", selected_entity=ABSENT)
        await r.text("has no entity")
        return {"missing_value": ABSENT}
    await r.phase("stale-entity", "An absent selected entity produces the explicit missing-value state.", stale)
    async def appearance():
        await r.full("easychair_office")
        await r.action("wait_css", ".x-entity-chip")
        await r.action("click_css", ".x-entity-chip")
        return await r.palette('.x-entity-chip')
    await r.phase("appearance", "Entity values and cards render under both color preferences.", appearance)


async def tree(r):
    async def baseline():
        await r.registered("storage-shapes-deep")
        await r.registered("qa-storage-warm-navigation")
        return {"deep_chain": True, "warm_ancestor_retained": True}
    await r.phase("baseline", "Deep routes expand the tree and warm archive navigation retains its ancestor.", baseline)
    async def two_datasets():
        await r.registered("qa-storage-cold-expansion")
        zips_state = await r.action("eval", "const btn=document.querySelector('#x-tree-d-testdata_zips'); return {ok:!!btn, aria:btn&&btn.getAttribute('aria-expanded'), already:window.__qa_zips_expand||null, locationReady:[...document.querySelectorAll('#x-storage-tree [data-node-key]')].some(x=>x.title==='/location-1'||x.title.endsWith('/location-1'))};")
        await r.click("location-1", "#x-storage-tree")
        await r.action("history_back")
        both = await r.check("const keys=[...document.querySelectorAll('#x-storage-tree [data-node-key]')].map(e=>e.dataset.nodeKey);const zips=document.querySelector('#x-tree-d-testdata_zips');const shapes=document.querySelector('#x-tree-d-testdata_shapes');return {ok:!!zips&&!!shapes&&keys.some(x=>x.startsWith('testdata_shapes'))&&keys.some(x=>x.startsWith('testdata_zips')),visibleNodeKeys:keys,zipsExpanded:zips&&zips.getAttribute('aria-expanded'),shapesExpanded:shapes&&shapes.getAttribute('aria-expanded')};")
        both["expandState"] = zips_state
        return both
    await r.phase("two-datasets", "Both dataset controls remain available after expansion and history navigation.", two_datasets)
    async def keyboard():
        await folder_route(r, "testdata_shapes")
        await r.action("wait_css", "#x-tree-d-testdata_zips")
        await r.action("eval", "document.querySelector('#x-tree-d-testdata_zips').focus();return true;")
        await r.action("press_enter")
        await r.text("location-1", "#x-storage-tree")
        return await r.check("return {ok:document.activeElement?.id==='x-tree-d-testdata_zips',active:document.activeElement?.outerHTML};")
    await r.phase("keyboard-tree", "Enter activates the focused dataset disclosure once.", keyboard)
    async def narrow():
        original = await r.h.measured_viewport(r.tab)
        try:
            await r.h.set_exact_viewport(r.tab, 600, 900)
            await r.registered("storage-shapes-deep-600px")
            await r.reload()
            await r.action("wait_css", "#x-storage-tree [aria-current]")
            (r.directory / f"{r.stem}.narrow-600.png").write_bytes(await r.h.screenshot(r.tab, False))
            return await r.check("return {ok:document.documentElement.scrollWidth<=innerWidth,width:innerWidth,scrollWidth:document.documentElement.scrollWidth};")
        finally:
            await r.h.set_exact_viewport(r.tab, *original)
    await r.phase("reload-and-narrow-view", "The deep route remains inside a narrow viewport.", narrow)
    async def leaf():
        await r.registered("qa-storage-leaf-dataset")
        return {"disclosure": False, "navigation": True}
    await r.phase("leaf-disclosure", "A leaf dataset opens its root without a disclosure or empty-folder child message.", leaf)
    async def retained():
        await r.registered("storage-shapes-deep")
        await r.check("const rows=[...document.querySelectorAll('#x-storage-tree [data-node-key]')];const current=rows.find(x=>x.getAttribute('aria-current')==='location');return !!current&&rows.some(x=>current.title.startsWith(x.title+'/'));")
        await r.action("eval", "window.__qa_deep_route=location.pathname;window.__qa_deep_rows=[...document.querySelectorAll('#x-storage-tree [data-node-key]')];const current=window.__qa_deep_rows.find(x=>x.getAttribute('aria-current')==='location');window.__qa_deep_ancestors=window.__qa_deep_rows.filter(x=>current?.title.startsWith(x.title+'/'));window.__qa_deep_ancestor_keys=window.__qa_deep_ancestors.map(x=>x.dataset.nodeKey);window.__qa_deep_requests=performance.getEntriesByType('resource').filter(x=>x.name.includes('/api/vfs_tree_')).length;window.__qa_deep_queries=JSON.parse(document.querySelector('#x-vfs-query-log')?.textContent||'[]');return {rows:window.__qa_deep_rows.map(x=>({key:x.dataset.nodeKey,title:x.title})),ancestorKeys:window.__qa_deep_ancestor_keys};")
        await r.action("eval", "const rows=[...document.querySelectorAll('#x-storage-tree [data-node-key]')];const current=rows.find(x=>x.getAttribute('aria-current')==='location');const parent=rows.filter(x=>current?.title.startsWith(x.title+'/')).at(-1);if(!parent)throw Error('deep parent row unavailable');window.__qa_deep_current_title=current.title;window.__qa_deep_parent_title=parent.title;parent.click();return {parentKey:parent.dataset.nodeKey,parentTitle:parent.title};")
        await r.check("return location.pathname!==window.__qa_deep_route;")
        await r.check("return document.querySelector('#x-storage-tree [aria-current=location]')?.title===window.__qa_deep_parent_title;")
        await r.action("async_eval", "await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);return true;")
        await r.check("const rows=[...document.querySelectorAll('#x-storage-tree [data-node-key]')];const keys=new Set(rows.map(x=>x.dataset.nodeKey));return {ok:rows.some(x=>x.title===window.__qa_deep_parent_title)&&!rows.some(x=>x.title.startsWith(window.__qa_deep_current_title+'/'))&&window.__qa_deep_ancestor_keys.every(k=>keys.has(k)),visibleKeys:[...keys],ancestorKeys:window.__qa_deep_ancestor_keys};")
        await r.action("history_back")
        await r.check("return location.pathname===window.__qa_deep_route;")
        await r.check("return document.querySelector('#x-storage-tree [aria-current=location]')?.title===window.__qa_deep_current_title;")
        await r.action("async_eval", "await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);return true;")
        return await r.action("eval", "const common=window.__qa_deep_ancestors; const after=performance.getEntriesByType('resource').filter(x=>x.name.includes('/api/vfs_tree_')).length; const queries=JSON.parse(document.querySelector('#x-vfs-query-log')?.textContent||'[]'); const live=new Set([...document.querySelectorAll('#x-storage-tree [data-node-key]')].map(x=>x.dataset.nodeKey)); const result={ancestorKeys:window.__qa_deep_ancestor_keys,ancestors:common.map(x=>x.title),connected:common.map(x=>x.isConnected),requestsBefore:window.__qa_deep_requests,requestsAfter:after,datastoreQueriesBefore:window.__qa_deep_queries,datastoreQueriesAfter:queries}; if(!common.length) throw Error('no common ancestors: '+JSON.stringify(result)); if(common.some(x=>!x.isConnected)||window.__qa_deep_ancestor_keys.some(k=>!live.has(k))) throw Error('common ancestor identity lost: '+JSON.stringify(result)); return result;")
    await r.phase("cache-and-history", "Returning through a deep route retains common ancestor DOM nodes and records tree request counts.", retained)
    async def freshness():
        await r.registered("qa-storage-warm-navigation")
        return await r.action("eval", "const queries=JSON.parse(document.querySelector('#x-vfs-query-log')?.textContent||'[]'); const requests=performance.getEntriesByType('resource').filter(x=>x.name.includes('/api/vfs_tree_')).map(x=>({name:x.name,duration:x.duration})); const pathQueries=queries.filter(x=>x.kind==='path'); const childQueries=queries.filter(x=>x.kind==='children'); const cold=queries.filter(x=>!x.from_cache); const fresh=queries.filter(x=>x.from_cache); return {ok:true, browserRequests:requests.length, datastoreQueries:queries, coldDatastoreQueries:cold, freshCachedQueries:fresh, requestDurations:requests};")
    await r.phase("freshness-and-query-cost", "Warm archive navigation records browser requests and datastore query counts separately.", freshness)


async def run_procedure(name, tab, base, network, directory, stem, harness):
    profile_path = Path(__file__).with_name("manual_qa_profile.json")
    if not profile_path.is_file():
        raise UnmetPrerequisite("Run fixture preparation before the manual matrix.")
    profile = json.loads(profile_path.read_text())
    contract = json.loads(Path(__file__).with_name("manual_qa_fixtures.json").read_text())
    originals = Path(__file__).with_name("manual_qa_original_cases.json")
    if originals.is_file():
        profile["original_cases"] = json.loads(originals.read_text())
    procedure = PROCEDURES.get(name)
    if procedure is None:
        raise ValueError(f"unknown executable procedure {name}")
    run = Run(tab, base, network, directory, stem, harness, profile, contract)
    await procedure(run)
    failed = [p for p in run.phases if p["status"] != "passed"]
    if failed:
        message = "; ".join(f"{p['procedure']}: {p.get('error', p['status'])}" for p in failed)
        if any(p["status"] == "application_error" for p in failed):
            raise RuntimeError(message)
        raise UnmetPrerequisite(message)


PROCEDURES = {"manual-shipping": shipping, "manual-mail-search": mail_search,
              "manual-size-filters": size_filters, "manual-type-filters": type_filters,
              "manual-dates": dates, "manual-email-filters": email_tabs,
              "manual-entity-filter": entity_filter, "manual-email-viewer": email_viewer}
PROCEDURES.update({"manual-sort-dates": sort_dates, "manual-sort-size": sort_sizes,
                   "manual-sort-name": sort_names, "manual-relevance": relevance, "manual-table": tables,
                   "manual-pdf": pdf})
PROCEDURES.update({"manual-folder-search": folder_search, "manual-archive-viewer": archive_viewer,
                   "manual-archive-storage": archive_storage, "manual-entities": entities,
                   "manual-tree": tree})
