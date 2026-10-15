"""The tool that ends a board explore turn with its fact."""

import asyncio
import json

import pytest
from pydantic import ValidationError

from research_agent.board_tools import SUBMIT_FACT, SubmitFactArgs, make_board_tools


def test_a_valid_fact_is_submitted():
    [tool] = make_board_tools()
    assert tool.name == SUBMIT_FACT
    result = json.loads(asyncio.run(tool.coroutine(
        fact="Kaminski objected [D1].", kind="sourced", open_questions=["Who replied?"])))
    assert result["submitted"] is True and result["kind"] == "sourced"


def test_the_slug_is_optional():
    assert SubmitFactArgs(fact="x", kind="inferred").slug == ""
    assert SubmitFactArgs(fact="x", kind="inferred", slug="contract-payment").slug == "contract-payment"


@pytest.mark.parametrize("args", [
    {"fact": "", "kind": "sourced"},
    {"fact": "x", "kind": "maybe"},
    {"fact": "x", "kind": "inferred", "open_questions": ["a", "b", "c", "d"]},
    {"fact": "x", "kind": "inferred", "slug": "x" * 81},
])
def test_an_invalid_fact_is_refused(args):
    with pytest.raises(ValidationError):
        SubmitFactArgs(**args)
