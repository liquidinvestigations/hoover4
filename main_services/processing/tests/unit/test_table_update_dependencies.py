"""Table updates retain exact generations and stop receipts after a failed dependency."""

import asyncio

import pytest

from tasks.P_admin.updates import workflows
from tasks.P_admin.updates.params import TablePlansParams


class Continued(Exception):
    def __init__(self, params):
        self.params = params


@pytest.mark.parametrize("failure", ["", "ChunkEmbedForPlan"])
def test_table_updates_run_text_dependencies_and_pin_every_receipt(monkeypatch, failure):
    children, receipts = [], []

    async def activity(name, arg=None, **kwargs):
        name = name if isinstance(name, str) else name.__name__
        if name == "list_update_table_plans":
            return ["plan"]
        if name == "prepare_table_update":
            return {"source": 7}
        if name == "record_table_update_receipts":
            receipts.append(arg)
        return None

    async def child(name, arg, **kwargs):
        children.append(name)
        assert arg["fail_on_errors"] is True
        assert arg["item_hashes"] == ["source"]
        if name == failure:
            raise RuntimeError("injected dependency failure")

    def continue_run(params):
        raise Continued(params)

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", child)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: True)
    monkeypatch.setattr(workflows.workflow, "wait", asyncio.wait)
    monkeypatch.setattr(workflows.workflow, "continue_as_new", continue_run)
    with pytest.raises(Continued) as continued:
        asyncio.run(workflows.UpdateDatasetTables().run(TablePlansParams("operation", "collection", "dataset")))
    expected = ["ExtractEntitiesForPlan", "ScanRegexEntitiesForPlan", "ChunkEmbedForPlan"]
    if not failure:
        expected.append("IndexDatasetPlan")
    assert children == expected
    assert all(receipt.generations == {"source": 7} for receipt in receipts)
    stages = [stage for receipt in receipts for stage in receipt.stages]
    assert stages == (["parse", "text", "entities", "regex"] if failure else
                      ["parse", "text", "entities", "regex", "embed", "index_text", "index_vectors"])
    assert continued.value.params.failed == int(bool(failure))
