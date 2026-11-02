"""Regression tests for Kaptia task modes and honest test accounting."""
from __future__ import annotations

import unittest

from scripts.kaptia_modes import (
    normalize_mode, parse_test_plan, run_deep_workflow,
    fast_prompt, TestReport,
)


class KaptiaModeTests(unittest.TestCase):
    def test_mode_aliases_and_invalid_mode(self):
        self.assertEqual(normalize_mode("快速"), "fast")
        self.assertEqual(normalize_mode("深度思考"), "deep")
        with self.assertRaises(ValueError):
            normalize_mode("turbo")

    def test_fast_prompt_keeps_verification_requirement(self):
        prompt = fast_prompt("請完成功能")
        self.assertIn("不得猜測", prompt)
        self.assertIn("必要", prompt)

    def test_model_generated_test_plan_is_pending_not_passed(self):
        report = parse_test_plan('{"tests":[{"id":"T01","name":"正常流程","status":"passed"},{"id":"T02","name":"錯誤處理","status":"passed"}]}')
        self.assertEqual(report.passed, [])
        self.assertEqual(report.failed, [])
        self.assertEqual(len(report.pending), 2)

    def test_invalid_test_plan_is_not_counted_as_passed(self):
        report = parse_test_plan("not json")
        self.assertEqual(report.total, 1)
        self.assertEqual(report.passed, [])

    def test_deep_workflow_runs_four_stages_and_reports_pending(self):
        calls = []
        def fake_generate(messages, max_new_tokens=100, temperature=0.2):
            calls.append(messages[-1]["content"])
            if len(calls) == 3:
                return '{"tests":[{"id":"T01","name":"功能測試","status":"passed"}]}'
            return "stage " + str(len(calls))
        output, meta = run_deep_workflow(fake_generate, "建立一個功能")
        self.assertEqual(len(calls), 4)
        self.assertIn("尚未由外部測試器實際執行", output)
        self.assertEqual(meta["pending"], 1)
        self.assertEqual(meta["passed"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
