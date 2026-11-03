import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from plugins.memory_import import parse_memory_file, import_memory_file, MemoryImportError


class MemoryImportTests(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()

    def test_chatgpt_export_mapping(self):
        path = self.root / "conversations.json"
        path.write_text(json.dumps([{"title":"demo","mapping":{
            "a":{"message":{"author":{"role":"user"},"create_time":1,"content":{"parts":["hello"]}}},
            "b":{"message":{"author":{"role":"assistant"},"create_time":2,"content":{"parts":["world"]}}},
            "c":{"message":{"author":{"role":"system"},"create_time":0,"content":{"parts":["ignored"]}}}
        }}]), encoding="utf-8")
        result = parse_memory_file(path)
        self.assertEqual(result["count"], 2)
        self.assertEqual([x["role"] for x in result["preview"]], ["user", "assistant"])

    def test_markdown_import(self):
        path = self.root / "notes.md"; path.write_text("# Project\ncontext", encoding="utf-8")
        result = parse_memory_file(path)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["messages"][0]["role"], "user")

    def test_invalid_format_rejected(self):
        path = self.root / "x.csv"; path.write_text("x", encoding="utf-8")
        with self.assertRaises(MemoryImportError): parse_memory_file(path)

    def test_confirmation_required(self):
        path = self.root / "x.txt"; path.write_text("context", encoding="utf-8")
        with self.assertRaises(MemoryImportError): import_memory_file(path)

    def test_commit_calls_local_import(self):
        path = self.root / "x.txt"; path.write_text("context", encoding="utf-8")
        with patch("kaptia_personal_memory.import_messages", return_value={"imported":1}) as fn:
            result = import_memory_file(path, locally_confirmed=True)
        self.assertEqual(result["imported"], 1)
        fn.assert_called_once()


if __name__ == "__main__": unittest.main()
