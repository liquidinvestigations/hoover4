"""Manual procedure manual-sort-dates."""

from __future__ import annotations

from manual_qa_runtime import (
    sort_results,
)

PROCEDURE_NAME = 'manual-sort-dates'


async def run(r):
    await sort_results(r, "Date")
