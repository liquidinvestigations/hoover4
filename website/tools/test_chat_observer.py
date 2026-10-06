"""Verify persisted-answer comparison independently of temporary interface text."""

import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import chat_observer as observer


class StoryTests(unittest.TestCase):
    def test_document_prompts_keep_their_modes_and_followups(self):
        root = Path(__file__).resolve().parents[2] / "docs/quality-assurance/chat-acceptance"
        workload = tuple(observer.PROMPTS)
        with patch.dict(observer.PROMPTS_BY_NAME), patch.dict(observer.FOLLOW_UPS):
            observer.register_story_prompts(root)
            names = {name for name in observer.PROMPTS_BY_NAME if name.startswith("story-")}
            self.assertEqual(names, {f"story-{n:02d}" for n in range(1, 24)})
            self.assertEqual(observer.PROMPTS_BY_NAME["story-14"], (
                "story-14", "chat_local",
                "Go in collection testdata and retrieve all the pdf files. Sort them by size, largest first.",
            ))
            self.assertEqual(observer.FOLLOW_UPS["story-14"],
                "How many PDF documents does the epstein collection hold? List the 10 largest.")
            self.assertEqual(observer.PROMPTS_BY_NAME["story-18"][1], "chat")
            self.assertEqual(observer.PROMPTS_BY_NAME["story-17"][1], "chat_local")
            self.assertEqual(tuple(observer.PROMPTS), workload)


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_collapsed_tools_do_not_change_persisted_answer_comparison(self):
        answers = [{"seq": "5", "text": "The inspected document has three attachments."}]
        states = [{"text_length": 1000, "assistant_answers": answers},
                  {"text_length": 600, "assistant_answers": answers}]
        with patch.object(observer, "transcript_state", AsyncMock(side_effect=states)), \
             patch.object(observer, "wait_for_app_mounted", AsyncMock()):
            result = await observer.check_history(AsyncMock(), "", None)
        self.assertTrue(observer.history_is_preserved(result))
        self.assertEqual(result["after_reload_text_length"], 600)

    async def test_changed_answer_fails_even_when_total_text_grows(self):
        states = [{"text_length": 100, "assistant_answers": [{"seq": "5", "text": "original"}]},
                  {"text_length": 200, "assistant_answers": [{"seq": "5", "text": "changed"}]}]
        with patch.object(observer, "transcript_state", AsyncMock(side_effect=states)), \
             patch.object(observer, "wait_for_app_mounted", AsyncMock()):
            result = await observer.check_history(AsyncMock(), "", None, timeout_s=0)
        self.assertFalse(observer.history_is_preserved(result))

    def test_failed_switch_is_not_accepted_after_successful_reload(self):
        self.assertFalse(observer.history_is_preserved({"reload_survived": True,
                                                       "before_answers": [{"seq": "1", "text": "answer"}],
                                                       "switch": {"attempted": True, "survived": False}}))

    def test_history_failure_names_the_transition(self):
        answers = [{"seq": "2", "text": "answer"}]
        self.assertIn("reload", observer.history_failure_reason({
            "before_answers": answers, "reload_survived": False}))
        self.assertIn("switching", observer.history_failure_reason({
            "before_answers": answers, "reload_survived": True,
            "switch": {"attempted": True, "survived": False}}))


def page(turn, users, answers=()):
    return {"turn": turn, "user_seqs": list(users),
            "assistant_answers": [{"seq": str(seq), "text": text} for seq, text in answers]}


class TurnPhaseTests(unittest.TestCase):
    def test_an_answer_of_an_earlier_turn_does_not_end_the_follow_up(self):
        state = page("idle", [1, 5], [(2, "first answer")])
        self.assertEqual(observer.turn_phase(state, 1), "ended_empty")

    def test_a_queued_turn_is_running(self):
        for turn in ("queued-model", "queued-tool", "active"):
            self.assertEqual(observer.turn_phase(page(turn, [1]), -1), "running")





    def test_a_question_to_the_user_answers_the_turn(self):
        state = page("idle", [1])
        state["asked"] = [{"seq": "3", "text": "What is the range of the number?"}]
        self.assertEqual(observer.turn_phase(state, -1), "answered")

    def test_no_new_user_message_is_not_started(self):
        self.assertEqual(observer.turn_phase(page("active", [1]), 1), "not_started")


