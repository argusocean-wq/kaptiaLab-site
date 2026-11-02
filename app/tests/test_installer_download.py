"""Regression tests for the self-contained Setup embedded-core verifier."""
from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from installer import webview_installer as installer

COMMIT = "a" * 40
PREFIX = f"kaptiaLab-core-{COMMIT}/"


def make_zip_bytes(*, valid_structure=True, traversal=False, symlink=False):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if valid_structure:
            archive.writestr(PREFIX + "README.md", "Kaptia test archive")
            archive.writestr(PREFIX + "scripts/chat.py", "def main(): return 0")
        else:
            archive.writestr("wrong-root/README.md", "Not the expected app")
        if traversal:
            archive.writestr(PREFIX + "../../outside.txt", "outside")
        if symlink:
            info = zipfile.ZipInfo(PREFIX + "linked-file")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "target")
    return buffer.getvalue()


class EmbeddedCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "install"
        self.payload_path = Path(self.temp.name) / "payload.zip"
        self.payload = make_zip_bytes()
        self.payload_path.write_bytes(self.payload)

    def tearDown(self):
        self.temp.cleanup()

    def run_extract(self, payload=None, *, commit=COMMIT, expected=None):
        if payload is not None:
            self.payload_path.write_bytes(payload)
        digest = expected or hashlib.sha256(self.payload_path.read_bytes()).hexdigest()
        with patch.object(installer, "EMBEDDED_CORE_ZIP", self.payload_path), \
             patch.object(installer, "SOURCE_COMMIT", commit), \
             patch.object(installer, "SOURCE_SHA256", digest), \
             patch.object(installer, "BUILD_NUMBER", 17), \
             patch.object(installer, "BUILD_TAG", "kaptia-build-17"):
            return installer._extract_embedded_core(self.root)

    def test_embedded_core_is_verified_and_extracted(self):
        source, manifest = self.run_extract()
        self.assertEqual(manifest["build_number"], 17)
        self.assertEqual(source, self.root / f"kaptiaLab-core-{COMMIT}")
        self.assertTrue((source / "README.md").is_file())
        self.assertTrue((source / "scripts" / "chat.py").is_file())

    def test_checksum_mismatch_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            self.run_extract(expected="0" * 64)
        self.assertFalse((self.root / f"kaptiaLab-core-{COMMIT}").exists())

    def test_corrupt_archive_fails_closed(self):
        with self.assertRaises(zipfile.BadZipFile):
            self.run_extract(b"not a zip file")

    def test_wrong_archive_structure_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "核心 ZIP 結構不完整"):
            self.run_extract(make_zip_bytes(valid_structure=False))

    def test_path_traversal_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "路徑越界"):
            self.run_extract(make_zip_bytes(traversal=True))
        self.assertFalse((Path(self.temp.name) / "outside.txt").exists())

    def test_symbolic_link_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "symbolic link"):
            self.run_extract(make_zip_bytes(symlink=True))

    def test_invalid_commit_metadata_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "commit"):
            self.run_extract(commit="invalid")

    def test_missing_embedded_payload_is_rejected(self):
        self.payload_path.unlink()
        with patch.object(installer, "EMBEDDED_CORE_ZIP", self.payload_path), \
             patch.object(installer, "SOURCE_COMMIT", COMMIT), \
             patch.object(installer, "SOURCE_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "未包含核心套件"):
                installer._extract_embedded_core(self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
