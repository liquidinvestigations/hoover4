"""Verify source preservation and navigation removal in actual Chromium."""

import asyncio
import json

from browser_use_server import chat_browser, markdown_walker


def test_markdown_preserves_source_sections_and_removes_navigation():
    html = '''<html><body>
    <nav><a href="/home">Navigation home</a><a href="/account">Navigation account</a></nav>
    <main><h1>Source heading</h1><p>Required source passage.</p>
    <ul><li><a href="https://source.example/one">First source record</a></li>
    <li><a href="https://source.example/two">Second source record</a></li></ul>
    <table><caption>Required table caption</caption><tr><th>Name</th><th>Value</th></tr>
    <tr><td>Source value</td><td>42</td></tr></table>
    <div hidden><pre><code>required_code()</code></pre></div></main>
    <div class="sidebar"><p>Release date 2026-10-01.</p><p>Minimum Rust version 1.80.</p>
    <p>License MIT.</p><pre>cargo install source-package</pre>
    <button class="purl-copy-button">pkg:cargo/source@1.0</button>
    <button title="Copy command"><span class="selectable">cargo add source</span></button></div>
    <p aria-describedby="description">Source download</p>
    <div id="description" hidden>Required source description.</div>
    <footer>Navigation footer</footer></body></html>'''
    async def run():
        chat = await chat_browser.start("extraction-regression", sidecar=False)
        try:
            tab = await chat.browser.get("about:blank")
            script = "(() => { const doc = new DOMParser().parseFromString(" + json.dumps(html)
            script += ", 'text/html');" + markdown_walker.WALKER_JS
            script += "return {links:walk(doc,{links:true}), plain:walk(doc,{links:false})}; })()"
            from nodriver import cdp
            remote, exception = await tab.send(cdp.runtime.evaluate(
                expression=script, return_by_value=True, await_promise=True))
            assert exception is None
            return remote.value
        finally:
            await chat_browser.stop(chat)
    result = asyncio.run(run())
    for output in result.values():
        for required in ("Source heading", "Required source passage", "First source record",
                         "Second source record", "Required table caption", "Source value", "42",
                         "required_code()", "Release date", "Minimum Rust version", "License MIT",
                         "cargo install source-package", "pkg:cargo/source@1.0", "cargo add source", "Required source description"):
            assert required in output
        assert "Navigation" not in output
    assert "https://source.example/one" in result["links"]
    assert "https://source.example/one" not in result["plain"]
