"""The tool that ends an explore turn of an investigation board with its fact.

Only the `board` run kind has `submit_board_fact` (`agent_common.tool_packs`). A successful
call ends the turn, as `ask_user` does: the worker's `AgentRun` writes the fact text as the
answer of the turn, and the board reads the fact from the arguments of the call.
The optional `slug` is a name candidate. The board writer derives the permanent id of the
fact from it, adds the kind prefix and a collision suffix, and falls back to the fact text.

**Mirrored in `processing/tasks/P_board/model.py`** (`SUBMIT_FACT_TOOL`) and in the
website's tool card of the same name.
"""

from __future__ import annotations

import json
from typing import List, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, field_validator

SUBMIT_FACT = "submit_board_fact"

DESCRIPTION = (
    "Submit the finding of this board task and end the turn. Call it once, after the "
    "citation calls, with one paragraph that keeps the returned handles beside its claims. "
    "Use open_questions: [] when the task leaves no unresolved question. "
    "Known answers and source caveats are not open questions. "
    "A remaining question can be: Who approved the transfer? "
    "For kind not_found, name the searches and documents examined. "
    "For example: The searched committee minutes did not identify an approval date. "
    "Do not extend that absence to records you did not examine."
)


class SubmitFactArgs(BaseModel):
    fact: str = Field(
        min_length=1, max_length=4000,
        description="One paragraph with the finding. Put each returned handle, such as [D1], "
                    "beside the claim that it supports.")
    kind: Literal["sourced", "inferred", "not_found"] = Field(
        description="sourced: the cited documents state the finding. inferred: the finding "
                    "follows from them but no document states it. not_found: the searches "
                    "found no answer, and the fact names them.")
    open_questions: List[str] = Field(
        default_factory=list, max_length=3,
        description="At most three unresolved questions that this task leaves open. "
                    "Use [] when none remain. Exclude known answers and source caveats.")
    slug: str = Field(
        default="", max_length=80,
        description="Two to four lowercase English words that name the finding, joined by "
                    "hyphens, such as contract-payment-date.")

    @field_validator("open_questions")
    @classmethod
    def short_questions(cls, questions: List[str]) -> List[str]:
        if any(not 1 <= len(q) <= 300 for q in questions):
            raise ValueError("Each open question needs 1 to 300 characters.")
        return questions


def make_board_tools() -> List[StructuredTool]:
    async def submit_fact(fact: str, kind: str, open_questions: List[str] | None = None,
                          slug: str = "") -> str:
        return json.dumps({"success": True, "submitted": True, "kind": kind,
                           "open_questions": open_questions or []})

    return [StructuredTool.from_function(
        coroutine=submit_fact, name=SUBMIT_FACT, description=DESCRIPTION,
        args_schema=SubmitFactArgs, handle_tool_error=True)]


__all__ = ["DESCRIPTION", "SUBMIT_FACT", "SubmitFactArgs", "make_board_tools"]
