"""Tests for hardware discovery used by the local assistant."""
from __future__ import annotations

import unittest
from unittest import mock

from installer import hardware_profile as hp


class HardwareProfileTests(unittest.TestCase):
    def test_high_profile_requires_both_vram_and_system_ram(self):
        with mock.patch.object(hp, "_nvidia_gpus", return_value=[{
            "name": "Test GPU", "vendor": "NVIDIA", "vram_mb": 16384,
            "driver_version": "test", "source": "nvidia-smi"
        }]), mock.patch.object(hp, "_windows_display_adapters", return_value=[]), \
             mock.patch.object(hp, "_ram_total_gb", return_value=32), \
             mock.patch.object(hp.platform, "system", return_value="Windows"):
            report = hp.detect_hardware()
        self.assertEqual(report.profile_id, "gpu_high")

    def test_low_ram_does_not_get_high_profile_even_with_large_gpu(self):
        with mock.patch.object(hp, "_nvidia_gpus", return_value=[{
            "name": "Test GPU", "vendor": "NVIDIA", "vram_mb": 24576,
            "driver_version": "test", "source": "nvidia-smi"
        }]), mock.patch.object(hp, "_windows_display_adapters", return_value=[]), \
             mock.patch.object(hp, "_ram_total_gb", return_value=8), \
             mock.patch.object(hp.platform, "system", return_value="Windows"):
            report = hp.detect_hardware()
        self.assertEqual(report.profile_id, "cpu_safe")

    def test_missing_gpu_and_ram_uses_cpu_safe_profile(self):
        with mock.patch.object(hp, "_nvidia_gpus", return_value=[]), \
             mock.patch.object(hp, "_windows_display_adapters", return_value=[]), \
             mock.patch.object(hp, "_ram_total_gb", return_value=None):
            report = hp.detect_hardware()
        self.assertEqual(report.profile_id, "cpu_safe")
        self.assertTrue(report.notes)

    def test_non_nvidia_adapter_memory_does_not_enable_cuda_profile(self):
        with mock.patch.object(hp, "_nvidia_gpus", return_value=[]), \
             mock.patch.object(hp, "_windows_display_adapters", return_value=[{
                 "name": "Integrated Display Adapter", "vendor": "Unknown",
                 "vram_mb": 16384, "driver_version": "test",
                 "source": "Windows CIM"
             }]), \
             mock.patch.object(hp, "_ram_total_gb", return_value=64):
            report = hp.detect_hardware()
        self.assertEqual(report.profile_id, "cpu_safe")
        self.assertEqual(report.gpus[0]["name"], "Integrated Display Adapter")

    def test_hardware_report_contains_detected_gpu_and_ram(self):
        with mock.patch.object(hp, "_nvidia_gpus", return_value=[{
            "name": "Test GPU", "vendor": "NVIDIA", "vram_mb": 4096,
            "driver_version": "test", "source": "nvidia-smi"
        }]), mock.patch.object(hp, "_windows_display_adapters", return_value=[]), \
             mock.patch.object(hp, "_ram_total_gb", return_value=16), \
             mock.patch.object(hp.platform, "system", return_value="Windows"):
            report = hp.detect_hardware()
        self.assertEqual(report.gpus[0]["name"], "Test GPU")
        self.assertEqual(report.ram_total_gb, 16)


if __name__ == "__main__":
    unittest.main(verbosity=2)
