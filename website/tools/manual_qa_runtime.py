"""Execute manual browser procedures with independent fixture expectations."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
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
        page = next(
            p for p in self.h.load_scenario_pages(self.h.default_scenarios_path()) if p.name == name
        )
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


async def folder_route(r, dataset, path="/", container=""):
    await r.action("goto", f"/file_browser/{dataset}/{route({'container_hash':container,'path':path})}/9g==/9g==")
    await r.action("wait_css", 'input[placeholder="Search in folder…"]')


def _procedure_dir() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (
        here.parent / "browser-tests" / "procedures",
        here / "browser-tests" / "procedures",
    ):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("procedure files are missing beside the capture tools")


_PROCEDURES: dict[str, object] | None = None


def load_procedures() -> dict[str, object]:
    """Import each procedure module from website/browser-tests/procedures/."""
    global _PROCEDURES
    if _PROCEDURES is not None:
        return _PROCEDURES
    found: dict[str, object] = {}
    for path in sorted(_procedure_dir().glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(
            f"h4_procedure_{path.stem.replace('-', '_')}", path
        )
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"cannot load procedure {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        found[module.PROCEDURE_NAME] = module.run
    _PROCEDURES = found
    return found


async def run_procedure(name, tab, base, network, directory, stem, harness):
    profile_path = Path(__file__).with_name("manual_qa_profile.json")
    if not profile_path.is_file():
        raise UnmetPrerequisite("Run fixture preparation before the manual matrix.")
    profile = json.loads(profile_path.read_text())
    contract = json.loads(Path(__file__).with_name("manual_qa_fixtures.json").read_text())
    originals = Path(__file__).with_name("manual_qa_original_cases.json")
    if originals.is_file():
        profile["original_cases"] = json.loads(originals.read_text())
    procedure = load_procedures().get(name)
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


