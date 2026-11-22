"""Verify the working files reported at compaction."""


def test_compaction_distinguishes_unknown_empty_and_saved_workspace():
    from research_agent.workspace_state import compaction_inventory

    assert "unavailable" in compaction_inventory(None)
    assert "no saved working files" in compaction_inventory([])
    record = compaction_inventory([{"name": "current-board.csv", "version": 3, "chars": 70}])
    assert "current-board.csv: version 3" in record
