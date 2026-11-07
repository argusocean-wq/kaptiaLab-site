import unittest
from chat import _research_query

class ResearchIntentTests(unittest.TestCase):
    def test_explicit_command_extracts_query(self):
        self.assertEqual(_research_query("/research compare local models"), "compare local models")
    def test_command_without_query_returns_empty(self):
        self.assertEqual(_research_query("/research"), "")
    def test_explicit_web_research_phrases_trigger(self):
        self.assertEqual(_research_query("請上網搜尋 Qwen 8B 最新資訊"), "請上網搜尋 Qwen 8B 最新資訊")
        self.assertEqual(_research_query("幫我研究這個技術"), "幫我研究這個技術")
    def test_ordinary_chat_does_not_trigger_network(self):
        self.assertIsNone(_research_query("請解釋什麼是 Transformer"))
        self.assertIsNone(_research_query("你好"))

if __name__ == "__main__":
    unittest.main()
