#!/usr/bin/env python3
"""Write the stored chat sessions that the chat screenshot cases open by name.

The named chat cases in `website/browser-tests/` open `{{chat_fixture:<name>}}`. This
script writes one session for each name, owned by one user, and prints the JSON map from
name to session id that `HOOVER4_SCREENSHOT_CHAT_FIXTURES` holds. It runs in the worker
container, which has the datastore clients and credentials. `prepare_chat_fixtures.sh`
runs it.

Each session id is derived from the name and the owner, so a second run writes the same
rows again. Every row has the time `FIXTURE_TIME`. The session list shows the newest
session first, and some cases open the newest session, so a fixture session must never
be the newest. A fixture session that a person deleted stays deleted, because the deletion
is newer, and the script then fails and names it. The rows have the shapes that the agent
service and the worker store. The documents that the rows name are in the `testdata`
collection of the hoover test data.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import uuid
from datetime import datetime

sys.path.insert(0, "/app")

FIXTURE_NAMESPACE = uuid.UUID("8f5d3c1e-3a57-4f0b-9a40-6a0f7b1f2c28")
DOC_HASH = "2ce1a51f0da95159ef2ea05b121c69545e6d1e9d8838fe3a93a84871e7d45924"
DOC_SHORT = DOC_HASH[:16]
DOC_PATH = "/sample (1).doc"
COLLECTION = "testdata"
DATASET = "testdata_testfiles"
SNIPPET = ("w, W energy density 1 erg/cm3 = 10^-1 J/m3. N, D demagnetizing factor. "
           "No vertical lines in table.")
# Longer than the 400 characters that a read card shows before its full-text control.
PAGE_TEXT = ("Template for Preparation of Papers for IEEE Sponsored Conferences & Symposia\n\n"
             "Abstract. These instructions give you guidelines for preparing papers for IEEE "
             "conferences. Use this document as a template if you are using Microsoft Word 6.0 "
             "or later. Otherwise, use this document as an instruction set. Instructions about "
             "final paper and figure submissions in this document are for IEEE journals.\n\n"
             "Table I lists units for magnetic properties. w, W energy density 1 erg/cm3 = "
             "10^-1 J/m3. N, D demagnetizing factor. No vertical lines in table.")
# The size of the first part of the continued read. The page text is ASCII.
PART_BYTES = 240


FIXTURE_TIME = datetime(2001, 1, 1)


def session_id(name: str, username: str) -> str:
    return hashlib.sha256(f"hoover4 chat fixture 2 {name} {username}".encode()).hexdigest()


def fixture_uuid(name: str, username: str, part: str) -> str:
    return str(uuid.uuid5(FIXTURE_NAMESPACE, f"{name}/{username}/{part}"))


def doc_ref(page_id=None, snippet: str = "") -> list[dict]:
    return [{"collection_dataset": DATASET, "file_hash": DOC_HASH, "collectionname": COLLECTION,
             "path": DOC_PATH, "page_id": page_id, "score": None, "snippet": snippet,
             "find_query": ""}]


def tool(name: str, args: dict, output, refs: list[dict] | None = None) -> dict:
    text = output if isinstance(output, str) else json.dumps(output)
    return {"role": "tool", "tool_name": name, "content": json.dumps(args),
            "tool_input": json.dumps(args), "tool_output": text,
            "doc_refs": json.dumps(refs) if refs else ""}


def user(text: str) -> dict:
    return {"role": "user", "content": text}


def answer(text: str) -> dict:
    return {"role": "assistant", "content": text}


def search_row() -> dict:
    return tool(
        "search_collections",
        {"collectionname": COLLECTION, "queries": ['"energy density"', "erg/cm3"]},
        {"items": [{"collectionname": COLLECTION, "date": "2007-10-10", "file_hash": DOC_SHORT,
                    "path": DOC_PATH, "q": [0, 1], "snippet": SNIPPET, "type": "doc"}]},
        doc_ref(snippet=SNIPPET),
    )


def cards(_name: str, _username: str) -> dict:
    quote = "energy density 1 erg/cm3 = 10^-1 J/m3"
    citation_refs = doc_ref()
    citation_refs[0].update(handle="[D1]", quote=quote, quote_verified=True,
                            find_query='"energy density"', term="")
    return {"title": "Browser fixture: tool cards", "rows": [
        user("Which testdata document gives the energy density conversion? Cite it."),
        search_row(),
        tool("read_documents",
             {"collectionname": COLLECTION, "file_hash": [DOC_SHORT], "page": 1,
              "find": "energy density"},
             {"items": [{"collectionname": COLLECTION, "file_hash": DOC_SHORT, "page": 1,
                         "min_page": 1, "max_page": 1, "path": DOC_PATH, "hit_count": 1,
                         "text": PAGE_TEXT}]},
             doc_ref(page_id=1)),
        tool("cite_documents",
             {"citations": [{"collectionname": COLLECTION, "file_hash": DOC_SHORT, "quote": quote,
                             "why": "The table gives the unit conversion for energy density."}]},
             {"citations": [{"file_hash": DOC_SHORT, "handle": "[D1]", "quote_verified": True}]},
             citation_refs),
        answer("The unit table in the sample document gives energy density as "
               "1 erg/cm3 = 10^-1 J/m3 [D1]."),
    ]}


def entities(_name: str, _username: str) -> dict:
    # The canonical page text that the collection server returns for this call.
    page = json.dumps(
        {"items": [{"collectionname": COLLECTION, "entities": {"organisation": ["IEEE"]},
                    "error": None, "file_hash": DOC_SHORT, "structured": [],
                    "success": True, "truncated": False}],
         "note": "One document was listed.", "success": True},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"title": "Browser fixture: document entities", "rows": [
        user("List the entities in the sample document."),
        search_row(),
        tool("list_document_entities",
             {"documents": [{"collectionname": COLLECTION, "file_hash": DOC_HASH}]},
             page, doc_ref()),
        answer("The sample document names IEEE."),
    ]}


def read_more(_name: str, _username: str) -> dict:
    handle = "f1a7c0de2b31"
    return {"title": "Browser fixture: continued read", "rows": [
        user("Read the sample document in the testdata collection to the end."),
        tool("read_documents",
             {"collectionname": COLLECTION, "file_hash": [DOC_SHORT], "page": 1},
             {"items": [{"collectionname": COLLECTION,
                         "cut": f"{PART_BYTES} of {len(PAGE_TEXT.encode())} bytes",
                         "file_hash": DOC_SHORT, "max_page": 1, "min_page": 1, "more": handle,
                         "page": 1, "path": DOC_PATH, "text": PAGE_TEXT[:PART_BYTES]}]},
             doc_ref(page_id=1)),
        tool("read_more", {"continuation": handle},
             {"continuation": handle, "text": PAGE_TEXT[PART_BYTES:], "more": None}),
        answer("The document is a paper template. Its unit table gives the energy density "
               "conversion."),
    ]}


def todo(name: str, username: str) -> dict:
    goal = "Summarise the unit table of the sample document."
    steps = ["Find the sample document.", "Read its unit table.", "Write the summary."]
    items_v1 = [{"id": str(i + 1), "text": s, "status": "pending", "note": ""}
                for i, s in enumerate(steps)]
    items_v2 = [dict(item, status="done" if item["id"] == "1" else item["status"])
                for item in items_v1]
    open_v2 = [{"id": i["id"], "text": i["text"], "status": i["status"]}
               for i in items_v2 if i["status"] != "done"]
    return {"title": "Browser fixture: todo list", "rows": [
        user("Plan the work, then summarise the unit table of the sample document."),
        tool("write_todo", {"goal": goal, "steps": steps},
             {"version": 1, "ids": ["1", "2", "3"], "summary": "0/3 items resolved"}),
        search_row(),
        tool("mark_todo", {"ids": ["1"], "status": "done"},
             {"version": 2, "summary": "1/3 items resolved", "open": open_v2}),
        answer("I found the sample document. The two other items are still open."),
    ], "todos": [(1, goal, items_v1), (2, goal, items_v2)]}


def web(name: str, username: str) -> dict:
    artifact_id = fixture_uuid(name, username, "search-detail")
    queries = ["IEEE conference paper template", "IEEE manuscript template units"]
    results = [
        {"title": "Manuscript templates for conference proceedings", "q": [0, 1],
         "url": "https://www.ieee.org/conferences/publishing/templates.html",
         "display_url": "www.ieee.org/conferences/publishing/templates.html",
         "snippet": "Templates for conference papers in Word and LaTeX formats.",
         "sources": ["duckduckgo", "brave"]},
        {"title": "Author guidelines", "q": [0],
         "url": "https://www.ieee.org/publications/authors.html",
         "display_url": "www.ieee.org/publications/authors.html",
         "snippet": "Guidelines for authors who prepare a manuscript.", "sources": ["brave"]},
    ]
    detail = {
        "before_rerank": results, "after_rerank": list(reversed(results)),
        "rerank_ms": 12.0, "rerank_applied": True, "total_before_dedupe": 3,
        "total_after_dedupe": 2, "degraded": [],
        "source_latency_ms": {"duckduckgo": 410.0, "brave": 380.0},
        "source_counts": {"duckduckgo": 1, "brave": 2},
    }
    output = {"success": True, "query": " ; ".join(queries), "queries": queries, "note": None,
              "results": results, "total_ms": 820.0,
              "_hoover4_artifacts": [{"artifact_id": artifact_id, "kind": "json",
                                      "tool_name": "web_search"}],
              "error": None}
    return {"title": "Browser fixture: web search", "internet": True, "rows": [
        user("Where does IEEE publish its conference paper templates?"),
        tool("web_search", {"queries": queries}, output),
        answer("IEEE publishes the templates on its conference publishing page."),
    ], "artifacts": [(artifact_id, "search_detail", "web_search", " ; ".join(queries), detail)]}


def compaction(_name: str, _username: str) -> dict:
    record = ("[Summary of earlier steps. Code wrote the lists of searches, documents, pages, "
              "continuations and citation labels. A model wrote the rest from the steps it "
              "replaces. The full steps are in the transcript. Read a source again before you "
              "quote it.]\n\n## Searches that found documents\n"
              '- search_collections ["\\"energy density\\"", "erg/cm3"]: 1 document\n\n'
              f"## Documents read\n- {COLLECTION}/{DOC_HASH} {DOC_PATH} page 1\n\n"
              "## Findings\nThe unit table gives energy density as 1 erg/cm3 = 10^-1 J/m3.\n")
    line = {"state": "done", "tokens_before": 218306, "target": 69905, "parts": 1,
            "tokens_after": 67636, "steps_summarised": 2, "target_reached": True,
            "record": record}
    return {"title": "Browser fixture: compacted context", "rows": [
        user("Which testdata document gives the energy density conversion?"),
        search_row(),
        {"role": "compaction", "content": json.dumps(line)},
        answer("The sample document gives the conversion in its unit table."),
    ]}


def question(name: str, username: str) -> dict:
    text = "Which period of the unit tables do you want the research to cover?"
    options = ["Tables from 2007", "All tables"]
    return {"title": "Browser fixture: chat question", "rows": [
        user("Research the unit tables in the testdata collection."),
        tool("ask_user", {"question": text, "options": options},
             {"success": True, "asked": True, "question": text, "options": options}),
        answer(text),
    ]}








FIXTURES = {
    "cards": cards,
    "entities": entities,
    "read_more": read_more,
    "todo": todo,
    "web": web,
    "compaction": compaction,
    "question": question,
}


def write_fixture(client, name: str, username: str, now: datetime) -> str:
    from database.clickhouse import insert_durable

    spec = FIXTURES[name](name, username)
    sid = session_id(name, username)
    turn = fixture_uuid(name, username, "turn")
    insert_durable(client, "chat_sessions", [[
        sid, username, spec["title"], [COLLECTION], "", int(spec.get("internet", False)),
        1, now, now, 0,
    ]], column_names=["session_id", "username", "title", "collections", "summary",
                      "use_internet_tools", "options_locked", "created_at",
                      "updated_at", "is_deleted"])
    rows = []
    for seq, row in enumerate(spec["rows"]):
        rows.append([
            sid, username, seq, row["role"], row.get("content", ""), row.get("tool_name", ""),
            row.get("tool_input", ""), row.get("tool_output", ""), row.get("doc_refs", ""),
            now, now, now, turn,
            json.dumps({"citation_status": "cited" if "[D1]" in row.get("content", "") else "none",
                        "tool_scope": "documents_and_web" if spec.get("internet") else "documents_only"})
            if row["role"] == "assistant" else "{}",
        ])
    insert_durable(client, "chat_messages", rows, column_names=[
        "session_id", "username", "seq", "role", "content", "tool_name", "tool_input",
        "tool_output", "doc_refs", "created_ms", "created_at", "updated_at", "message_uuid", "usage_json"])
    for version, goal, items in spec.get("todos", []):
        insert_durable(client, "chat_todos", [[sid, username, version, goal, json.dumps(items), now]],
                       column_names=["session_id", "username", "version", "goal", "items",
                                     "updated_at"])
    for artifact_id, kind, tool_name, title, detail in spec.get("artifacts", []):
        write_artifact(client, sid, username, artifact_id, kind, tool_name, title, detail, now)
    return sid


def write_artifact(client, sid, username, artifact_id, kind, tool_name, title, detail, now):
    from database import s3
    from database.clickhouse import insert_durable

    data = json.dumps(detail).encode()
    key = f"derived/chat-artifacts/{sid}/{artifact_id}/body.json"
    store = s3.get_s3_client()
    if not store.bucket_exists(s3.SYSTEM_BUCKET):
        store.make_bucket(s3.SYSTEM_BUCKET)
    store.put_object(s3.SYSTEM_BUCKET, key, io.BytesIO(data), length=len(data),
                     content_type="application/json")
    insert_durable(client, "chat_artifacts", [[
        artifact_id, sid, username, kind, tool_name, title, key, len(data), "ok",
        hashlib.sha256(data).hexdigest(), artifact_id, now, now, 0,
    ]], column_names=["artifact_id", "session_id", "username", "kind", "tool_name", "title",
                      "body_key", "body_bytes", "status", "body_sha256", "idempotency_key",
                      "created_at", "updated_at", "is_deleted"])




def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username", required=True,
                        help="the account that the screenshot run signs in as")
    parser.add_argument("--only", default="",
                        help="comma-separated fixture names, default every name")
    args = parser.parse_args()
    names = [n for n in args.only.split(",") if n] or list(FIXTURES)
    unknown = [n for n in names if n not in FIXTURES]
    if unknown:
        print(f"unknown fixture names: {', '.join(unknown)}", file=sys.stderr)
        return 2

    from database.clickhouse import get_global_client

    now = FIXTURE_TIME
    with get_global_client() as client:
        # The rows name one document of the test data. A stack without it still renders
        # the cards, but a link from a card opens no document, so the run says so.
        present = client.query(
            f"SELECT count() FROM Hoover4_Collection_{COLLECTION}.vfs_files FINAL "
            "WHERE hash = {h:String} AND is_deleted = 0", parameters={"h": DOC_HASH},
        ).result_rows[0][0] if client.query(
            "SELECT count() FROM collections FINAL WHERE collectionname = {c:String} "
            "AND is_deleted = 0", parameters={"c": COLLECTION}).result_rows[0][0] else 0
        if not present:
            print(f"warning: the {COLLECTION} collection has no document {DOC_PATH}",
                  file=sys.stderr)
        result = {name: write_fixture(client, name, args.username, now) for name in names}
        stored = {row[0] for row in client.query(
            "SELECT session_id FROM chat_sessions FINAL WHERE username = {u:String} "
            "AND session_id IN {s:Array(String)} AND is_deleted = 0",
            parameters={"u": args.username, "s": list(result.values())}).result_rows}
    deleted = sorted(name for name, sid in result.items() if sid not in stored)
    if deleted:
        print(f"deleted fixture sessions: {', '.join(deleted)}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
