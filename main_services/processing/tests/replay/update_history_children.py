"""The dynamic child workflow of `generate_update_histories.py`.

It is a module of its own because the workflow sandbox imports the module of each
workflow class, and the generator module reads files at import.
"""

from typing import Sequence

from temporalio import workflow
from temporalio.common import RawValue


@workflow.defn(dynamic=True)
class AnyChild:
    """Every child that a scenario does not run for real."""

    @workflow.run
    async def run(self, args: Sequence[RawValue]):
        # The plan stage workflows return a summary text. The other children return a dict.
        if workflow.info().workflow_type in TEXT_RESULTS:
            return "done"
        return {"steps": [], "plans_run": 0}


#: The children whose callers decode a `str` result.
TEXT_RESULTS = {"ExtractEntitiesForPlan", "ScanRegexEntitiesForPlan", "ChunkEmbedForPlan", "IndexDatasetPlan"}
