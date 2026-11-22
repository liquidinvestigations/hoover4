"""Project elements from an archived browser page without running page code."""

from __future__ import annotations

from urllib.parse import urljoin

from agent_common import artifacts
from browser_use_server import page_citations

MAX_BODY = 64 * 1024 * 1024


def extract(owner, session, capture, selector, fields, cursor, limit):
    from selectolax.lexbor import LexborHTMLParser

    row = artifacts._artifact_row(capture)
    if row is None or row["username"] != owner or row["session_id"] != session:
        raise LookupError("The browser capture is unavailable.")
    rows = artifacts.query_rows(
        "SELECT url FROM chat_artifacts FINAL WHERE artifact_id = {id:String} "
        "AND username = {user:String} AND session_id = {session:String} "
        "AND kind = 'page_capture' AND is_deleted = 0 AND status = 'ok' LIMIT 1",
        id=capture, user=owner, session=session,
    )
    if not rows:
        raise LookupError("The browser capture has no saved page.")
    body, length = artifacts.read_range(owner, session, capture, 0, MAX_BODY)
    if length != len(body):
        raise LookupError("The stored page exceeds the extraction limit.")
    source = page_citations.captured_text(owner, session, capture)
    root = LexborHTMLParser(body)
    root.strip_tags(["script", "style", "noscript"])
    matched = root.css(selector)
    output = []
    for index, node in enumerate(matched[cursor:cursor + limit], start=cursor):
        values = {}
        for field in fields:
            if field == "text":
                values[field] = node.text(separator=" ", strip=True)[:4000]
            elif field == "tag":
                values[field] = node.tag
            elif field == "href" and node.attributes.get("href"):
                values[field] = urljoin(rows[0]["url"], node.attributes["href"])
            else:
                values[field] = node.attributes.get(field)
        row = {"row": index, "values": values}
        if source and values.get("text"):
            path, captured = source
            text = captured["markdown"]
            quote = values["text"]
            start = text.find(quote)
            if start >= 0 and text.find(quote, start + 1) < 0:
                row["evidence"] = {"path": f"sources/web/{path}", "version": captured["version"],
                                   "start": start, "end": start + len(quote)}
        output.append(row)
    return {"capture": capture, "url": rows[0]["url"], "rows": output, "matched_rows": len(matched),
            "next_cursor": cursor + limit if cursor + limit < len(matched) else None}
