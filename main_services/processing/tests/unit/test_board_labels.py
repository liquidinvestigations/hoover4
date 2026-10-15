"""The labels of board nodes and the board summary: checks, slugs, pending set, attempts.

The functions under test are pure, except `board_plan`, which runs with its storage
replaced by the rows built here.
"""

import json
from datetime import datetime, timedelta

from database.boards import BoardRow, EventRow, FactRow, LabelRow
from tasks.P_board import activities
from tasks.P_board import labels as lb
from tasks.P_board import model as m
from tasks.P_board.contracts import parse_board_summary, parse_labels
from tasks.P_board.fold import fold
from board_store_fake import FakeBoardStore

T0 = datetime(2026, 10, 14, 8, 0, 0)


def board(board_id="b1") -> BoardRow:
    return BoardRow(board_id=board_id, owner="admin", title="t", goal="g", collections=["enron"],
                    created_at=T0)


def events(board_id="b1", rejected=()):
    out = [EventRow(board_id, "r1", m.REASON_STARTED, "dispatcher", "1", {}, T0),
           EventRow(board_id, "r2", m.REASON_RESULT, "reason", "1", {
               "outcome": "intents", "situation": {"facts": 0, "hints": 0, "rejected": 0},
               "intents": [{"from": ["origin"], "objective": "Find the Raptor emails",
                            "brief": "Search the collection."}]}, T0 + timedelta(seconds=1))]
    for i, fact_id in enumerate(rejected):
        out.append(EventRow(board_id, f"x{i}", m.FACT_REJECTED, "admin", fact_id, {"reason": "no"},
                            T0 + timedelta(seconds=5 + i)))
    return out


def facts(board_id="b1"):
    return [
        FactRow(board_id, "origin", m.ORIGIN, "The investigation searches enron.", created_at=T0),
        FactRow(board_id, "goal-2", m.GOAL, "Second goal text", created_at=T0),
        FactRow(board_id, "goal", m.GOAL, "Who approved the Raptor hedges?", created_at=T0),
        FactRow(board_id, "f1.1", m.SOURCED, "Kaminski refused the valuations [D1].",
                created_at=T0 + timedelta(seconds=2)),
        FactRow(board_id, "c1", m.CORRECTION, "The hedges failed in 2001.",
                created_at=T0 + timedelta(seconds=3)),
    ]


def nodes_of(board_id="b1", rejected=()):
    f = facts(board_id)
    folded = fold(board(board_id), events(board_id, rejected), f)
    return f, folded, lb.label_nodes(f, folded)


def row(node, slug="x", title="A Title", summary="s", attempts=0, model="dgemma", **kw):
    return LabelRow("b1", node.node_id, node.kind, slug, title, summary, node.source_hash, model,
                    attempts, **kw)


# ------------------------------------------------------------------------ the reply checks


def test_a_reply_is_cleaned_and_limited():
    reply = "<think>x</think>```json\n" + json.dumps({"labels": [
        {"id": "f1.1", "slug": "Fact: Raptor Credit-Capacity!! Drop now", "title": "Raptor   Credit Capacity Drops Sharply Today",
         "summary": " ".join(f"w{i}" for i in range(30))},
        {"id": "zz", "slug": "x", "title": "x", "summary": "x"},
        {"id": "i1.1", "slug": "", "title": "Find Raptor Emails", "summary": "Search them."},
        {"id": "c1", "slug": "a", "title": "", "summary": "no title"},
    ]}) + "\n```"
    parsed = parse_labels(reply, {"f1.1": "Kaminski refused", "i1.1": "Find the emails", "c1": "x"})
    assert set(parsed) == {"f1.1", "i1.1"}
    assert parsed["f1.1"]["slug"] == "raptor-credit-capacity-drop"
    assert parsed["f1.1"]["title"] == "Raptor Credit Capacity Drops Sharply"
    assert len(parsed["f1.1"]["summary"].split()) == 24
    assert parsed["i1.1"]["slug"] == "find-raptor-emails"


def test_a_slug_falls_back_to_the_source_words_and_a_reply_without_json_gives_nothing():
    parsed = parse_labels('{"labels": [{"id": "a", "slug": "!!", "title": "!!", "summary": "s"}]}',
                          {"a": "Enron Raptor hedges collapse"})
    assert parsed["a"]["slug"] == "enron-raptor-hedges"
    assert parse_labels("no json here", {"a": "x"}) == {}


