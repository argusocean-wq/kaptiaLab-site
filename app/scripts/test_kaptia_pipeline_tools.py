import unittest

from scripts.kaptia_pipeline import _run_preflight_tools


class PipelineToolRoutingTests(unittest.TestCase):
    def test_ordinary_chat_skips_tool_planner_model_call(self):
        calls = []

        def generate(messages, **kwargs):
            calls.append((messages, kwargs))
            return '{"action":"done","summary":"not needed"}'

        events, context = _run_preflight_tools(generate, "嗨，請簡短回答")
        self.assertEqual(calls, [])
        self.assertEqual(events, [])
        self.assertEqual(context, "")

    def test_explicit_tool_orchestration_uses_bounded_planner(self):
        calls = []

        def generate(messages, **kwargs):
            calls.append((messages, kwargs))
            return '{"action":"done","summary":"不需要呼叫其他工具"}'

        events, context = _run_preflight_tools(generate, "請使用工具協作處理這項任務")
        self.assertEqual(len(calls), 1)
        self.assertTrue(any("不需要" in event for event in events))
        self.assertEqual(context, "[]")


if __name__ == "__main__":
    unittest.main()
