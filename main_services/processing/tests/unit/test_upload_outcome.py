"""The batch outcome of an upload: counters of manifest entries and the terminal state."""

import pytest

from database.uploads import (
    INGEST_REJECTION_PREFIX, OutcomeEvidence, classify_outcome, is_upload_part_name,
    outcome_error,
)


def _file(n, state, path=None, file_hash="", error=""):
    return {"file_no": n, "path": path or f"/in/f{n}", "state": state,
            "file_hash": file_hash, "error": error}


def _evidence(files, *, plans=None, failing=(), members=None, unpublished=()):
    """Evidence in which every ingested file is published and fully processed."""
    vfs, nodes, all_plans = {}, set(), {}
    for f in files:
        if f["state"] == "ingested":
            if f["path"] not in unpublished:
                vfs[f["path"]] = f["file_hash"]
                nodes.add(f["path"])
            all_plans[f["file_hash"]] = (1, 1)
    all_plans.update(plans or {})
    return OutcomeEvidence(vfs, nodes, members or {}, all_plans, failing)


def test_every_file_processed_and_published_is_completed():
    files = [_file(0, "ingested", file_hash="h0"), _file(1, "ingested", file_hash="h1")]
    counts = classify_outcome(files, _evidence(files))
    assert counts["state"] == "completed"
    assert counts["succeeded"] == counts["files"] == 2
    assert outcome_error(counts) == ""


def test_a_recovered_error_is_not_current_and_the_file_succeeds():
    # `current_error_hashes` drops an error that a later operation recovered, so the
    # hash is absent from `failing`.
    files = [_file(0, "ingested", file_hash="h0")]
    assert classify_outcome(files, _evidence(files, failing=()))["state"] == "completed"
    assert classify_outcome(files, _evidence(files, failing={"h0"}))["state"] == "failed"


def test_a_failed_archive_member_makes_its_archive_incomplete():
    files = [_file(0, "ingested", file_hash="zip"), _file(1, "ingested", file_hash="txt")]
    evidence = _evidence(files, members={"m1": "zip", "m2": "zip"},
                         plans={"m1": (1, 1), "m2": (1, 1)}, failing={"m2"})
    counts = classify_outcome(files, evidence)
    assert counts["state"] == "completed_with_errors"
    assert counts["succeeded"] == 1
    assert counts["current_errors"] == 1


def test_an_unfinished_member_plan_makes_its_archive_incomplete():
    files = [_file(0, "ingested", file_hash="zip")]
    evidence = _evidence(files, members={"m1": "zip"}, plans={"m1": (2, 1)})
    counts = classify_outcome(files, evidence)
    assert counts["processed"] == 0
    assert counts["state"] == "failed"


def test_a_batch_without_any_success_is_failed():
    files = [_file(0, "ingested", file_hash="h0"),
             _file(1, "rejected", error=INGEST_REJECTION_PREFIX + "Permission denied")]
    counts = classify_outcome(files, _evidence(files, failing={"h0"}))
    assert counts["state"] == "failed"
    assert counts["placed"] == 2
    assert counts["rejected"] == 1


def test_unsent_files_make_the_batch_incomplete():
    files = [_file(0, "ingested", file_hash="h0"), _file(1, "not_sent"), _file(2, "not_sent")]
    counts = classify_outcome(files, _evidence(files))
    assert counts["state"] == "completed_with_errors"
    assert counts["not_sent"] == 2
    assert outcome_error(counts).startswith("2 of 3 files did not complete: 2 not sent")


def test_duplicate_content_under_a_new_name_succeeds_once_published():
    files = [_file(0, "ingested", path="/a/copy.pdf", file_hash="same"),
             _file(1, "ingested", path="/b/copy.pdf", file_hash="same")]
    assert classify_outcome(files, _evidence(files))["state"] == "completed"
    # The same bytes without the published path of the second name do not count.
    counts = classify_outcome(files, _evidence(files, unpublished={"/b/copy.pdf"}))
    assert counts["state"] == "completed_with_errors"
    assert counts["published"] == 1