def test_a_slug_keeps_at_most_forty_characters():
    parsed = parse_labels(json.dumps({"labels": [{"id": "a", "slug": "a" * 30 + " " + "b" * 30,
                                                  "title": "T", "summary": "s"}]}), {"a": "x"})
    assert parsed["a"]["slug"] == "a" * 30


def test_a_board_summary_is_one_line_of_at_most_twenty_words():
    assert parse_board_summary("<think>no</think>\nSummary: " + " ".join(["w"] * 30)) == " ".join(["w"] * 20)
    assert parse_board_summary("  \n") == ""


# --------------------------------------------------------------------------------- nodes


def test_origin_and_goals_are_never_pending_and_the_order_is_by_creation():
    _f, _folded, nodes = nodes_of()
    assert [(n.node_id, n.kind) for n in nodes] == [("i1.1", "intent"), ("f1.1", "fact"), ("c1", "correction")]
    assert nodes[1].source == "sourced fact\n\nKaminski refused the valuations."
    assert nodes[0].source == "Find the Raptor emails\n\nSearch the collection."


def test_the_pending_set_is_missing_empty_or_stale_rows():
    _f, _folded, nodes = nodes_of()
    intent, fact, correction = nodes
    labels = {intent.node_id: row(intent), fact.node_id: row(fact, slug=""),
              correction.node_id: LabelRow("b1", "c1", "correction", "s", "T", "s", "old-hash")}
    assert [n.node_id for n in lb.pending_nodes(nodes, labels)] == ["f1.1", "c1"]
    assert lb.pending_nodes(nodes, {n.node_id: row(n) for n in nodes}) == []


# --------------------------------------------------------------------------------- slugs


def test_a_duplicate_slug_gets_two_then_three_against_stored_and_batch_slugs():
    assert lb.unique_slug("fact-raptor", set()) == "fact-raptor"
    assert lb.unique_slug("fact-raptor", {"fact-raptor"}) == "fact-raptor-2"
    assert lb.unique_slug("fact-raptor", {"fact-raptor", "fact-raptor-2"}) == "fact-raptor-3"
    _f, _folded, nodes = nodes_of()
    intent, fact, correction = nodes
    stored = {"x": LabelRow("b1", "x", "fact", "fact-raptor", "T", "s", "h")}
    entry = {"slug": "raptor", "title": "T", "summary": "s"}
    other = lb.Node("f9.9", "fact", "sourced fact\n\nother", "other")
    rows = lb.node_rows("b1", [fact, other], stored, {"f1.1": entry, "f9.9": entry}, "dgemma")
    assert [r.slug for r in rows] == ["fact-raptor-2", "fact-raptor-3"]


def test_a_changed_source_keeps_its_slug_and_gets_a_new_title():
    _f, _folded, nodes = nodes_of()
    fact = nodes[1]
    old = LabelRow("b1", "f1.1", "fact", "fact-old-slug", "Old Title", "old", "stale-hash",
                   "dgemma", 0, created_at=T0)
    rows = lb.node_rows("b1", [fact], {"f1.1": old},
                        {"f1.1": {"slug": "new-words", "title": "New Title", "summary": "new"}}, "dgemma")
    assert (rows[0].slug, rows[0].title, rows[0].source_hash) == ("fact-old-slug", "New Title", fact.source_hash)
    assert rows[0].created_at == T0


# ------------------------------------------------------------------- attempts and fallback


def test_a_failed_attempt_counts_and_the_second_gives_the_fallback_label():
    _f, _folded, nodes = nodes_of()
    fact = nodes[1]
    first = lb.node_rows("b1", [fact], {}, {}, "dgemma")[0]
    assert (first.slug, first.attempts) == ("", 1)
    assert lb.pending_nodes([fact], {"f1.1": first}) == [fact]
    second = lb.node_rows("b1", [fact], {"f1.1": first}, {}, "dgemma")[0]
    assert second.model == lb.FALLBACK_MODEL and second.attempts == 0
    assert second.slug == "fact-kaminski-refused-the"
    assert second.title == "Kaminski refused the valuations."
    assert lb.pending_nodes([fact], {"f1.1": second}) == []


