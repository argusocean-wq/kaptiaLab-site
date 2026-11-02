"""Tests for local model preflight diagnostics."""
from __future__ import annotations

import types
import unittest
from unittest import mock

from scripts import kaptia_diagnostics as diagnostics


class DiagnosticsTests(unittest.TestCase):
    def _fake_torch(self, cuda=True, vram=16, capability=(8, 6)):
        props = types.SimpleNamespace(name="Test NVIDIA GPU", total_memory=vram * (1024 ** 3))
        return types.SimpleNamespace(
            __version__="2.6.0",
            version=types.SimpleNamespace(cuda="12.4"),
            cuda=types.SimpleNamespace(
                is_available=lambda: cuda,
                current_device=lambda: 0,
                get_device_properties=lambda _index: props,
                get_device_capability=lambda _index: capability,
            ),
        )

    def test_preflight_passes_with_compatible_cuda_stack(self):
        modules = {
            "torch": self._fake_torch(),
            "transformers": types.SimpleNamespace(__version__="4.51.3"),
            "bitsandbytes": types.SimpleNamespace(__version__="0.46.1"),
        }
        with mock.patch.object(diagnostics.importlib, "import_module", side_effect=lambda name: modules[name]), \
             mock.patch.object(diagnostics.platform, "system", return_value="Windows"), \
             mock.patch.object(diagnostics.platform, "machine", return_value="AMD64"), \
             mock.patch.object(diagnostics.platform, "python_version", return_value="3.11.9"), \
             mock.patch.object(diagnostics.struct, "calcsize", return_value=8), \
             mock.patch.object(diagnostics.shutil, "disk_usage", return_value=types.SimpleNamespace(free=30 * 1024 ** 3)):
            report = diagnostics.run_diagnostics(cache_dir=".")
        self.assertTrue(report["ok"])
        self.assertEqual(report["failure_count"], 0)

    def test_missing_cuda_blocks_local_model(self):
        modules = {
            "torch": self._fake_torch(cuda=False),
            "transformers": types.SimpleNamespace(__version__="4.52.0"),
            "bitsandbytes": types.SimpleNamespace(__version__="0.46.1"),
        }
        with mock.patch.object(diagnostics.importlib, "import_module", side_effect=lambda name: modules[name]), \
             mock.patch.object(diagnostics.platform, "system", return_value="Windows"), \
             mock.patch.object(diagnostics.platform, "machine", return_value="AMD64"), \
             mock.patch.object(diagnostics.platform, "python_version", return_value="3.11.9"), \
             mock.patch.object(diagnostics.struct, "calcsize", return_value=8), \
             mock.patch.object(diagnostics.shutil, "disk_usage", return_value=types.SimpleNamespace(free=30 * 1024 ** 3)):
            report = diagnostics.run_diagnostics(cache_dir=".")
        self.assertFalse(report["ok"])
        self.assertTrue(any(item["id"] == "cuda" and item["status"] == "fail" for item in report["checks"]))

    def test_low_vram_is_reported_as_failure(self):
        modules = {
            "torch": self._fake_torch(vram=6),
            "transformers": types.SimpleNamespace(__version__="4.52.0"),
            "bitsandbytes": types.SimpleNamespace(__version__="0.46.1"),
        }
        with mock.patch.object(diagnostics.importlib, "import_module", side_effect=lambda name: modules[name]), \
             mock.patch.object(diagnostics.platform, "system", return_value="Windows"), \
             mock.patch.object(diagnostics.platform, "machine", return_value="AMD64"), \
             mock.patch.object(diagnostics.platform, "python_version", return_value="3.11.9"), \
             mock.patch.object(diagnostics.struct, "calcsize", return_value=8), \
             mock.patch.object(diagnostics.shutil, "disk_usage", return_value=types.SimpleNamespace(free=30 * 1024 ** 3)):
            report = diagnostics.run_diagnostics(cache_dir=".")
        self.assertFalse(report["ok"])
        self.assertTrue(any(item["id"] == "vram" and item["status"] == "fail" for item in report["checks"]))

    def test_unquantized_model_requires_more_vram(self):
        modules = {
            "torch": self._fake_torch(vram=16),
            "transformers": types.SimpleNamespace(__version__="4.52.0"),
        }
        with mock.patch.object(diagnostics.importlib, "import_module", side_effect=lambda name: modules[name]), \
             mock.patch.object(diagnostics.platform, "system", return_value="Windows"), \
             mock.patch.object(diagnostics.platform, "machine", return_value="AMD64"), \
             mock.patch.object(diagnostics.platform, "python_version", return_value="3.11.9"), \
             mock.patch.object(diagnostics.struct, "calcsize", return_value=8), \
             mock.patch.object(diagnostics.shutil, "disk_usage", return_value=types.SimpleNamespace(free=30 * 1024 ** 3)):
            report = diagnostics.run_diagnostics(quantization="none", cache_dir=".")
        self.assertFalse(report["ok"])
        self.assertTrue(any(item["id"] == "unquantized_vram" and item["status"] == "fail" for item in report["checks"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
