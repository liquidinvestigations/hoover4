"""Result pages: canonical JSON, the fixed-point test, continuations, allocation and the
four shape adapters. A fake counter stands in for `TokenCounter`, which talks to the live
tokenizer endpoint and is exercised where that endpoint exists."""

from __future__ import annotations

import json

import pytest

from agent_common import result_pages as rp


class FakeCounter:
    """One byte counts as one token. Deterministic, and enough to drive the adapters
    through their trimming loop without a network call."""

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


def _page_input(**overrides) -> rp.PageInput:
    defaults = dict(
        tool_name="search_collections",
        shape="rows",
        items=[{"path": f"doc-{i}.txt", "snippet": "x" * 20} for i in range(5)],
        columns=None,
        total_units=5,
        position_start={"offset": 0},
        source="fingerprint-1",
        input={"query": "q"},
        raw_artifact_id=None,
    )
    defaults.update(overrides)
    if "position_after" not in defaults:
        offset = defaults["position_start"]["offset"]
        total = defaults["total_units"]
        defaults["position_after"] = (
            lambda count: {"offset": offset + count} if offset + count < total else None
        )
    return rp.PageInput(**defaults)


# ----------------------------------------------------------------------------------
# canonical_json / is_canonical_page
# ----------------------------------------------------------------------------------


class TestCanonicalJson:
    def test_sorted_keys_and_compact_separators(self):
        assert rp.canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'

    def test_non_ascii_stays_unescaped(self):
        assert rp.canonical_json({"a": "café"}) == '{"a":"café"}'


class TestIsCanonicalPage:
    def test_true_for_a_built_page(self):
        text, _ = rp.build_page(_page_input(), rp.ByteLimit(10_000))
        assert rp.is_canonical_page(text)

    def test_false_after_one_byte_changes(self):
        text, _ = rp.build_page(_page_input(), rp.ByteLimit(10_000))
        # A trailing space is still valid JSON (json.loads tolerates it) but is not the
        # canonical form, which has no whitespace at all: this fails the fixed-point test
        # while a single-digit substitution elsewhere in the text would not.
        changed = text + " "
        assert rp.is_canonical_page(changed) is False

    def test_false_for_non_json(self):
        assert rp.is_canonical_page("not json") is False

    def test_false_for_a_different_kind(self):
        assert rp.is_canonical_page(rp.canonical_json({"kind": "something_else"})) is False

    def test_false_for_reordered_keys(self):
        # Valid JSON, valid kind, but not the sorted-key canonical form.
        text = json.dumps({"kind": "result_page", "b": 1, "a": 2})
        assert rp.is_canonical_page(text) is False


# ----------------------------------------------------------------------------------
# Continuation
# ----------------------------------------------------------------------------------


class TestContinuation:
    def test_round_trips(self):
        token = rp.encode_continuation(
            "table_page", {"sheet": "Sheet1"}, {"row": 40}, "fp-1", "artifact-x",
        )
        decoded = rp.decode_continuation(token)
        assert decoded == {
            "tool": "table_page",
            "input": {"sheet": "Sheet1"},
            "position": {"row": 40},
            "source": "fp-1",
        }

    def test_carries_no_raw_artifact_id(self):
        token = rp.encode_continuation("table_page", {}, {}, "fp-1", "artifact-x")
        padded = token + "=" * (-len(token) % 4)
        import base64

        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        assert "raw_artifact_id" not in payload

    def test_garbage_token_raises(self):
        with pytest.raises(rp.ContinuationInvalid):
            rp.decode_continuation("not-base64url-json!!")

    def test_valid_base64_wrong_shape_raises(self):
        import base64

        token = base64.urlsafe_b64encode(b'{"not":"a continuation"}').decode("ascii").rstrip("=")
        with pytest.raises(rp.ContinuationInvalid):
            rp.decode_continuation(token)


# ----------------------------------------------------------------------------------
# allocate()
# ----------------------------------------------------------------------------------


