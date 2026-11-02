import os
import unittest
from unittest.mock import patch

from scripts.kaptia_reasoning import generate_reasoned


class KaptiaReasoningTests(unittest.TestCase):
    def test_single_mode_calls_model_once(self):
        calls = []
        def generate(messages, **kwargs):
            calls.append((messages, kwargs))
            return "direct answer"
        with patch.dict(os.environ, {"KAPTIA_REASONING_MODE": "single"}):
            answer, meta = generate_reasoned(generate, [{"role": "user", "content": "hi"}],
                                             max_new_tokens=20, temperature=0.2)
        self.assertEqual(answer, "direct answer")
        self.assertEqual(len(calls), 1)
        self.assertEqual(meta["mode"], "single")

    def test_best_of_n_is_bounded_and_uses_judge(self):
        calls = []
        outputs = iter(["candidate A", "candidate B", "candidate C", "2"])
        def generate(messages, **kwargs):
            calls.append((messages, kwargs))
            return next(outputs)
        with patch.dict(os.environ, {
            "KAPTIA_REASONING_MODE": "best_of_n",
            "KAPTIA_REASONING_CANDIDATES": "99",
        }):
            answer, meta = generate_reasoned(generate, [{"role": "user", "content": "solve"}],
                                             max_new_tokens=20, temperature=0.2)
        self.assertEqual(answer, "candidate B")
        self.assertEqual(meta["candidates"], 3)
        self.assertEqual(meta["selection"], "model_judge")
        self.assertEqual(len(calls), 4)  # 3 candidates + 1 selector

    def test_invalid_mode_falls_back_to_single(self):
        calls = []
        def generate(messages, **kwargs):
            calls.append(1)
            return "ok"
        with patch.dict(os.environ, {"KAPTIA_REASONING_MODE": "not-a-mode"}):
            answer, meta = generate_reasoned(generate, [], max_new_tokens=5, temperature=0.1)
        self.assertEqual(answer, "ok")
        self.assertEqual(len(calls), 1)
        self.assertEqual(meta["mode"], "single")


if __name__ == "__main__":
    unittest.main()
