"""Measure PDF drag coordinates at each application zoom."""

from __future__ import annotations

import json

PROCEDURE_NAME = "pdf-pointer-selection"


async def run(r):
    async def measure():
        import nodriver.cdp.input_ as input_cdp

        original = await r.h.measured_viewport(r.tab)
        results = []
        try:
            for width in (1919, 1366):
                await r.h.set_exact_viewport(r.tab, width, 1080)
                for fixture in ("stanley_pdf_with_ocr", "born_digital_pdf_without_ocr"):
                    await r.full(fixture)
                    await r.action("wait_css", "#x-pdf-viewer embedpdf-container")
                    await r.action("async_eval", """
const registry=await window.x_pdf_viewer.registry;
const selection=registry.getPlugin('selection').provides().forDocument('x-pdf-viewer-doc-id');
window.__qa_marquees=[];
selection.setMarqueeEnabled(true);
selection.onMarqueeChange(event=>{if(event.rect)window.__qa_marquees.push(event)});
window.__qa_pdf_registry=registry;
return true;
""")
                    await r.check("const root=document.querySelector('embedpdf-container')?.shadowRoot;return [...(root?.querySelectorAll('img')||[])].some(e=>e.getBoundingClientRect().height>200);")
                    for fraction in (.15, .35, .55, .75):
                        points = await r.action("async_eval", """
const root=document.querySelector('embedpdf-container').shadowRoot;
const image=[...root.querySelectorAll('img')].find(e=>{const b=e.getBoundingClientRect();return b.width>100&&b.height>200&&b.top<innerHeight-200&&b.bottom>200});
if(!image)throw Error('No visible PDF page image');
const box=image.getBoundingClientRect();
const documents=window.__qa_pdf_registry.getPlugin('document-manager').provides();
const state=documents.getDocumentState('x-pdf-viewer-doc-id');
const page=state.document.pages[0];
const scale=box.width/page.size.width;
window.__qa_marquees=[];
const top=Math.max(box.top+30,120),bottom=Math.min(box.bottom-30,innerHeight-100);
return {x1:box.left+15,x2:box.left+35,y1:top+(bottom-top)*FRACTION,y2:top+(bottom-top)*FRACTION+15,box:{left:box.left,top:box.top,width:box.width},scale};
""".replace("FRACTION", str(fraction)))
                        common = {"pointer_type": "mouse", "button": input_cdp.MouseButton.LEFT}
                        await r.tab.send(input_cdp.dispatch_mouse_event(type_="mouseMoved", x=points["x1"], y=points["y1"], pointer_type="mouse"))
                        await r.tab.send(input_cdp.dispatch_mouse_event(type_="mousePressed", x=points["x1"], y=points["y1"], buttons=1, click_count=1, **common))
                        await r.tab.send(input_cdp.dispatch_mouse_event(type_="mouseMoved", x=points["x2"], y=points["y2"], buttons=1, **common))
                        await r.tab.send(input_cdp.dispatch_mouse_event(type_="mouseReleased", x=points["x2"], y=points["y2"], buttons=0, click_count=1, **common))
                        observed = await r.action("eval", """
const event=window.__qa_marquees.at(-1);
if(!event)throw Error('The PDF selection emitted no drag rectangle');
const expected=POINTS,rect=event.rect,scale=expected.scale;
const x=expected.box.left+(rect.origin.x+rect.size.width)*scale;
const y=expected.box.top+(rect.origin.y+rect.size.height)*scale;
const error=Math.max(Math.abs(x-expected.x2),Math.abs(y-expected.y2));
if(error>2)throw Error('The PDF selection differs from the pointer by '+error+' pixels');
return {pointer:[expected.x2,expected.y2],selection:[x,y],error,rect,pageIndex:event.pageIndex};
""".replace("POINTS", json.dumps(points)))
                        results.append({"width": width, "fixture": fixture, "height_fraction": fraction, **observed})
            return results
        finally:
            await r.h.set_exact_viewport(r.tab, *original)
    await r.phase("pointer-coordinate-measurement", "Sixteen PDF drags remain within two pixels of the pointer across two documents and two viewport widths.", measure)
