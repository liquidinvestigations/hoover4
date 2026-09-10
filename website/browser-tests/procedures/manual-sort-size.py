"""Manual procedure manual-sort-size."""

from __future__ import annotations

from manual_qa_runtime import (
    sort_results,
)

PROCEDURE_NAME = 'manual-sort-size'


async def run(r):
    await sort_results(r, "FileSize")
