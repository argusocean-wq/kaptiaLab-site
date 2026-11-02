import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kaptia_tools
import kaptia_memory
import kaptia_artifacts


class KaptiaToolsTests(unittest.TestCase):
    def test_unknown_tool_fails_closed(self):
        result = kaptia_tools.dispatch_tool("run_shell", {"command": "echo unsafe"})
        self.assertFalse(result["ok"])
        self.assertIn("allowed_tools", result)

    def test_file_allowlist_blocks_unlisted_paths(self):
        result = kaptia_tools.read_project_file("../../secrets.txt")
        self.assertFalse(result["ok"])

    def test_check_name_is_allowlisted(self):
        result = kaptia_tools.run_project_check("delete_everything")
        self.assertFalse(result["ok"])

    def test_memory_rejects_invalid_kind(self):
        with self.assertRaises(ValueError):
            kaptia_memory.append_record("chat_dump", "title", "detail")

    def test_memory_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory.jsonl"
            with patch.object(kaptia_memory, "MEMORY_PATH", path):
                kaptia_memory.append_record("decision", "Use local RAG", "Keep source attribution", tags=["architecture"])
                rows = kaptia_memory.list_records(kind="decision")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["title"], "Use local RAG")

    def test_markdown_artifact_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(kaptia_artifacts, "OUTPUT_DIR", Path(tmp)):
                result = kaptia_artifacts.export_artifact("# Kaptia\n\nVerified output", "md", "test-file")
                self.assertTrue(result["ok"])
                self.assertTrue(result["readback_verified"])
                self.assertEqual(Path(result["path"]).read_text(encoding="utf-8"), "# Kaptia\n\nVerified output")


if __name__ == "__main__":
    unittest.main()
