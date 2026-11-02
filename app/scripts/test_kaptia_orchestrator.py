import unittest

from scripts.kaptia_orchestrator import build_plan
from scripts.kaptia_pipeline import plan_task


class DeterministicOrchestratorTests(unittest.TestCase):
    def test_short_chat_is_single_generation_plan(self):
        plan = build_plan("嗨，簡短介紹一下你自己")
        self.assertEqual(plan["task_size"], "short")
        self.assertEqual(plan["output_type"], "text")
        self.assertFalse(plan["needs_file"])
        self.assertEqual(plan["planner"], "kaptia_deterministic_rules_v1")

    def test_code_and_file_request_are_classified(self):
        plan = build_plan("請寫 Python 程式並建立檔案")
        self.assertEqual(plan["output_type"], "code")
        self.assertTrue(plan["needs_file"])

    def test_research_intent_is_explicit(self):
        plan = build_plan("請查詢今天的最新消息")
        self.assertTrue(plan["needs_research"])

    def test_long_input_gets_bounded_outline(self):
        plan = build_plan("需求描述 " + ("細節 " * 300))
        self.assertEqual(plan["task_size"], "long")
        self.assertLessEqual(len(plan["outline"]), 12)

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            build_plan("   ")
        with self.assertRaises(ValueError):
            build_plan("x" * 20001)

    def test_legacy_plan_task_does_not_call_base_model(self):
        calls = []

        def should_not_run(*args, **kwargs):
            calls.append(True)
            raise AssertionError("planner should be deterministic")

        plan = plan_task(should_not_run, "嗨，簡短回答")
        self.assertEqual(calls, [])
        self.assertEqual(plan["planner"], "kaptia_deterministic_rules_v1")


if __name__ == "__main__":
    unittest.main()
