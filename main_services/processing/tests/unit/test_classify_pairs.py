from tasks.P_admin.rerun_selection import classify_pairs


def test_classify_pairs_keeps_the_stage_check_before_plan_lookup():
    result = classify_pairs(
        [
            ("h1", "P4_ExtractEntities"),
            ("", "P3_ParseSingleFile"),
            ("h2", "extract_plaintext_chunks"),
            ("h1", "some_unknown_task"),
        ],
        {"h1": ["plan-1"]},
        lambda task_name: task_name == "P4_ExtractEntities",
    )

    assert result == {
        "removed_stage_off": [("h1", "P4_ExtractEntities")],
        "without_plan": [
            ("", "P3_ParseSingleFile"),
            ("h2", "extract_plaintext_chunks"),
        ],
        "selected": [("h1", "some_unknown_task")],
    }


def test_classify_pairs_selects_an_enabled_stage_with_a_plan():
    result = classify_pairs(
        [("h1", "P4_ExtractEntities")],
        {"h1": ["plan-1"]},
        lambda _task_name: False,
    )

    assert result["selected"] == [("h1", "P4_ExtractEntities")]
