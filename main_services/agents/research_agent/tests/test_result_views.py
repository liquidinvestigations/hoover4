"""Verify model paging without changing the broker's structured values."""

import json

from agent_common.workspace_results import DISPLAY_LIMIT, display
from research_agent.result_views import execution_view, workspace_view


def test_workspace_short_body_and_large_row_cursor():
    assert workspace_view("workspace_rows", '{"rows":[]}', {}) is None
    body = json.dumps({"path": "./tmp/a.csv", "version": 1,
                       "rows": [{"row": 8, "values": {"cell": "α" * 20000}}]})
    shown = workspace_view("workspace_rows", body, {"path": "./tmp/a.csv", "cursor": 8})
    assert len(shown) <= DISPLAY_LIMIT
    assert json.loads(shown)["next_call"]["arguments"] == {
        "path": "./tmp/a.csv", "cursor": 8, "limit": 1, "row_offset": 0,
    }
    assert len(json.loads(body)["rows"][0]["values"]["cell"]) == 20000


def test_large_search_page_advances_count_and_keeps_span():
    hits = [{"path": "sources/web/item", "version": "first", "start": i, "end": i + 3,
             "context": "α" * 7000} for i in range(5)]
    shown = workspace_view("workspace_search", json.dumps({"matches": hits}, ensure_ascii=False),
                           {"cursor": 5, "terms": ["a"]})
    assert len(shown) <= DISPLAY_LIMIT
    result = json.loads(shown)
    assert result["matches"][0]["start"] == 0
    assert result["next_cursor"] == 5 + len(result["matches"])


def test_oversized_controls_and_mixed_receipts_keep_the_model_limit():
    reference = {"path": "results/record", "version": "one", "source": {"items": ["a" * 30000]}}
    body = json.dumps({"success": False, "error": "a" * 50000, "citations": ["x" * 30000]})
    assert len(display(body, reference, DISPLAY_LIMIT)) <= DISPLAY_LIMIT
    receipts = [{"tool": "cite_pages", "status": "ok",
                 "citations": [{"handle": "[W1]", "quote": "a" * 20000}] * 12}] * 31 + [
        {"tool": "write_file", "status": "ok", "name": "report.md", "version": 3}
    ]
    shown = execution_view({"success": True, "output": "α" * 90000, "receipts": receipts}, reference)
    assert len(shown) <= DISPLAY_LIMIT
    parsed = json.loads(shown)
    assert any(row.get("name") == "report.md" and row["version"] == 3 for row in parsed["receipts"])
    assert parsed["result_ref"] == {"path": "results/record", "version": "one"}