def test_a_failure_of_a_labelled_node_keeps_its_label_and_stays_pending():
    _f, _folded, nodes = nodes_of()
    fact = nodes[1]
    old = LabelRow("b1", "f1.1", "fact", "fact-kept", "Kept Title", "kept", "stale", "dgemma", 0)
    failed = lb.node_rows("b1", [fact], {"f1.1": old}, {}, "dgemma")[0]
    assert (failed.slug, failed.title, failed.attempts) == ("fact-kept", "Kept Title", 1)
    assert lb.pending_nodes([fact], {"f1.1": failed}) == [fact]


def test_a_board_waits_after_a_failed_attempt():
    f, folded, nodes = nodes_of()
    failed = LabelRow("b1", "f1.1", "fact", "", "", "", "", "dgemma", 1, updated_at=T0)
    assert not lb.label_due(f, folded, [failed], (T0 + timedelta(seconds=30)).timestamp())
    assert lb.label_due(f, folded, [failed], (T0 + timedelta(seconds=61)).timestamp())


# ------------------------------------------------------------------------ board summary


def test_the_summary_source_holds_origin_goals_and_live_titles_in_order():
    f, folded, nodes = nodes_of(rejected=("f1.1",))
    labels = {n.node_id: row(n, title=f"Title {n.node_id}") for n in nodes}
    assert lb.summary_source(f, folded, nodes, labels).splitlines() == [
        "Origin: The investigation searches enron.",
        "Goal: Who approved the Raptor hedges?",
        "Goal: Second goal text",
        "Intent: Title i1.1",
        "Correction: Title c1",
    ]


def test_the_summary_is_due_when_missing_or_stale_and_not_before_the_nodes():
    f, folded, nodes = nodes_of()
    labels = [row(n) for n in nodes]
    now = (T0 + timedelta(hours=1)).timestamp()
    assert lb.label_due(f, folded, labels, now)
    source = lb.summary_source(f, folded, nodes, {r.node_id: r for r in labels})
    current = LabelRow("b1", "", "board", "", "", "A summary", lb.text_hash(source), "dgemma", 0,
                       updated_at=T0)
    assert not lb.label_due(f, folded, labels + [current], now)
    renamed = labels[:2] + [row(nodes[2], title="Another Title")]
    assert lb.label_due(f, folded, renamed + [current], now)


def test_the_summary_falls_back_to_the_first_goal_after_two_failures():
    f, _folded, _nodes = nodes_of()
    first = lb.summary_row("b1", f, None, "src", "", "dgemma")
    assert first.attempts == 1 and first.summary == ""
    second = lb.summary_row("b1", f, first, "src", "", "dgemma")
    assert second.summary == "Who approved the Raptor hedges?" and second.model == lb.FALLBACK_MODEL
    assert second.source_hash == lb.text_hash("src")
    ok = lb.summary_row("b1", f, None, "src", "Raptor hedges failed", "dgemma")
    assert (ok.summary, ok.attempts, ok.node_kind, ok.slug) == ("Raptor hedges failed", 0, "board", "")


# ---------------------------------------------------------------------- the dispatcher


def test_one_label_task_at_a_time():
    assert lb.labels_to_start(set(), ["b1", "b2"]) == ["b1"]
    assert lb.labels_to_start({"b9"}, ["b1"]) == []
    assert lb.labels_to_start(set(), []) == []


def test_board_plan_names_one_board_that_needs_labels(monkeypatch):
    store = FakeBoardStore().install(monkeypatch)
    for board_id in ("b1", "b2"):
        store.add_board(board_id, created_at=T0 if board_id == "b1" else T0 + timedelta(hours=1))
        store.write_events(events(board_id))
        store.publish_facts(facts(board_id), [])
    monkeypatch.setattr(activities, "_cap", lambda: 0)
    monkeypatch.setattr(activities, "_reconcile", lambda stale: [])
    output = activities.board_plan(activities.PlanInput())
    assert output.labels == ["b1"]
    store.submit("b1", "hint-1", "add_hint", "admin", {"text": "h"})
    output = activities.board_plan(activities.PlanInput())
    assert output.labels == ["b2"], "a board with a waiting command gets no label task"
    assert output.command_boards == ["b1"]


def test_an_old_plan_output_decodes_without_labels():
    from temporalio.converter import DataConverter

    payload = DataConverter.default.payload_converter.to_payloads(
        [{"reasons": [], "explores": [], "cancels": []}])
    decoded = DataConverter.default.payload_converter.from_payloads(payload, [activities.PlanOutput])
    assert decoded[0].labels == []
