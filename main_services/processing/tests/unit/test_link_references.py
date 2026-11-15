"""The References block of a person's text (`tasks.P_agent.link_references`)."""

import json

from tasks.P_agent import link_references as lr


def ref(n, label="x", **extra):
    return {"handle": f"[R{n}]", "kind": "document", "label": label, "tool": "read_documents",
            "arguments": {"collection": "c", "file_hash": ["h"]}, "url": "/view_document/a/b/c",
            "link": {"kind": "document"}, **extra}


def test_the_block_lists_the_named_references_in_handle_order():
    text = "Compare [R2] with [R1]. [R7] has no reference."
    out = lr.with_references(text, [ref(1, "a.pdf"), ref(2, "b.pdf"), ref(3, "unused")])
    head, block = out.split("\n\nReferences:\n")
    assert head == text
    lines = [json.loads(line) for line in block.splitlines()]
    assert [line["handle"] for line in lines] == ["[R1]", "[R2]"]
    assert lines[0] == {"handle": "[R1]", "kind": "document", "label": "a.pdf", "tool": "read_documents",
                        "arguments": {"collection": "c", "file_hash": ["h"]}}


def test_a_text_without_a_named_reference_is_unchanged():
    assert lr.with_references("No link here.", [ref(1)]) == "No link here."
    assert lr.with_references("[R1]", []) == "[R1]"


def test_a_note_is_kept_and_one_block_serves_several_texts():
    block = lr.block(["Goal [R1]", "Hint [R3]"], [ref(3, note="no argument for virus_hit"), ref(1), ref(2)])
    lines = [json.loads(line) for line in block.splitlines()[1:]]
    assert [line["handle"] for line in lines] == ["[R1]", "[R3]"]
    assert lines[1]["note"] == "no argument for virus_hit"


def test_shift_and_parse_follow_the_website_form():
    text, refs = lr.shifted("A [R1] and [R2], typed [R9]", [ref(1), ref(2)], 3)
    assert text == "A [R4] and [R5], typed [R9]" and [r["handle"] for r in refs] == ["[R4]", "[R5]"]
    assert lr.highest(refs) == 5 and lr.highest([]) == 0
    assert lr.rich("plain") == ("plain", [])
    assert lr.rich({"text": "t [R1]", "references": [ref(1)]}) == ("t [R1]", [ref(1)])
    assert lr.parse("") == [] and lr.parse("not json") == [] and lr.parse(json.dumps([ref(1)])) == [ref(1)]
    assert lr.dumps([]) == "" and json.loads(lr.dumps([ref(1)])) == [ref(1)]


def test_a_reference_marker_is_not_a_citation_handle():
    from tasks.P_agent import reports
    from tasks.P_workspace import references

    assert references.handles("See [R1] and [D2].") == [("[D2]", 1)]
    check = reports.check_labels("The lease [R1] is signed.", {}, [])
    assert not check["labels"] and not check["unresolved"]


def test_the_display_text_puts_each_label_in_place_of_its_marker():
    text = "Compare [R1] with [R2] and [R5]."
    refs = [ref(1, "a.pdf"), {**ref(2, ""), "url": "/ai_chat/boards/b"}]
    assert lr.display_text(text, refs) == "Compare a.pdf with /ai_chat/boards/b and [R5]."
