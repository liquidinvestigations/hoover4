"""The three batching mechanics, and the shapes models actually send."""

from __future__ import annotations

from agent_common import batching


class TestAsList:
    def test_a_real_list(self):
        assert batching.as_list(["a", "b"]) == ["a", "b"]

    def test_a_json_encoded_list(self):
        # What an XML-style tool-call parser hands across for every list parameter.
        assert batching.as_list('["a", "b"]') == ["a", "b"]

    def test_a_bare_string_is_a_one_element_list(self):
        assert batching.as_list("a") == ["a"]

    def test_a_separated_string(self):
        assert batching.as_list("a, b ,c") == ["a", "b", "c"]

    def test_blanks_are_dropped(self):
        assert batching.as_list(["a", "", "  ", "b"]) == ["a", "b"]

    def test_none_is_empty_not_none(self):
        assert batching.as_list(None) == []

    def test_truncated_json_still_yields_the_items(self):
        # A model that cut its own argument short must not have `["a"` reach a fetcher.
        assert batching.as_list('["a", "b"') == ["a", "b"]


class TestAsObjects:
    def test_a_real_list_of_objects(self):
        assert batching.as_objects([{"id": "a"}]) == [{"id": "a"}]

    def test_a_json_encoded_list(self):
        assert batching.as_objects('[{"id": "a"}, {"id": "b"}]') == [
            {"id": "a"},
            {"id": "b"},
        ]

    def test_a_lone_object_is_a_one_element_list(self):
        assert batching.as_objects({"id": "a"}) == [{"id": "a"}]

    def test_a_json_encoded_lone_object(self):
        assert batching.as_objects('{"id": "a"}') == [{"id": "a"}]

    def test_none_and_unparseable_text_are_empty(self):
        assert batching.as_objects(None) == []
        assert batching.as_objects("not json") == []
        assert batching.as_objects("") == []

    def test_a_non_object_member_is_kept_for_the_caller_to_refuse(self):
        # Dropping it here would leave the model believing it wrote a row nobody stored.
        assert batching.as_objects(["a", {"id": "b"}]) == ["a", {"id": "b"}]


class TestDedupe:
    def test_order_is_preserved_and_repeats_returned(self):
        kept, repeats = batching.dedupe(["a", "b", "A", "c", "b"])
        assert kept == ["a", "b", "c"]
        assert repeats == ["A", "b"]

    def test_case_sensitivity_is_optional(self):
        kept, _ = batching.dedupe(["a", "A"], casefold=False)
        assert kept == ["a", "A"]


class TestDivideBudget:
    def test_even_split(self):
        per, fits = batching.divide_budget(30000, 3)
        assert (per, fits) == (10000, 3)

    def test_never_divides_below_the_floor(self):
        # Ten items over 2000 characters would be 200 each, which carries nothing.
        per, fits = batching.divide_budget(2000, 10)
        assert per >= batching.MIN_ITEM_CHARS
        assert fits == 2000 // batching.MIN_ITEM_CHARS

    def test_nothing_to_divide(self):
        assert batching.divide_budget(0, 3) == (0, 0)
        assert batching.divide_budget(1000, 0) == (0, 0)


class TestTruncate:
    def test_under_the_limit_is_untouched(self):
        assert batching.truncate("hello", 100) == ("hello", False)

    def test_cuts_on_a_word_boundary(self):
        text, truncated = batching.truncate("alpha beta gamma delta", 14)
        assert truncated and not text.endswith("gam")


class TestNotes:
    def test_no_repeats_costs_nothing(self):
        assert batching.repeats_note([]) == ""

    def test_a_repeat_says_what_to_do_instead(self):
        note = batching.repeats_note(["enron"], "query")
        assert "enron" in note and "distinct" in note

    def test_corrective_note_drops_empties(self):
        assert batching.corrective_note("", "one thing", None or "") == "one thing"

    def test_dropped_items_are_named(self):
        note = batching.dropped_note(["https://a.example"], "URL")
        assert "https://a.example" in note and "fewer" in note
