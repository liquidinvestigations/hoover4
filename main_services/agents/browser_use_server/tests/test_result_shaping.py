"""What the router does to a sidecar result before the model and the website see it.

Two things, and they exist for the same reason: a tool result travels to the transcript as
**text and nothing else**, so anything the card needs that is not in the text is lost.

1. the trailing artifact marker carries the capture ids *and* whether the call failed —
   Playwright reports failure as `is_error`, which does not survive, and its prose is
   indistinguishable from the page it was fetching;
2. links into the sidecar's own output directory are stripped — nobody downstream can
   open `.playwright-mcp/page-….yml`, so it renders as a dead link and invites the model
   to ask for a file it cannot have.
"""

from __future__ import annotations

import json

from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent

from browser_use_server.server import (
    ARTIFACT_MARKER,
    _append_marker,
    _attach_artifact,
    _drop_dead_links,
)


def _text(result: ToolResult) -> list[str]:
    return [b.text for b in result.content if isinstance(b, TextContent)]


def _marker_payload(result: ToolResult) -> dict:
    last = _text(result)[-1]
    assert last.startswith(ARTIFACT_MARKER)
    return json.loads(last[len(ARTIFACT_MARKER) :])


def _result(*texts: str) -> ToolResult:
    return ToolResult(content=[TextContent(type="text", text=t) for t in texts])


# --------------------------------------------------------------------------- marker


def test_marker_is_an_object_and_is_always_last():
    out = _append_marker(_result("### Page\n- Page URL: https://x.example/"), [])
    assert _text(out)[0].startswith("### Page")
    assert _marker_payload(out) == {"artifacts": []}


def test_a_failed_call_says_so_in_the_marker():
    # The whole point: the card cannot tell a refused navigation from a successful one by
    # reading the text, so it used to render "opened http://clickhouse:8123".
    out = _append_marker(_result("Error: net::ERR_PROXY_CONNECTION_FAILED"), [], failed=True)
    assert _marker_payload(out)["failed"] is True


def test_a_successful_call_carries_no_failed_key():
    # Written only when true: a flag on every result is ~10 tokens per browser call for
    # something the absence already says.
    assert "failed" not in _marker_payload(_append_marker(_result("ok"), []))


def test_the_capture_entry_rides_in_the_same_marker():
    class Captured:
        artifact_id = "6f1a3c2e-9b4d-4a71-8e0f-2c5d7a9b1e33"
        status = "ok"
        url = "https://x.example/"
        title = "X"
        detail = ""

    payload = _marker_payload(_attach_artifact(_result("### Page"), Captured()))
    assert payload["artifacts"][0]["artifact_id"] == Captured.artifact_id
    assert payload["artifacts"][0]["status"] == "ok"


def test_a_capture_that_produced_nothing_still_ends_with_a_marker():
    # The card authenticates the marker by its position, which only works if every result
    # this router returns has one — including the ones that captured nothing.
    assert _marker_payload(_attach_artifact(_result("### Console"), None)) == {"artifacts": []}


def test_the_structured_key_keeps_the_bare_array():
    # A client reading structured content has MCP's own `is_error` and needs no flag here.
    out = _append_marker(_result("x"), [{"artifact_id": "a"}], failed=True)
    assert out.structured_content["_hoover4_artifacts"] == [{"artifact_id": "a"}]


# ------------------------------------------------------------------------ dead links


def test_the_snapshot_file_link_is_removed_with_its_orphaned_heading():
    text = (
        "### Page\n- Page URL: https://example.com/\n- Page Title: Example Domain\n"
        "### Snapshot\n- [Snapshot](.playwright-mcp/page-2026-08-07T16-54-18-139Z.yml)"
    )
    out = _text(_drop_dead_links(_result(text)))[0]
    assert ".playwright-mcp" not in out
    # The heading went with it: "### Snapshot" over nothing reads as a missing snapshot.
    assert not out.endswith("### Snapshot")
    assert out.endswith("Example Domain")


def test_a_heading_with_real_content_under_it_survives():
    text = "### Page\n- Page URL: https://example.com/\n### Snapshot\n```yaml\n- generic\n```"
    assert _drop_dead_links(_result(text))
    assert "### Snapshot" in _text(_drop_dead_links(_result(text)))[0]


def test_page_text_that_merely_mentions_the_path_is_untouched():
    # The rule is anchored to a whole line that is only the link — the rest of a browser
    # result is the fetched page, and rewriting that would be rewriting evidence.
    text = "### Page\nthe article discusses .playwright-mcp/page-1.yml at length"
    assert _text(_drop_dead_links(_result(text)))[0] == text


def test_non_text_blocks_pass_through_untouched():
    from mcp.types import ImageContent

    image = ImageContent(type="image", data="AAAA", mimeType="image/png")
    out = _drop_dead_links(ToolResult(content=[image]))
    assert out.content == [image]


class TestCaptureIsExplicit:
    """D6: captures happen only when the model asked to look.

    Q4/Q5 answered "no implicit captures" and the router captured after seventeen tools
    anyway — a screenshot plus a multi-megabyte MHTML serialisation after almost every
    click. This is the kind of decision that gets quietly reverted by someone adding "just
    one more" tool to the set, so the *shape* of the rule is pinned here, not only its
    current membership.
    """

    def test_only_the_two_looking_tools_capture(self):
        from browser_use_server import capture as capture_mod

        assert capture_mod.CAPTURING_TOOLS == {"browser_take_screenshot", "browser_snapshot"}

    def test_navigation_and_interaction_do_not_capture(self):
        from browser_use_server.capture import should_capture

        for tool in [
            "browser_navigate",
            "browser_navigate_back",
            "browser_click",
            "browser_type",
            "browser_fill_form",
            "browser_press_key",
            "browser_hover",
            "browser_wait_for",
            "browser_tabs",
            "browser_evaluate",
            "browser_console_messages",
        ]:
            assert not should_capture(tool), f"{tool} must not capture implicitly"

    def test_the_two_looking_tools_do_capture(self):
        from browser_use_server.capture import should_capture

        assert should_capture("browser_take_screenshot")
        assert should_capture("browser_snapshot")

    def test_the_change_detection_reuse_machinery_is_gone(self):
        """Two artifacts pointing at one MinIO object is a retention hazard, and it only
        ever existed to make implicit captures affordable."""
        from browser_use_server.chat_browser import ChatBrowser

        chat = ChatBrowser(session_id="s", sidecar_port=1)
        for attr in ("last_capture_key", "last_body_key", "last_body_bytes"):
            assert not hasattr(chat, attr), f"{attr} outlived the implicit captures"
