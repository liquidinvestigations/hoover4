"""Replay a saved evidence and report operation in the WebAssembly runtime."""

import os
from pathlib import Path

import pytest

from research_agent import code_mode


@pytest.mark.skipif(not os.getenv("PLAN102_VERIFY_WASM"), reason="Requires the pinned JavaScript runtime.")
async def test_wasm_keeps_the_receipt_of_a_write_before_a_failure(monkeypatch):
    if os.getenv("PLAN102_JS_RUNNER"):
        monkeypatch.setattr(code_mode, "RUNNER", Path(os.environ["PLAN102_JS_RUNNER"]))
    async def invoke(name, args, ordinal):
        if name == "workspace_search":
            return {"matches": [{"text": "the verified claim"}]}, {"status": "ok"}
        assert name == "write_file" and ordinal == 1
        assert args == {"name": "report.md", "content": "the verified claim"}
        return {"version": 2}, {"status": "ok", "name": args["name"], "version": 2}

    result = await code_mode.run("javascript", """
        if (typeof require !== "undefined" || typeof process !== "undefined") throw Error("host");
        const hit = workspace_search({terms: ["verified"]});
        write_file({name: "report.md", content: hit.matches[0].text});
        throw Error("later failure");
    """, {"workspace_search", "write_file"}, invoke)
    assert result["success"] is False and result["error"] == "later failure"
    assert result["receipts"][-1] == {"tool": "write_file", "status": "ok", "name": "report.md", "version": 2}


@pytest.fixture
def real_runner(monkeypatch):
    if not os.getenv("PLAN102_VERIFY_WASM"):
        pytest.skip("Requires the pinned JavaScript runtime.")
    if os.getenv("PLAN102_JS_RUNNER"):
        monkeypatch.setattr(code_mode, "RUNNER", Path(os.environ["PLAN102_JS_RUNNER"]))


async def test_research_endpoint_direct_and_code_calls_share_scope(real_runner, monkeypatch):
    import json

    import httpx
    from langchain_core.tools import StructuredTool

    from research_agent import api, execution
    from research_agent.result_views import DISPLAY_LIMIT
    from test_steps import FakeAgent, tool_request

    files = {}
    calls = []

    def tool(name, properties, required, result):
        async def invoke(**args):
            headers = execution.page_share_client()
            calls.append((name, args, headers.headers.get(execution.IDEMPOTENCY_HEADER)))
            await headers.aclose()
            return json.dumps(result(args))

        return StructuredTool(name=name, description=name, coroutine=invoke, args_schema={
            "type": "object", "properties": properties, "required": required,
            "additionalProperties": False,
        })

    string = {"type": "string"}
    tools = [
        tool("read_file", {"path": string}, ["path"], lambda args: (
            {"text": files.get(args["path"], ""), "version": 2}
            if args["path"] != "other-chat" else {"success": False, "error": "The result is unavailable."}
        )),
        tool("write_file", {"name": string, "content": string}, ["name", "content"], lambda args: (
            files.update({args["name"]: args["content"]}) or
            {"name": args["name"], "version": 2, "success": True}
        )),
        tool("workspace_list", {}, [], lambda _: {"entries": []}),
    ]
    agent = FakeAgent(tools, {"search", "execute", "read_file", "write_file"})
    monkeypatch.setattr(api.app.state, "agent", agent, raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
        async def request(name, args):
            response = await client.post("/tool_call", json=tool_request(name, args).model_dump(mode="json"))
            assert response.is_success, response.text
            return response.json()

        discovery = json.loads((await request("search", {"detail": True}))["content"])
        assert {row["tool"] for row in discovery["matches"]} == {"read_file", "write_file"}
        result = json.loads((await request("execute", {"language": "javascript", "code": """
          if (typeof workspace_list !== "undefined" || typeof process !== "undefined") throw Error("scope");
          const refused = read_file({path:"other-chat"});
          if (refused.success !== false) throw Error("authorization");
          const saved = write_file({name:"shared.md",content:"verified"});
          return {saved, text:"x".repeat(25000)};
        """}))["content"])
        assert result["success"]
        assert result["receipts"][0]["status"] == "error" and result["receipts"][0]["error"]
        assert result["receipts"][1]["version"] == 2
        direct = json.loads((await request("read_file", {"path": "shared.md"}))["content"])
        assert direct["text"] == "verified"
        assert calls[-2][2].endswith("/execute/1")
        assert calls[-1][2] == "key-1"
        from research_agent.result_views import execution_view
        assert len(execution_view(result, None)) <= DISPLAY_LIMIT


async def test_wasm_timeout_keeps_completed_receipt(real_runner, monkeypatch):
    monkeypatch.setattr(code_mode, "TIMEOUT", 1)

    async def invoke(name, args, ordinal):
        assert (name, ordinal) == ("write_file", 0)
        return {"version": 3}, {"status": "ok", "name": args["name"], "version": 3}

    result = await code_mode.run("javascript", """
        write_file({name:"report.md",content:"saved"});
        while (true) {}
    """, {"write_file"}, invoke)
    assert not result["success"]
    assert result["receipts"][-1]["version"] == 3
