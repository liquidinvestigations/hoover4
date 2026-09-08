"""Verify persisted-answer comparison independently of temporary interface text."""

import unittest
from unittest.mock import AsyncMock, patch

import chat_observer as observer


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
                                                       "switch": {"attempted": True, "survived": False}}))


if __name__ == "__main__":
    unittest.main()
