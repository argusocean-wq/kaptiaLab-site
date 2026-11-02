"""Regression tests for the public-release automatic update path."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import kaptia_update


class AutomaticUpdatePreferenceTests(unittest.TestCase):
    def test_disabled_setting_exits_before_network_access(self):
        with patch.object(kaptia_update, "read_json", return_value={"auto_updates": False}), \
             patch.object(kaptia_update, "latest_release_manifest") as latest:
            result = kaptia_update.main()
        self.assertEqual(result, 0)
        latest.assert_not_called()

    def test_missing_preference_defaults_to_enabled(self):
        with patch.object(kaptia_update, "read_json", side_effect=[{}, {"build_number": 0}]), \
             patch.object(kaptia_update, "latest_release_manifest", side_effect=RuntimeError("offline")) as latest, \
             patch.object(kaptia_update.os, "name", "nt"):
            result = kaptia_update.main()
        self.assertEqual(result, 0)
        latest.assert_called_once()

    def test_latest_public_release_manifest_is_validated(self):
        tag = "kaptia-build-42"
        setup_url = f"{kaptia_update.RELEASE_ASSET_BASE}/{tag}/Kaptia-Setup.exe"
        checksum_url = f"{kaptia_update.RELEASE_ASSET_BASE}/{tag}/Kaptia-Setup.exe.sha256"
        release = {
            "draft": False,
            "published_at": "2026-11-01T00:00:00Z",
            "tag_name": tag,
            "target_commitish": "main",
            "assets": [
                {"name": "Kaptia-Setup.exe", "browser_download_url": setup_url, "size": 12000000},
                {"name": "Kaptia-Setup.exe.sha256", "browser_download_url": checksum_url, "size": 86},
            ],
        }
        digest = "a" * 64
        with patch.object(kaptia_update, "get_json", return_value=release), \
             patch.object(kaptia_update, "get_text", return_value=f"{digest}  Kaptia-Setup.exe"):
            manifest = kaptia_update.latest_release_manifest()
        self.assertEqual(manifest["build_number"], 42)
        self.assertEqual(manifest["setup"]["sha256"], digest)
        self.assertEqual(manifest["setup"]["url"], setup_url)

    def test_latest_release_rejects_untrusted_asset_host(self):
        release = {
            "draft": False,
            "published_at": "2026-11-01T00:00:00Z",
            "tag_name": "kaptia-build-42",
            "assets": [
                {"name": "Kaptia-Setup.exe", "browser_download_url": "https://attacker.example/setup.exe"},
                {"name": "Kaptia-Setup.exe.sha256", "browser_download_url": "https://attacker.example/setup.sha256"},
            ],
        }
        with patch.object(kaptia_update, "get_json", return_value=release):
            with self.assertRaisesRegex(RuntimeError, "trusted public site repository|trusted"):
                kaptia_update.latest_release_manifest()


if __name__ == "__main__":
    unittest.main(verbosity=2)
