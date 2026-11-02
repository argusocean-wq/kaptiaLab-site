"""Regression tests for Kaptia's staged generation and strict review gate."""
import unittest

from kaptia_pipeline import (
    _validate_review_payload,
    verify_output,
    RESPONSE_PRINCIPLES,
    CORE_CONSTITUTION,
    PLANNER_PROMPT,
    WRITER_RULES,
    REVIEW_PROMPT,
)


class ReviewPayloadTests(unittest.TestCase):
    def test_valid_review_payload(self):
        result = _validate_review_payload(
            {"pass": True, "issues": [], "needs_source_check": False}
        )
        self.assertTrue(result["pass"])
        self.assertTrue(result["review_available"])

    def test_string_false_is_rejected_not_truthy(self):
        with self.assertRaises(ValueError):
            _validate_review_payload(
                {"pass": "false", "issues": [], "needs_source_check": False}
            )

    def test_missing_pass_is_rejected(self):
        with self.assertRaises(ValueError):
            _validate_review_payload({"issues": [], "needs_source_check": False})

    def test_wrong_issue_item_type_is_rejected(self):
        with self.assertRaises(ValueError):
            _validate_review_payload(
                {"pass": True, "issues": [1], "needs_source_check": False}
            )

    def test_research_always_requires_source_check(self):
        result = _validate_review_payload(
            {"pass": True, "issues": [], "needs_source_check": False},
            needs_research=True,
        )
        self.assertTrue(result["needs_source_check"])

    def test_invalid_model_review_fails_closed(self):
        def fake_generate(messages, **kwargs):
            return '{"pass":"false","issues":[],"needs_source_check":false}'

        result = verify_output(
            fake_generate, "write code", {"needs_research": False}, "print('hi')"
        )
        self.assertFalse(result["pass"])
        self.assertFalse(result["review_available"])

    def test_all_pipeline_roles_include_core_rules(self):
        for prompt in (PLANNER_PROMPT, WRITER_RULES, REVIEW_PROMPT):
            self.assertIn(CORE_CONSTITUTION, prompt)
            self.assertIn(RESPONSE_PRINCIPLES, prompt)


if __name__ == "__main__":
    unittest.main()
