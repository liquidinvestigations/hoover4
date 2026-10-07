"""Verify wheel scrolling over both margins of the red flag terms page."""

PROCEDURE_NAME = "signal-terms-scroll"


async def run(r):
    async def scroll_margins():
        import nodriver.cdp.input_ as input_cdp

        results = []
        for side in ("left", "right"):
            point = await r.action("eval", """
const main=document.querySelector('main.x-signal-terms');
const content=main.querySelector('.x-signal-terms-content');
main.scrollTop=0;
const box=main.getBoundingClientRect(),column=content.getBoundingClientRect();
const x=SIDE==='left'?(box.left+column.left)/2:(column.right+box.right)/2;
const y=box.top+Math.min(200,box.height/2);
if(!(x>box.left&&x<box.right))throw Error('The wheel target is outside the page');
if(column.left-box.left<4||box.right-column.right<4)throw Error('The page has no outside margin');
return {x,y,side:SIDE};
""".replace("SIDE", repr(side)))
            await r.tab.send(input_cdp.dispatch_mouse_event(
                type_="mouseWheel", x=point["x"], y=point["y"], delta_x=0, delta_y=500,
            ))
            await r.check("return document.querySelector('main.x-signal-terms').scrollTop>0;")
            results.append(point)
        await r.action("eval", "document.querySelector('main.x-signal-terms').scrollTop=0;return true;")
        return results

    await r.phase("outside-column-wheel", "The page scrolls when the pointer is over either outside margin.", scroll_margins)
