"""Manual procedure manual-tree."""

from __future__ import annotations

from manual_qa_runtime import (
    folder_route,
    query,
    route,
)

PROCEDURE_NAME = 'manual-tree'


async def run(r):
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
