"""Unit tests for fail-fast local model runtime configuration."""
from __future__ import annotations

import unittest

from scripts.kaptia_runtime_config import validate_runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_cuda_accepts_four_bit_quantization(self):
        self.assertEqual(validate_runtime_config(True, "4bit", False), "cuda")

    def test_cuda_accepts_unquantized_configuration(self):
        self.assertEqual(validate_runtime_config(True, "none", False), "cuda")

    def test_cpu_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(RuntimeError, "CUDA GPU"):
            validate_runtime_config(False, "none", False)

    def test_cpu_four_bit_is_rejected_instead_of_silently_using_fp32(self):
        with self.assertRaisesRegex(RuntimeError, "靜默改用 FP32"):
            validate_runtime_config(False, "4bit", True)

    def test_cpu_fp32_requires_explicit_opt_in(self):
        self.assertEqual(validate_runtime_config(False, "none", True), "cpu")

    def test_unknown_quantization_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "僅支援 4bit 或 none"):
            validate_runtime_config(True, "8bit", False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
