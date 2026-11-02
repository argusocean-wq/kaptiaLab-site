"""Security and regression tests for Kaptia Agent planning and workspace tools."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.kaptia_agent_runtime import WorkspaceSandbox, build_plan_prompt, parse_agent_plan, create_agent_plan


class AgentPlanTests(unittest.TestCase):
    def test_valid_plan_is_parsed_without_execution(self):
        raw = json.dumps({"goal":"檢查程式","steps":[
            {"id":"S1","action":"list_files","target":".","reason":"檢視專案結構"},
            {"id":"S2","action":"read_file","target":"main.py","reason":"讀取入口"}
        ]})
        plan = parse_agent_plan(raw)
        self.assertEqual(len(plan["steps"]), 2)
        self.assertEqual(plan["steps"][1]["target"], "main.py")

    def test_rejects_shell_or_unknown_actions(self):
        raw = json.dumps({"goal":"bad","steps":[{"id":"S1","action":"shell","target":"whoami","reason":"no"}]})
        with self.assertRaises(ValueError):
            parse_agent_plan(raw)

    def test_rejects_absolute_and_parent_paths(self):
        for target in ("../secret.txt", "C:\\Windows\\win.ini", "/etc/passwd"):
            raw = json.dumps({"goal":"bad","steps":[{"id":"S1","action":"read_file","target":target,"reason":"read"}]})
            with self.assertRaises(ValueError):
                parse_agent_plan(raw)

    def test_rejects_duplicate_step_ids_and_too_many_steps(self):
        raw = json.dumps({"goal":"bad","steps":[
            {"id":"S1","action":"list_files","target":".","reason":"one"},
            {"id":"S1","action":"list_files","target":".","reason":"two"}
        ]})
        with self.assertRaises(ValueError):
            parse_agent_plan(raw)

    def test_plan_prompt_forbids_shell_and_direct_writes(self):
        prompt = build_plan_prompt("檢查工作區")
        self.assertIn("禁止 shell", prompt)
        self.assertIn("propose_write", prompt)

    def test_create_plan_validates_model_output(self):
        def fake_generate(messages, **kwargs):
            return json.dumps({"goal":"list files","steps":[
                {"id":"S1","action":"list_files","target":".","reason":"list"}
            ]})
        plan = create_agent_plan(fake_generate, "列出工作區檔案")
        self.assertTrue(plan["plan_id"])
        self.assertEqual(plan["steps"][0]["action"], "list_files")


class WorkspaceSandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        self.sandbox = WorkspaceSandbox()
        self.sandbox.set_root(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_read_is_denied_until_explicitly_granted(self):
        (self.root / "hello.txt").write_text("hello", encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.sandbox.read_file("hello.txt")
        self.sandbox.grant_read(True)
        self.assertEqual(self.sandbox.read_file("hello.txt")["content"], "hello")

    def test_read_and_list_stay_inside_selected_workspace(self):
        (self.root / "hello.txt").write_text("hello", encoding="utf-8")
        self.sandbox.grant_read(True)
        self.assertEqual(self.sandbox.list_files()[0]["path"], "hello.txt")
        with self.assertRaises(ValueError):
            self.sandbox.read_file("../outside.txt")

    def test_search_text_returns_bounded_matches(self):
        (self.root / "one.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        self.sandbox.grant_read(True)
        hits = self.sandbox.search_text("beta")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["line"], 2)

    def test_staged_write_requires_explicit_approval(self):
        target = self.root / "notes.txt"
        target.write_text("old", encoding="utf-8")
        self.sandbox.grant_read(True)
        change = self.sandbox.stage_write("notes.txt", "new")
        with self.assertRaises(PermissionError):
            self.sandbox.apply_staged_write(change["change_id"], approved=False)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")
        result = self.sandbox.apply_staged_write(change["change_id"], approved=True)
        self.assertTrue(result["ok"])
        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertTrue(Path(result["backup"]).is_file())

    def test_staged_write_rejects_stale_preview(self):
        target = self.root / "notes.txt"
        target.write_text("old", encoding="utf-8")
        self.sandbox.grant_read(True)
        change = self.sandbox.stage_write("notes.txt", "new")
        target.write_text("external change", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.sandbox.apply_staged_write(change["change_id"], approved=True)

    def test_symlinks_are_rejected(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.root / "link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation is not permitted on this runner")
        self.sandbox.grant_read(True)
        with self.assertRaises(PermissionError):
            self.sandbox.read_file("link.txt")


    def test_hidden_and_dependency_paths_are_rejected(self):
        self.sandbox.grant_read(True)
        for target in (".env", ".git/config", "node_modules/pkg/index.js"):
            with self.assertRaises(ValueError):
                self.sandbox.read_file(target)

    def test_revoking_read_permission_clears_staged_changes(self):
        (self.root / "notes.txt").write_text("old", encoding="utf-8")
        self.sandbox.grant_read(True)
        change = self.sandbox.stage_write("notes.txt", "new")
        self.sandbox.grant_read(False)
        self.assertEqual(self.sandbox.status()["pending_changes"], 0)
        with self.assertRaises(PermissionError):
            self.sandbox.apply_staged_write(change["change_id"], approved=True)


    def test_hard_linked_files_cannot_be_staged_for_write(self):
        target = self.root / "original.txt"
        target.write_text("old", encoding="utf-8")
        linked = self.root / "linked.txt"
        try:
            os.link(target, linked)
        except OSError:
            self.skipTest("Hard-link creation is not permitted on this runner")
        self.sandbox.grant_read(True)
        with self.assertRaises(ValueError):
            self.sandbox.stage_write("linked.txt", "new")

    def test_workspace_read_permission_is_reset_when_root_changes(self):
        self.sandbox.grant_read(True)
        other = Path(self.temp.name) / "other"
        other.mkdir()
        self.sandbox.set_root(other)
        self.assertFalse(self.sandbox.status()["read_enabled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