class TestAllocate:
    """Allocation keeps one completion reserve below the compaction threshold.

    H=157286, R=8192, max(U,P)=42000 and E=547. `allocate` derives A=H-R and uses
    `content_available = max(0, A - R - fixed)`. For two results, the total is
    42000 + 2*547 + 2*48904 + 8192 = 149094, which is 8192 below H.
    """

    def test_k_1(self):
        assert rp.allocate(42000, [547], 157286, 8192, None) == [98355]

    def test_k_2(self):
        assert rp.allocate(42000, [547, 547], 157286, 8192, None) == [48904, 48904]

    def test_k_3(self):
        assert rp.allocate(42000, [547, 547, 547], 157286, 8192, None) == [32420, 32420, 32420]

    def test_none_when_even_the_empty_messages_do_not_fit(self):
        # H=100, R=20, max(U,P)=50, K=4, E=9: fixed+R = 50+36+20 = 106 > A(=80).
        assert rp.allocate(50, [9, 9, 9, 9], 100, 20, None) is None

    def test_max_page_tokens_clamps_the_share(self):
        assert rp.allocate(42000, [547], 157286, 8192, 1000) == [1000]


# ----------------------------------------------------------------------------------
# build_page: rows / table
# ----------------------------------------------------------------------------------


class TestBuildPageRows:
    def test_everything_fits_no_continuation(self):
        text, measure = rp.build_page(_page_input(), rp.ByteLimit(10_000))
        envelope = json.loads(text)
        assert envelope["returned_units"] == 5
        assert envelope["total_units"] == 5
        assert envelope["continuation"] is None
        assert measure.truncated is False
        assert measure.status == "ok"

    def test_trims_whole_rows_and_sets_a_continuation(self):
        p = _page_input()
        # A budget too small for all five rows but big enough for at least one, once the
        # encoded continuation's own overhead is accounted for.
        text, measure = rp.build_page(p, rp.ByteLimit(400))
        envelope = json.loads(text)
        assert 0 < envelope["returned_units"] < 5
        assert envelope["continuation"] is not None
        assert measure.truncated is True
        decoded = rp.decode_continuation(envelope["continuation"])
        assert decoded["source"] == "fingerprint-1"
        assert decoded["position"] == {"offset": envelope["returned_units"]}

    def test_next_page_starts_after_the_returned_rows(self):
        rows = _page_input().items
        first_text, _ = rp.build_page(_page_input(), rp.ByteLimit(400))
        first = json.loads(first_text)
        offset = rp.decode_continuation(first["continuation"])["position"]["offset"]
        next_input = _page_input(items=rows[offset:], position_start={"offset": offset})
        next_text, _ = rp.build_page(next_input, rp.ByteLimit(10_000))
        second = json.loads(next_text)
        assert first["items"] + second["items"] == rows
        assert second["continuation"] is None

    def test_non_advancing_position_is_rejected(self):
        p = _page_input(position_after=lambda count: {"offset": 0})
        with pytest.raises(ValueError, match="advance"):
            rp.build_page(p, rp.ByteLimit(400))

    def test_budget_too_small_for_one_row_is_budget_exhausted(self):
        text, measure = rp.build_page(_page_input(), rp.ByteLimit(10))
        envelope = json.loads(text)
        assert envelope["success"] is False
        assert envelope["status"] == "budget_exhausted"
        assert envelope["returned_units"] == 0
        assert envelope["continuation"] is None
        assert measure.status == "budget_exhausted"


class TestBuildPageTable:
    def test_columns_emitted_once(self):
        p = _page_input(
            shape="table",
            items=[{"row": i, "cells": ["a", "b"]} for i in range(3)],
            columns=[{"name": "a"}, {"name": "b"}],
            total_units=3,
        )
        text, _ = rp.build_page(p, rp.ByteLimit(10_000))
        envelope = json.loads(text)
        assert envelope["columns"] == [{"name": "a"}, {"name": "b"}]
        assert len(envelope["items"]) == 3


# ----------------------------------------------------------------------------------
# build_page: tree
# ----------------------------------------------------------------------------------


class TestBuildPageTree:
    def test_never_emits_an_orphan(self):
        # Parent-before-child order, as the adapter requires. Trimming from the end
        # must never keep node 4 (parent 3) while dropping node 3.
        nodes = [
            {"node_id": "root", "parent_id": None},
            {"node_id": "1", "parent_id": "root"},
            {"node_id": "2", "parent_id": "root"},
            {"node_id": "3", "parent_id": "1"},
            {"node_id": "4", "parent_id": "3"},
        ]
        p = _page_input(shape="tree", items=nodes, total_units=len(nodes))
        text, _ = rp.build_page(p, rp.ByteLimit(260))
        envelope = json.loads(text)
        kept_ids = {n["node_id"] for n in envelope["items"]}
        for node in envelope["items"]:
            parent = node["parent_id"]
            if parent is not None and any(n["node_id"] == parent for n in nodes):
                assert parent in kept_ids, (node, kept_ids)


