import os
import unittest
from unittest.mock import patch

import chat


class ChatGuardrailTests(unittest.TestCase):
    def test_env_limit_uses_default_on_invalid_input(self):
        with patch.dict(os.environ, {"KAPTIA_LIMIT_TEST": "not-a-number"}):
            self.assertEqual(chat._env_limit("KAPTIA_LIMIT_TEST", 50, 10, 100), 50)

    def test_env_limit_clamps_to_safe_bounds(self):
        with patch.dict(os.environ, {"KAPTIA_LIMIT_TEST": "999999"}):
            self.assertEqual(chat._env_limit("KAPTIA_LIMIT_TEST", 50, 10, 100), 100)

    def test_history_evicts_oldest_content_and_keeps_latest(self):
        history = [{"role": "user", "content": "old" * 10}]
        chat._append_bounded_history(history, "user", "latest", max_chars=12)
        self.assertEqual(history[-1], {"role": "user", "content": "latest"})
        self.assertLessEqual(chat._history_char_count(history), 12)

    def test_history_message_count_is_bounded(self):
        history = []
        for i in range(30):
            chat._append_bounded_history(history, "user", str(i), max_chars=1000)
        self.assertLessEqual(len(history), chat.MAX_HISTORY_MESSAGES)
        self.assertEqual(history[-1]["content"], "29")

    def test_casual_replies_use_smaller_token_budget(self):
        self.assertEqual(chat._response_token_budget("嗨，今天有點累。"), chat.DEFAULT_RESPONSE_TOKENS)
        self.assertLess(chat.DEFAULT_RESPONSE_TOKENS, chat.DETAILED_RESPONSE_TOKENS)

    def test_code_and_detailed_requests_get_larger_token_budget(self):
        self.assertEqual(chat._response_token_budget("請寫一段 Python 程式"), chat.DETAILED_RESPONSE_TOKENS)
        self.assertEqual(chat._response_token_budget("請詳細解釋這個問題"), chat.DETAILED_RESPONSE_TOKENS)
        self.assertEqual(chat._response_token_budget("請分析 " + ("不同模組的問題與設計。" * 30)), chat.DETAILED_RESPONSE_TOKENS)

    def test_long_personal_message_stays_concise_without_detail_request(self):
        message = "今天發生很多事，我覺得有點委屈，想找人聊聊。" * 12
        self.assertEqual(chat._response_token_budget(message), chat.DEFAULT_RESPONSE_TOKENS)

    def test_casual_chat_uses_more_natural_sampling(self):
        self.assertEqual(chat._response_temperature("你今天怎麼樣？"), 0.55)

    def test_technical_answers_use_conservative_sampling(self):
        self.assertEqual(chat._response_temperature("請寫一段 Python 程式"), 0.25)
        self.assertEqual(chat._response_temperature("請詳細解釋這件事"), 0.35)

    def test_subagents_are_opt_in_by_default(self):
        calls = []
        def generate(messages, **kwargs):
            calls.append((messages, kwargs))
            return "ok"
        # A long enough message would use subagents if the default were accidentally re-enabled.
        long_message = "請分析並優化專案中的不同模組與穩定性。 " * 10
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(chat, "_load_generator", return_value=generate), \
             patch("builtins.input", side_effect=[long_message, "/exit"]):
            exit_code = chat.main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["max_new_tokens"], chat._response_token_budget(long_message))


if __name__ == "__main__":
    unittest.main()
