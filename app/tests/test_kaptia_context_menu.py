"""Unit tests for Kaptia Windows Explorer context-menu configuration and safe text collection."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from scripts import kaptia_context_menu as cm

class ContextMenuTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / "context_menu.json"
        self.patch = mock.patch.object(cm, "CONFIG_PATH", self.config)
        self.patch.start()
        self.app_patch = mock.patch.object(cm, "APP_ROOT", self.root)
        self.app_patch.start()

    def tearDown(self):
        self.app_patch.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def test_default_config(self):
        self.assertEqual(cm.load_config(), {"menu_label": "問問 Kaptia", "default_assistant": "Kaptia"})

    def test_user_can_customize_label_and_assistant(self):
        saved = cm.save_config("詢問 Kaptia", "程式助理")
        self.assertEqual(saved["menu_label"], "詢問 Kaptia")
        self.assertEqual(saved["default_assistant"], "程式助理")
        self.assertEqual(json.loads(self.config.read_text(encoding="utf-8"))["default_assistant"], "程式助理")

    def test_rejects_blank_or_too_long_label(self):
        with self.assertRaises(ValueError):
            cm.save_config(" ", None)
        with self.assertRaises(ValueError):
            cm.save_config("x" * 65, None)

    def test_only_reads_supported_text_files(self):
        text_file = self.root / "hello.md"
        text_file.write_text("Kaptia test", encoding="utf-8")
        binary = self.root / "image.png"
        binary.write_bytes(b"not text")
        result = cm.read_selected_paths([str(self.root)])
        self.assertIn("Kaptia test", result)
        self.assertNotIn("not text", result)

    def test_rejects_selection_without_supported_text(self):
        binary = self.root / "image.png"
        binary.write_bytes(b"binary")
        with self.assertRaisesRegex(ValueError, "沒有可讀取"):
            cm.read_selected_paths([str(binary)])

if __name__ == "__main__":
    unittest.main(verbosity=2)
