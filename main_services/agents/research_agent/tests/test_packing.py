"""The packing numbers of `research_agent.packing`, and the planner skill that renders them."""

from __future__ import annotations

import pytest

from agent_common.tool_packs import allowed_tools
from research_agent import compaction, packing
from research_agent.skill_store import SkillContext, render_skill
from research_agent.skill_tools import read_skill_result


def test_two_classes_pack_by_the_larger_cost():
    found = packing.packing_for(("person", "topic"), 262_144)
    assert (found.leaf_tokens, found.leaves_per_subagent) == (20_548, 6)
    assert found.target_tokens == 157_286
    assert packing.sections_for(30, 6) == [8, 8, 7, 7]
    assert packing.sections_for(14, 6) == [5, 5, 4]


def test_the_default_window_one_class_and_the_cap_giving_way():
    assert packing.packing_for((), 0).leaves_per_subagent == 6
    assert packing.packing_for(("topic",), 262_144).leaves_per_subagent == 9
    assert packing.sections_for(45, 6) == [12, 11, 11, 11]
    assert packing.sections_for(9, 9) == [9]
    assert packing.sections_for(7, 6) == [4, 3]
    assert packing.sections_for(0, 6) == []


def test_a_small_window_keeps_one_task_and_a_large_one_stops_at_the_cap():
    assert packing.packing_for(("review",), 30_000).leaves_per_subagent == 1
    assert packing.packing_for(("topic",), 1_000_000).leaves_per_subagent == packing.LEAF_CAP


def test_at_most_two_classes_are_kept():
    assert packing.packing_for(("a", "b", "c"), 0).classes == ("a", "b")


def _planner(**extra):
    return SkillContext(profile="planner", tool_names=frozenset(allowed_tools(
        "planner", "collections,web,plan")), **extra)


def test_the_planner_skill_renders_the_numbers_of_its_classes():
    text = render_skill("method_planner", _planner(request_classes=("person", "topic")))
    assert "of the kind person and topic" in text
    assert "about 6 tasks" in text and "more than 24 tasks" in text
    assert "The plan tools refuse a fifth section." in text
    unknown = read_skill_result("method_planner", _planner())
    assert "of the kind unknown" in unknown and "about 6 tasks" in unknown


def test_a_model_id_reads_the_stated_window(monkeypatch):
    asked = []
    monkeypatch.setattr(compaction, "context_window",
                        lambda model: asked.append(model) or 131_072)
    text = render_skill("method_planner", _planner(request_classes=("topic",),
                                                   model_id="small-model"))
    assert asked == ["small-model"]
    # (0.60 x 131,072 - 16,000) // 14,296 is 4.
    assert "about 4 tasks" in text
    render_skill("method_planner", _planner(request_classes=("topic",)))
    assert asked == ["small-model"]


@pytest.mark.parametrize("name", ["method_planner", "method_organizer"])
def test_the_plan_skills_name_the_caps(name):
    text = render_skill(name, _planner() if name == "method_planner" else SkillContext(
        profile="organizer", tool_names=frozenset(allowed_tools("organizer", "all"))))
    assert "review" not in text.split("Research method")[0].lower()
    assert "4 sections" in text


def test_the_note_warning_matches_the_worker_copy():
    """The worker writes the warning from its own copy, whose test holds this literal."""
    assert compaction.NOTE_WARNING_TEXT.format(pct=90) == (
        "Your context is at 90 percent of its limit. The older steps of this run will soon be "
        "replaced by a record. Save each fact that you need later with `write_note` now. When "
        "`write_note` is not ready, call `read_tool` with the name `write_note` first. Then call "
        "`write_note` in your next reply.")
