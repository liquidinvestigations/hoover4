"""Verify saved passage recovery and typed scratch projections."""

from types import SimpleNamespace

from agent_todo_server import workspace_views


def test_unicode_match_recovers_the_middle_of_a_long_line(monkeypatch):
    text = "HEAD\n" + "α" * 8000 + "Founder Ada joined in May" + "終" * 8000 + "\nTAIL"
    path = "sources/web/example"
    scope = SimpleNamespace(username="reader", session_id="chat")
    monkeypatch.setattr(workspace_views, "body", lambda *_: ({"path": path, "version": "v1"}, text))
    result = workspace_views.search(scope, [], ["Ada joined"], [path], "", "any", False,
                                    "lines", True, 2, 0, 10)
    match = result["matches"][0]
    assert result["exhausted"]
    assert match["line"] == 2
    assert text[match["start"]:match["end"]] == "Ada joined"
    assert match["start"] > 8000
    assert match["version"] == "v1"


def test_jsonl_and_csv_keep_values_and_reach_exhaustion(monkeypatch):
    data = {
        "./tmp/rows.jsonl": '{"name":"Ada","key":2,"office":"Deputy"}\n{"name":"Grace","key":1}\n',
        "./tmp/rows.csv": 'name,note\r\nAda,"first, second\nthird"\r\n',
    }
    monkeypatch.setattr(workspace_views, "body",
                        lambda *_args: ({"path": _args[2], "version": 1}, data[_args[2]]))
    output = workspace_views.rows(None, [], "./tmp/rows.jsonl", 1, ["name"], [],
                                  [workspace_views.Sort(column="key")], 0, 1)
    assert output["rows"] == [{"row": 1, "values": {"name": "Grace"}}]
    assert output["next_cursor"] == "1"
    output = workspace_views.rows(None, [], "./tmp/rows.jsonl", 1, [], [],
                                  [workspace_views.Sort(column="key")], 1, 1)
    assert output["rows"][0]["values"]["key"] == 2 and output["next_cursor"] is None
    output = workspace_views.rows(None, [], "./tmp/rows.csv", 1, [], [], [], 0, 1)
    assert output["rows"][0]["values"]["note"] == "first, second\nthird"


def test_revoked_earlier_item_cannot_be_reopened_or_searched(monkeypatch):
    import pytest
    from fastmcp.exceptions import ToolError

    scope = SimpleNamespace(username="reader", session_id="chat")
    captured = SimpleNamespace(
        source={"items": [{"item_kind": "chat", "item_id": "revoked"}]},
        as_dict=lambda: {"path": "results/item", "version": "one", "kind": "execute"},
    )
    monkeypatch.setattr(workspace_views.workspace_results, "read",
                        lambda *_: (captured, "previously allowed evidence"))
    monkeypatch.delenv("AGENT_API_BASE_URL", raising=False)
    with pytest.raises(ToolError, match="source is unavailable"):
        workspace_views.body(scope, [], "results/item")
    with pytest.raises(ToolError, match="source is unavailable"):
        workspace_views.search(scope, [], ["evidence"], ["results/item"], "", "any",
                               False, "lines", True, 2, 0, 10)