class FollowTurnTests(unittest.IsolatedAsyncioTestCase):
    async def follow(self, states, before_seq=-1, deadline_s=60.0):
        captured = []

        async def capture(index, target, actual):
            captured.append(index)

        with patch.object(observer, "transcript_state", AsyncMock(side_effect=states)), \
             patch.object(observer.asyncio, "sleep", AsyncMock()):
            phase, ended = await observer.follow_turn(AsyncMock(), before_seq, deadline_s, 0.0, capture)
        return phase, ended, captured

    async def test_answer_text_that_renders_after_the_turn_ends_is_recorded(self):
        states = [page("active", [1]), page("idle", [1]), page("idle", [1], [(2, "late answer")])]
        phase, ended, captured = await self.follow(states)
        self.assertEqual(phase, "answered")
        self.assertEqual(captured, [0, 1, 2])

    async def test_a_silent_queue_does_not_end_the_observation(self):
        states = [page("queued-model", [1])] * 5 + [page("idle", [1], [(2, "answer")])]
        phase, _, captured = await self.follow(states)
        self.assertEqual(phase, "answered")
        self.assertEqual(len(captured), 6)

    async def test_a_turn_that_ended_before_the_tab_loaded_ends_at_once(self):
        phase, ended, captured = await self.follow([page("idle", [1], [(2, "answer")])])
        self.assertEqual((phase, captured), ("answered", [0]))
        self.assertGreaterEqual(ended, 0)

    async def test_an_interrupted_turn_ends_the_observation(self):
        phase, _, _ = await self.follow([page("interrupted", [1])])
        self.assertEqual(phase, "interrupted")

    async def test_a_page_that_stops_answering_ends_the_observation(self):
        async def never(*_args):
            await asyncio.Event().wait()

        with patch.object(observer, "transcript_state", never), \
             patch.object(observer, "PAGE_CALL_TIMEOUT_S", 0.01), \
             patch.object(observer, "UNRESPONSIVE_LIMIT_S", 0.05):
            phase, ended = await observer.follow_turn(AsyncMock(), -1, 60.0, 0.0, AsyncMock())
        self.assertEqual((phase, ended), ("unresponsive", -1.0))

    async def test_a_slow_capture_skips_its_interval_and_the_observation_goes_on(self):
        calls = []

        async def capture(index, target, actual):
            calls.append(index)
            if index == 1:
                await asyncio.Event().wait()

        states = [page("active", [1]), page("active", [1]), page("idle", [1], [(2, "answer")])]
        with patch.object(observer, "transcript_state", AsyncMock(side_effect=states)), \
             patch.object(observer, "PAGE_CALL_TIMEOUT_S", 0.01):
            phase, _ = await observer.follow_turn(AsyncMock(), -1, 60.0, 0.0, capture)
        self.assertEqual(phase, "answered")
        self.assertEqual(calls, [0, 1, 2])

    async def test_the_deadline_leaves_a_running_turn_running(self):
        phase, ended, _ = await self.follow([page("active", [1])], deadline_s=0.0)
        self.assertEqual((phase, ended), ("running", -1.0))

    async def test_timeout_after_deadline_does_not_start_another_page_call(self):
        async def never(*_args):
            await asyncio.Event().wait()

        with patch.object(observer, "transcript_state", never), \
             patch.object(observer, "PAGE_CALL_TIMEOUT_S", 0.01):
            phase, ended = await observer.follow_turn(AsyncMock(), -1, 0.0, 0.0, AsyncMock())
        self.assertEqual((phase, ended), ("running", -1.0))


class FollowUpSubmitTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_follow_up_is_submitted_once_when_no_turn_appears(self):
        typed, pressed = AsyncMock(), AsyncMock()
        clock = iter(range(0, 1000, 10))
        with patch.object(observer, "transcript_state", AsyncMock(return_value=page("idle", [1]))), \
             patch.object(observer, "type_css", typed), patch.object(observer, "press_enter", pressed), \
             patch.object(observer.asyncio, "sleep", AsyncMock()), \
             patch.object(observer.time, "monotonic", lambda: next(clock)):
            before, problem = await observer.submit_followup(AsyncMock(), "next question")
        self.assertEqual(before, 1)
        self.assertIn("no new user message", problem)
        self.assertEqual((typed.await_count, pressed.await_count), (1, 1))

    async def test_a_follow_up_observes_the_turn_it_submitted(self):
        states = [page("idle", [1], [(2, "first")]), page("active", [1, 3], [(2, "first")])]
        with patch.object(observer, "transcript_state", AsyncMock(side_effect=states)), \
             patch.object(observer, "type_css", AsyncMock()), \
             patch.object(observer, "press_enter", AsyncMock()):
            before, problem = await observer.submit_followup(AsyncMock(), "next question")
        self.assertEqual((before, problem), (1, ""))
        self.assertEqual(observer.turn_phase(states[1], before), "running")


if __name__ == "__main__":
    unittest.main()
