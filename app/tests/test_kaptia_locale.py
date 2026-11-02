"""Locale preference persistence and translation regression tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import kaptia_locale as loc


class LocalePreferenceTests(unittest.TestCase):
    def test_all_supported_languages_have_labels(self):
        self.assertEqual(set(loc.SUPPORTED), set(loc.LABELS))
        for code in loc.SUPPORTED:
            self.assertTrue(loc.tr("overview", code))

    def test_language_preference_is_persisted_without_discarding_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}, clear=False):
            path = loc.preference_path()
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
            loc.set_language("ja")
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["language"], "ja")
            self.assertEqual(saved["theme"], "dark")
            self.assertEqual(loc.get_language(), "ja")

    def test_invalid_language_is_rejected(self):
        with self.assertRaises(ValueError):
            loc.set_language("xx")


if __name__ == "__main__":
    unittest.main(verbosity=2)
