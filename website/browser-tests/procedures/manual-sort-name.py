"""Manual procedure manual-sort-name."""

from __future__ import annotations

from manual_qa_runtime import (
    sort_results,
)

PROCEDURE_NAME = 'manual-sort-name'


async def run(r):
    await sort_results(r, "Name")
