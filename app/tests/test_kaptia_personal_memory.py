"""Tests for per-user persistent Kaptia conversation memory."""
import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import kaptia_personal_memory as memory


class PersonalMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"KAPTIA_DATA_DIR": self.temp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_exchange_survives_reload_and_reports_local_path(self):
        memory.append_exchange("我偏好繁體中文", "我會以繁體中文回答。")
        rows = memory.load_recent_messages()
        self.assertEqual([row["role"] for row in rows], ["user", "assistant"])
        self.assertIn("繁體中文", rows[0]["content"])
        status = memory.memory_status()
        self.assertEqual(status["exchanges"], 1)
        self.assertEqual(status["storage"], "local-only")
        self.assertTrue(Path(status["path"]).is_file())

    def test_clear_memory_removes_active_and_archived_history(self):
        with patch.object(memory, "MAX_STORED_MESSAGES", 2):
            memory.append_exchange("第一個問題", "第一個回答")
            memory.append_exchange("第二個問題", "第二個回答")
        path = memory.memory_path()
        archive_dir = path.parent / "archive"
        self.assertTrue(list(archive_dir.glob("*.jsonl.gz")))
        memory.clear_memory()
        self.assertFalse(path.exists())
        self.assertFalse(archive_dir.exists())
        self.assertEqual(memory.load_recent_messages(), [])

    def test_old_conversation_is_archived_before_active_history_is_trimmed(self):
        with patch.object(memory, "MAX_STORED_MESSAGES", 2):
            memory.append_exchange("第一個問題", "第一個回答")
            memory.append_exchange("第二個問題", "第二個回答")
        rows = memory.load_recent_messages(max_messages=10)
        self.assertEqual([row["content"] for row in rows], ["第二個問題", "第二個回答"])
        status = memory.memory_status()
        self.assertEqual(status["archive_files"], 1)
        archive = next((Path(self.temp.name) / "memory" / "archive").glob("*.jsonl.gz"))
        with gzip.open(archive, "rt", encoding="utf-8") as stream:
            archived = [json.loads(line) for line in stream]
        self.assertEqual([row["content"] for row in archived], ["第一個問題", "第一個回答"])

    def test_archive_manager_lists_reads_and_searches_archived_messages(self):
        with patch.object(memory, "MAX_STORED_MESSAGES", 2):
            memory.append_exchange("舊專案的部署問題", "先檢查部署日誌。")
            memory.append_exchange("新的問題", "新的回答。")
        listing = memory.list_conversation_archives()
        self.assertEqual(listing["total"], 1)
        archive_id = listing["archives"][0]["archive_id"]
        detail = memory.read_conversation_archive(archive_id)
        self.assertEqual(detail["total"], 2)
        self.assertEqual(detail["messages"][0]["content"], "舊專案的部署問題")
        found = memory.search_conversation_archives("部署")
        self.assertEqual(len(found["matches"]), 1)
        self.assertEqual(found["matches"][0]["archive_id"], archive_id)

    def test_restore_archive_preserves_current_history_and_source_archive(self):
        with patch.object(memory, "MAX_STORED_MESSAGES", 2):
            memory.append_exchange("要封存的舊問題", "舊回答")
            memory.append_exchange("目前近期問題", "近期回答")
        archive_id = memory.list_conversation_archives()["archives"][0]["archive_id"]
        result = memory.restore_conversation_archive(archive_id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["restored_messages"], 2)
        self.assertEqual(result["previous_messages_archived"], 2)
        self.assertTrue(result["source_archive_retained"])
        active = memory.load_recent_messages(max_messages=10)
        self.assertEqual([row["content"] for row in active],
                         ["要封存的舊問題", "舊回答"])
        self.assertEqual(memory.list_conversation_archives()["total"], 2)

    def test_archive_manager_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            memory.read_conversation_archive("../../conversation.jsonl.gz")

    def test_invalid_record_fails_closed(self):
        path = memory.memory_path()
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": 999}) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            memory.load_recent_messages()

    def test_limits_are_validated(self):
        with self.assertRaises(ValueError):
            memory.load_recent_messages(max_messages=0)
        with self.assertRaises(ValueError):
            memory.load_recent_messages(max_chars=10)


if __name__ == "__main__":
    unittest.main()
