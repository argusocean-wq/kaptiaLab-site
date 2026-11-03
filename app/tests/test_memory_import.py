import json
import os
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

    def test_chatgpt_export_allows_selecting_one_conversation(self):
        def conv(identifier, title, user_text, assistant_text):
            return {"id":identifier,"title":title,"mapping":{
                "u":{"message":{"author":{"role":"user"},"create_time":1,"content":{"parts":[user_text]}}},
                "a":{"message":{"author":{"role":"assistant"},"create_time":2,"content":{"parts":[assistant_text]}}}
            }}
        path = self.root / "conversations.json"
        path.write_text(json.dumps([conv("one","Project A","A question","A answer"),
                                    conv("two","Project B","B question","B answer")]), encoding="utf-8")
        preview = parse_memory_file(path)
        self.assertEqual(preview["conversation_count"], 2)
        selected_id = next(x["id"] for x in preview["conversations"] if x["title"] == "Project B")
        with patch("kaptia_personal_memory.import_messages", return_value={"imported":2,"duplicates":0,"total_messages":2}) as fn:
            result = import_memory_file(path, locally_confirmed=True,
                expected_sha256=preview["source_sha256"], selected_conversation_ids=[selected_id])
        imported = fn.call_args.args[0]
        self.assertEqual([x["content"] for x in imported], ["B question", "B answer"])
        self.assertEqual(result["selected_conversations"], ["Project B"])

    def test_invalid_format_rejected(self):
        path = self.root / "x.csv"; path.write_text("x", encoding="utf-8")
        with self.assertRaises(MemoryImportError): parse_memory_file(path)

    def test_confirmation_required(self):
        path = self.root / "x.txt"; path.write_text("context", encoding="utf-8")
        with self.assertRaises(MemoryImportError): import_memory_file(path)

    def test_changed_file_after_preview_is_rejected(self):
        path = self.root / "x.txt"; path.write_text("original", encoding="utf-8")
        preview = parse_memory_file(path)
        path.write_text("changed after preview", encoding="utf-8")
        with self.assertRaises(MemoryImportError):
            import_memory_file(path, locally_confirmed=True, expected_sha256=preview["source_sha256"])

    def test_commit_calls_local_import(self):
        path = self.root / "x.txt"; path.write_text("context", encoding="utf-8")
        with patch("kaptia_personal_memory.import_messages", return_value={"imported":1}) as fn:
            result = import_memory_file(path, locally_confirmed=True)
        self.assertEqual(result["imported"], 1)
        fn.assert_called_once()

    def test_import_appends_and_deduplicates_local_history(self):
        path = self.root / "conversation.json"
        path.write_text(json.dumps({"messages":[
            {"role":"user","content":"project goal"},
            {"role":"assistant","content":"project plan"}
        ]}), encoding="utf-8")
        with patch.dict(os.environ, {"KAPTIA_DATA_DIR": str(self.root / "data")}):
            first = import_memory_file(path, locally_confirmed=True)
            second = import_memory_file(path, locally_confirmed=True)
            from kaptia_personal_memory import load_recent_messages
            history = load_recent_messages(max_messages=10, max_chars=5000)
        self.assertEqual(first["imported"], 2)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["content"], "project goal")


if __name__ == "__main__": unittest.main()
