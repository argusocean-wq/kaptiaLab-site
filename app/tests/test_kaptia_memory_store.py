"""Tests for Kaptia structured local memory and explicit conflict review."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from scripts import kaptia_memory_store as memory_module
from scripts.kaptia_memory_store import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp.name) / "facts.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_add_fact_is_active_and_available_as_context(self):
        fact = self.store.add_fact("preference", "editor", "VS Code", "development")
        self.assertEqual(fact["status"], "active")
        self.assertIn("VS Code", self.store.build_context(query_text="development"))
        self.assertEqual(self.store.status()["active"], 1)

    def test_conflicting_fact_waits_for_explicit_review(self):
        old = self.store.add_fact("preference", "editor", "VS Code", "development")
        new = self.store.add_fact("preference", "editor", "Visual Studio", "development")
        self.assertEqual(new["status"], "review")
        self.assertEqual(new["conflict_with"], old["fact_id"])
        self.assertIn("VS Code", self.store.build_context(query_text="development"))
        self.assertNotIn("Visual Studio", self.store.build_context(query_text="development"))

    def test_keep_new_supersedes_old_and_activates_new(self):
        old = self.store.add_fact("project", "language", "Python", "Kaptia")
        new = self.store.add_fact("project", "language", "C++", "Kaptia")
        self.store.resolve_conflict(new["fact_id"], "keep_new")
        statuses = {x["fact_id"]: x["status"] for x in self.store.list_facts()}
        self.assertEqual(statuses[old["fact_id"]], "superseded")
        self.assertEqual(statuses[new["fact_id"]], "active")
        self.assertIn("C++", self.store.build_context(query_text="Kaptia"))

    def test_keep_existing_archives_pending_update(self):
        old = self.store.add_fact("project", "language", "Python", "Kaptia")
        new = self.store.add_fact("project", "language", "C++", "Kaptia")
        self.store.resolve_conflict(new["fact_id"], "keep_existing")
        statuses = {x["fact_id"]: x["status"] for x in self.store.list_facts()}
        self.assertEqual(statuses[old["fact_id"]], "active")
        self.assertEqual(statuses[new["fact_id"]], "archived")

    def test_same_fact_is_not_duplicated(self):
        first = self.store.add_fact("preference", "editor", "VS Code")
        second = self.store.add_fact("preference", "editor", "VS Code")
        self.assertEqual(first["fact_id"], second["fact_id"])
        self.assertTrue(second["duplicate"])

    def test_scope_separates_same_key(self):
        self.store.add_fact("project", "language", "Python", "Project A")
        other = self.store.add_fact("project", "language", "C++", "Project B")
        self.assertEqual(other["status"], "active")
        self.assertEqual(self.store.status()["active"], 2)

    def test_archive_removes_fact_from_context(self):
        fact = self.store.add_fact("preference", "editor", "VS Code")
        self.assertTrue(self.store.archive_fact(fact["fact_id"]))
        self.assertEqual(self.store.build_context(), "")

    def test_archived_fact_can_be_restored(self):
        fact = self.store.add_fact("preference", "editor", "VS Code")
        self.store.archive_fact(fact["fact_id"])
        self.assertTrue(self.store.restore_fact(fact["fact_id"]))
        self.assertIn("VS Code", self.store.build_context())
        self.assertEqual(self.store.status()["active"], 1)

    def test_restore_rejects_duplicate_active_key_and_scope(self):
        old = self.store.add_fact("preference", "editor", "VS Code")
        new = self.store.add_fact("preference", "editor", "Vim")
        self.store.resolve_conflict(new["fact_id"], "keep_new")
        self.store.archive_fact(old["fact_id"])
        with self.assertRaises(ValueError):
            self.store.restore_fact(old["fact_id"])

    def test_compaction_creates_backup_and_preserves_facts(self):
        fact = self.store.add_fact("profile", "timezone", "Asia/Taipei")
        result = self.store.compact_storage()
        self.assertEqual(result["integrity"], "ok")
        self.assertTrue(Path(result["backup"]).is_file())
        self.assertIn("Asia/Taipei", self.store.build_context())
        self.assertEqual(self.store.status()["active"], 1)

    def test_compaction_failure_preserves_completed_backup(self):
        self.store.add_fact("profile", "timezone", "Asia/Taipei")
        real_connect = sqlite3.connect

        class FailingVacuumConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if sql.strip().upper() == "VACUUM":
                    raise sqlite3.OperationalError("injected VACUUM failure")
                return super().execute(sql, *args, **kwargs)

        def failing_connect(*args, **kwargs):
            kwargs["factory"] = FailingVacuumConnection
            return real_connect(*args, **kwargs)

        with mock.patch.object(memory_module.sqlite3, "connect", side_effect=failing_connect):
            with self.assertRaisesRegex(sqlite3.OperationalError, "injected VACUUM failure"):
                self.store.compact_storage()

        backups = list((self.store.path.parent / "backups").glob("facts-*.sqlite3"))
        self.assertEqual(len(backups), 1)
        backup = real_connect(str(backups[0]))
        try:
            integrity = backup.execute("PRAGMA integrity_check").fetchone()[0]
            fact = backup.execute(
                "SELECT fact_value FROM facts WHERE fact_key='timezone'"
            ).fetchone()[0]
        finally:
            backup.close()
        self.assertEqual(integrity, "ok")
        self.assertEqual(fact, "Asia/Taipei")

    def test_validation_rejects_empty_or_oversized_values(self):
        with self.assertRaises(ValueError):
            self.store.add_fact("preference", "", "x")
        with self.assertRaises(ValueError):
            self.store.add_fact("preference", "key", "x" * 1001)
        with self.assertRaises(ValueError):
            self.store.resolve_conflict("missing", "auto")


    def test_identical_pending_conflict_is_not_duplicated(self):
        self.store.add_fact("preference", "editor", "VS Code")
        first = self.store.add_fact("preference", "editor", "Visual Studio")
        second = self.store.add_fact("preference", "editor", "Visual Studio")
        self.assertEqual(first["fact_id"], second["fact_id"])
        self.assertTrue(second["duplicate"])

    def test_context_includes_global_and_matching_scope_only(self):
        self.store.add_fact("project", "tool", "Blender", "Blender Project")
        self.store.add_fact("project", "tool", "VS Code", "VS Code Project")
        self.store.add_fact("preference", "language", "Traditional Chinese", "global")
        context = self.store.build_context(query_text="Please inspect Blender Project")
        self.assertIn("Blender", context)
        self.assertIn("Traditional Chinese", context)
        self.assertNotIn("VS Code", context)

    def test_memory_persists_after_store_reopen(self):
        self.store.add_fact("profile", "timezone", "Asia/Taipei")
        reopened = MemoryStore(self.store.path)
        self.assertIn("Asia/Taipei", reopened.build_context())


    def test_project_memory_is_not_injected_without_matching_scope(self):
        self.store.add_fact("project", "tool", "Blender", "Blender Project")
        self.assertEqual(self.store.build_context(), "")


    def test_multiple_pending_conflicts_cannot_create_multiple_active_values(self):
        old = self.store.add_fact("project", "language", "Python", "Kaptia")
        candidate_a = self.store.add_fact("project", "language", "C++", "Kaptia")
        candidate_b = self.store.add_fact("project", "language", "Rust", "Kaptia")
        self.store.resolve_conflict(candidate_a["fact_id"], "keep_new")
        self.store.resolve_conflict(candidate_b["fact_id"], "keep_new")
        active = [x for x in self.store.list_facts() if x["status"] == "active"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["fact_id"], candidate_b["fact_id"])
        statuses = {x["fact_id"]: x["status"] for x in self.store.list_facts()}
        self.assertEqual(statuses[old["fact_id"]], "superseded")
        self.assertEqual(statuses[candidate_a["fact_id"]], "superseded")


    def test_keep_existing_restores_original_after_other_candidate_was_accepted(self):
        original = self.store.add_fact("project", "language", "Python", "Kaptia")
        accepted = self.store.add_fact("project", "language", "C++", "Kaptia")
        pending = self.store.add_fact("project", "language", "Rust", "Kaptia")
        self.store.resolve_conflict(accepted["fact_id"], "keep_new")
        self.store.resolve_conflict(pending["fact_id"], "keep_existing")
        statuses = {x["fact_id"]: x["status"] for x in self.store.list_facts()}
        self.assertEqual(statuses[original["fact_id"]], "active")
        self.assertEqual(statuses[accepted["fact_id"]], "superseded")
        self.assertEqual(statuses[pending["fact_id"]], "archived")

    def test_context_has_a_hard_character_budget(self):
        for index in range(20):
            self.store.add_fact("note", f"key-{index}", "x" * 100, "global")
        context = self.store.build_context(300)
        self.assertLessEqual(len(context), 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
