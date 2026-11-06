"""Verify structured output requirements independently of model response quality."""
import asyncio
import json
from dataclasses import replace

import pytest

from tasks.P_agent.control import output_requirements as output, task_state as TS
from tasks.P_agent.control.model import ClassifierResult, ControlEvent, freeze
from tasks.P_agent.control.handlers.preparation import Handler
from test_agent_control import _progress_context, SKILLS

REQUESTS = [
    "Write three reports.", "Schreibe drei Berichte.", "Escribe tres informes.", "Écris trois rapports.",
    "Napisz trzy raporty.", "Escreva três relatórios.", "اكتب ثلاثة تقارير.", "כתוב שלושה דוחות.",
    "तीन रिपोर्ट लिखें।", "请写三份报告。", "Scrivi tre rapporti.", "Schrijf drie rapporten.",
    "Skriv tre rapporter.", "Skriv tre rapporter om avtalen.", "Skriv tre rapporter om avtalet.",
    "Γράψε τρεις αναφορές.", "Napiši tri izvješća.", "Scrie trei rapoarte.", "Напиши три отчёта.",
    "報告書を三つ書いてください。", "보고서 세 개를 작성하세요.", "Üç rapor yaz."]


def answer(message, names=None, count=3, interpretation="new", number=1):
    return json.dumps({"schema_version": 1, "state": "known", "complete": True,
                       "interpretation": interpretation, "groups": [
                           {"noun": "report", "count": count, "names": names or [],
                            "message": number, "words": message}]})


@pytest.mark.parametrize("message", REQUESTS)
def test_counted_multilingual_requests_keep_original_text_and_need_distinct_files(message):
    state = TS.derive(message, 1)
    result = output.validate(answer(message), state)
    state = output.apply(state, result)
    assert state["objective"]["text"] == message
    assert TS.delivery(state, ["one.md"])["state"] == "incomplete"
    assert TS.delivery(state, ["one.md", "two.md", "three.md"])["evidence"]


@pytest.mark.parametrize("text", ["{}", "[]", "invalid", '{"schema_version":2}', '{"state":"unknown"}'])
def test_invalid_unknown_or_incomplete_classification_provides_no_evidence(text):
    state = TS.derive(REQUESTS[3], 1)
    result = output.validate(text, state)
    assert TS.delivery(output.apply(state, result), ["one.md"])["evidence"] is False


def test_named_outputs_reject_invented_names_counts_and_stale_input():
    message = "Écris trois rapports: a.md, b.md et c.md."
    state = TS.derive(message, 1)
    result = output.validate(answer(message, ["a.md", "b.md", "c.md"]), state)
    assert TS.delivery(output.apply(state, result), ["a.md", "b.md", "c.md"])["evidence"]
    assert output.validate(answer(message, ["a.md", "b.md"], count=1), state)["state"] == "unknown"
    newer = TS.derive("Continue.", 2, state)
    assert output.apply(newer, result) == newer


def test_unknown_source_mention_does_not_grant_web_permission():
    state = TS.derive("Use only the selected documents. Do not use the web. Write a report.", 1)
    state = TS.derive("What about the web archives?", 2, state)
    class Answers:
        async def ask(self, source, questions, instructions=""):
            if "sources=" in questions:
                assert "web" not in questions["sources="]["criteria"]
            return ClassifierResult("ok", freeze({"sources=": {"choice": "web", "probabilities": {"web": 1.0}}}))
        async def complete(self, *args):
            return ClassifierResult("unavailable")
    context = replace(_progress_context(), task_state=freeze(state), listed_skills=freeze(SKILLS),
                      capabilities=frozenset({"documents", "web", "both"}), collections=("enron",))
    result = asyncio.run(Handler().evaluate(ControlEvent("start", "turn_started", 0, "runtime"), context,
                                           {"names": False}, Answers()))
    assert result.facts["sources"]["choice"] == "documents"
    notes = "\n".join(a.arguments.get("text", "") for a in result.actions)
    assert "Do not use the web" in notes and "then search the web" not in notes.lower()
    assert TS.source_scope(state)["web"] == "forbidden"


@pytest.mark.parametrize("message", [REQUESTS[3], REQUESTS[19]])
def test_new_foreign_objective_replaces_outputs_and_reactivates_source_restrictions(message):
    state = TS.derive("Use only the selected documents. Do not use the web. Write a report.", 1)
    state = TS.derive("Search the web for the bankruptcy date.", 2, state)
    assert TS.source_scope(state)["web"] == "allowed"
    state = TS.derive(message, 3, state)
    result = output.validate(answer(message, interpretation="new", number=3), state)
    state = output.apply(state, result)
    assert state["objective"]["text"] == message
    assert TS.text_task(state)["objective"]["text"] == message
    assert TS.source_scope(state)["web"] == "forbidden"
    assert TS.delivery(state, ["one.md"])["state"] == "incomplete"


def test_invented_explicit_output_name_is_unknown():
    state = TS.derive(REQUESTS[3], 1)
    assert output.validate(answer(REQUESTS[3], ["invented.md"]), state)["state"] == "unknown"


@pytest.mark.parametrize("message", REQUESTS)
def test_explicit_named_outputs_remain_distinct_across_supported_languages(message):
    message += " a.md, b.md, c.md"
    state = TS.derive(message, 1)
    state = output.apply(state, output.validate(answer(message, ["a.md", "b.md", "c.md"]), state))
    assert TS.delivery(state, ["a.md"])["evidence"] is False
    assert TS.delivery(state, ["a.md", "b.md", "c.md"])["evidence"] is True


@pytest.mark.parametrize("cancellation", ["Annule le troisième rapport.", "三つ目の報告書を取り消してください。"])
def test_translated_cancellation_and_continuation_keep_remaining_outputs(cancellation):
    state = TS.derive(REQUESTS[3], 1)
    state = output.apply(state, output.validate(answer(REQUESTS[3]), state))
    state = TS.derive(cancellation, 2, state)
    state = output.apply(state, output.validate(answer(cancellation, count=2, interpretation="amendment", number=2), state))
    assert TS.delivery(state, ["one.md"])["state"] == "incomplete"
    state = TS.derive("Continue.", 3, state)
    assert TS.delivery(state, ["one.md", "two.md"])["evidence"] is True