def test_a_supported_file_without_text_succeeds_when_its_plan_finished():
    # A blank image or an empty text file has a finished plan and no error. The outcome
    # reads no text table, so empty text is no failure.
    files = [_file(0, "ingested", file_hash="blank")]
    assert classify_outcome(files, _evidence(files))["state"] == "completed"


def test_an_ingested_file_without_a_plan_is_not_processed():
    files = [_file(0, "ingested", file_hash="h0")]
    counts = classify_outcome(files, _evidence(files, plans={"h0": (0, 0)}))
    assert counts["processed"] == 0 and counts["state"] == "failed"


@pytest.mark.parametrize("operation_state", ["errored", "cancelled", "missing"])
def test_an_ended_operation_fails_the_batch(operation_state):
    files = [_file(0, "ingested", file_hash="h0")]
    assert classify_outcome(files, _evidence(files), operation_state)["state"] == "failed"


def test_a_placed_file_not_yet_ingested_fails_the_batch():
    files = [_file(0, "ingested", file_hash="h0"), _file(1, "placed")]
    counts = classify_outcome(files, _evidence(files))
    assert counts["unaccounted"] == 1 and counts["state"] == "failed"


def test_no_placed_file_is_cancelled_and_website_rejections_are_not_placed():
    files = [_file(0, "rejected", error="The path exists in the dataset folder."),
             _file(1, "not_sent")]
    counts = classify_outcome(files, OutcomeEvidence())
    assert counts["placed"] == 0 and counts["state"] == "cancelled"


def test_counters_count_manifest_entries_once():
    files = [_file(0, "ingested", file_hash="zip")]
    evidence = _evidence(files, members={f"m{i}": "zip" for i in range(5)},
                         plans={f"m{i}": (1, 1) for i in range(5)},
                         failing={f"m{i}" for i in range(5)})
    counts = classify_outcome(files, evidence)
    assert counts["files"] == 1 and counts["current_errors"] == 1


@pytest.mark.parametrize("name, reserved", [
    (".hoover4-upload-0123abcd-7.hoover4-part", True),
    (".hoover4-upload-.hoover4-part", False),
    (".hoover4-upload-notes.txt", False),
    ("report.hoover4-part", False),
    ("report.pdf", False),
])
def test_only_the_complete_part_name_is_skipped_by_the_scan(name, reserved):
    assert is_upload_part_name(name) is reserved


class _VfsClient:
    """A client whose member query answers from `edges` (container, members), in the row
    order given, for the containers of the current level."""

    def __init__(self, edges):
        self.edges = edges
        self.frontier = set()

    def query(self, _sql, parameters=None, external_data=None):
        class _Result:
            pass

        result = _Result()
        result.result_rows = [(c, m) for c, members in self.edges for m in members
                              if c in self.frontier]
        return result


def _descend(edges, roots, monkeypatch):
    from database import uploads

    client = _VfsClient(edges)

    def fake_table(_name, _column, values):
        client.frontier = set(values)

    monkeypatch.setattr(uploads, "_string_table", fake_table)
    return uploads._descendants(client, "ds", roots)


def test_a_member_below_two_roots_belongs_to_the_smallest_root_in_any_row_order(monkeypatch):
    edges = [("rootB", ["shared", "onlyB"]), ("rootA", ["shared"])]
    for order in (edges, list(reversed(edges))):
        owner = _descend(order, ["rootA", "rootB"], monkeypatch)
        assert owner == {"shared": "rootA", "onlyB": "rootB"}


def test_a_member_belongs_to_the_root_that_reaches_it_at_the_lowest_level(monkeypatch):
    # rootA reaches `deep` at level 2 through `mid`, rootZ reaches it at level 1.
    edges = [("rootA", ["mid"]), ("mid", ["deep"]), ("rootZ", ["deep"])]
    owner = _descend(edges, ["rootA", "rootZ"], monkeypatch)
    assert owner == {"mid": "rootA", "deep": "rootZ"}


def test_a_root_below_another_root_stays_its_own_root(monkeypatch):
    edges = [("rootA", ["rootB", "x"]), ("rootB", ["y"])]
    owner = _descend(edges, ["rootA", "rootB"], monkeypatch)
    assert owner == {"x": "rootA", "y": "rootB"}