# ----------------------------------------------------------------------------------
# build_page: blob
# ----------------------------------------------------------------------------------


class TestBuildPageBlob:
    def test_utf8_boundary_never_splits_a_multibyte_character(self):
        data = "café".encode("utf-8")  # c, a, f (1 byte each), then 'é' as 2 bytes
        assert len(data) == 5
        assert rp._utf8_boundary(data, 4) == 3  # index 4 is 'é's second byte: back off
        assert rp._utf8_boundary(data, 5) == 5  # the whole string is a real boundary
        assert rp._utf8_boundary(data, 3) == 3  # already a boundary

    def test_a_trimmed_blob_decodes_cleanly_across_a_multibyte_cut(self):
        # 'café' repeats every 10 bytes, so any cut point in a wide budget range lands
        # near a multi-byte character somewhere in the string.
        text_value = ("a" * 5 + "café") * 60
        full_bytes = text_value.encode("utf-8")
        p = _page_input(
            shape="blob", items=[text_value], columns=None, total_units=len(full_bytes)
        )
        for budget in range(350, 780, 10):
            text, measure = rp.build_page(p, rp.ByteLimit(budget))
            envelope = json.loads(text)
            returned_text = envelope["items"][0] if envelope["items"] else ""
            # A cut that split 'café's two-byte 'é' would make this prefix check fail:
            # the truncated bytes would not equal a whole-character prefix of the source.
            assert full_bytes.startswith(returned_text.encode("utf-8"))
            assert measure.page_bytes <= budget

    def test_next_blob_page_starts_at_the_returned_utf8_byte(self):
        value = "café " * 60
        data = value.encode("utf-8")
        first_input = _page_input(shape="blob", items=[value], total_units=len(data))
        first_text, _ = rp.build_page(first_input, rp.ByteLimit(400))
        first = json.loads(first_text)
        offset = rp.decode_continuation(first["continuation"])["position"]["offset"]
        assert offset == len(first["items"][0].encode("utf-8"))
        next_input = _page_input(
            shape="blob", items=[data[offset:].decode("utf-8")],
            total_units=len(data), position_start={"offset": offset},
        )
        next_text, _ = rp.build_page(next_input, rp.ByteLimit(10_000))
        second = json.loads(next_text)
        assert first["items"][0] + second["items"][0] == value
        assert second["continuation"] is None

    def test_no_content_fits_is_budget_exhausted(self):
        p = _page_input(shape="blob", items=["hello world"], columns=None, total_units=11)
        text, measure = rp.build_page(p, rp.ByteLimit(5))
        envelope = json.loads(text)
        assert envelope["success"] is False
        assert envelope["status"] == "budget_exhausted"
        assert measure.status == "budget_exhausted"


# ----------------------------------------------------------------------------------
# Safe mode: one aggregate byte budget shared across a parallel batch
# ----------------------------------------------------------------------------------


class TestSafeModeBudget:
    def test_a_batch_of_three_stays_at_or_under_24000_bytes(self):
        results = [
            _page_input(
                tool_name=f"tool_{i}",
                items=[{"path": f"doc-{i}-{j}.txt", "snippet": "s" * 500} for j in range(40)],
                total_units=40,
                source=f"fp-{i}",
            )
            for i in range(3)
        ]
        # Reserve the empty envelope for each, then split what is left evenly, exactly
        # as the design's safe-mode section describes.
        empty_sizes = []
        for p in results:
            empty = rp._budget_exhausted_envelope(p.tool_name, p.shape, p.total_units, p.raw_artifact_id)
            empty_sizes.append(len(rp.canonical_page_bytes(empty)))
        remaining = rp.SAFE_MODE_BATCH_BYTES - sum(empty_sizes)
        share = remaining // len(results)

        total_bytes = 0
        for p in results:
            text, measure = rp.build_page(p, rp.ByteLimit(share))
            total_bytes += measure.page_bytes
        assert total_bytes <= rp.SAFE_MODE_BATCH_BYTES


# ----------------------------------------------------------------------------------
# TokenCounter (no network call; only URL derivation and failure classification here)
# ----------------------------------------------------------------------------------


class TestTokenizeUrl:
    def test_strips_trailing_v1(self):
        assert rp._tokenize_url("http://model:8000/v1") == "http://model:8000/tokenize"

    def test_no_v1_suffix_is_unchanged_but_appended(self):
        assert rp._tokenize_url("http://model:8000") == "http://model:8000/tokenize"
