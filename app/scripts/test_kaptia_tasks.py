import tempfile
import unittest
from pathlib import Path

from kaptia_tasks import create_task, transition_task, list_tasks


class TaskStateTests(unittest.TestCase):
    def test_create_transition_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            task = create_task("Add tests", "Create unit tests", path)
            self.assertEqual(task["status"], "queued")
            transition_task(task["id"], "in_progress", "Starting work", path)
            transition_task(task["id"], "completed", "Checks passed", path)
            rows = list_tasks(status="completed", path=path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], task["id"])
            self.assertEqual(len(rows[0]["events"]), 3)

    def test_invalid_transition_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            task = create_task("Task", "Details", path)
            with self.assertRaises(ValueError):
                transition_task(task["id"], "completed", "Skip work", path)

    def test_terminal_task_cannot_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.json"
            task = create_task("Task", "Details", path)
            transition_task(task["id"], "in_progress", "Start", path)
            transition_task(task["id"], "failed", "Error", path)
            with self.assertRaises(ValueError):
                transition_task(task["id"], "in_progress", "Reopen", path)

    def test_unknown_task_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(KeyError):
                transition_task("missing", "in_progress", "Start", Path(tmp) / "tasks.json")

    def test_bad_limits_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                list_tasks(limit=True, path=Path(tmp) / "tasks.json")


if __name__ == "__main__":
    unittest.main()
