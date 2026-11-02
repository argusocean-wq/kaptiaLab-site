"""Tests for Kaptia's per-user persistent conversation memory."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kaptia_personal_memory as memory


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

    def test_clear_memory_removes_only_memory_file(self):
        memory.append_exchange("問題", "回答")
        path = memory.memory_path()
        memory.clear_memory()
        self.assertFalse(path.exists())
        self.assertEqual(memory.load_recent_messages(), [])

    def test_invalid_record_fails_closed(self):
        path = memory.memory_path()
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": 999}) + "\\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            memory.load_recent_messages()

    def test_limits_are_validated(self):
        with self.assertRaises(ValueError):
            memory.load_recent_messages(max_messages=0)
        with self.assertRaises(ValueError):
            memory.load_recent_messages(max_chars=10)


if __name__ == "__main__":
    unittest.main()
