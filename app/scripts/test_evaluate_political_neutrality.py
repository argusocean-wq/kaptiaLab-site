"""Unit tests for the political-neutrality evaluation harness (no model download)."""
import tempfile
import unittest
from pathlib import Path

from evaluate_political_neutrality import load_cases, run_suite


class PoliticalNeutralityHarnessTests(unittest.TestCase):
    def test_load_cases_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.jsonl"
            path.write_text(
                '{"id":"x","prompt":"one"}\n{"id":"x","prompt":"two"}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "id 重複"):
                load_cases(path)

    def test_load_cases_rejects_missing_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.jsonl"
            path.write_text('{"id":"x"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "id 與 prompt"):
                load_cases(path)

    def test_load_cases_reads_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cases.jsonl"
            path.write_text('{"id":"x","prompt":"請比較政策","category":"policy"}\n', encoding="utf-8")
            self.assertEqual(load_cases(path)[0]["category"], "policy")

    def test_run_suite_records_pipeline_answer(self):
        # Patch the pipeline import target so no model or network is needed.
        import kaptia_pipeline
        original = kaptia_pipeline.run_workflow
        try:
            kaptia_pipeline.run_workflow = lambda generator, prompt: {
                "content": "以證據區分事實與觀點", "events": ["test"], "review": {"pass": True}
            }
            rows = run_suite([{"id": "x", "prompt": "test"}], lambda *a, **k: "")
        finally:
            kaptia_pipeline.run_workflow = original
        self.assertEqual(rows[0]["answer"], "以證據區分事實與觀點")
        self.assertIn("self_review", rows[0])


if __name__ == "__main__":
    unittest.main()
