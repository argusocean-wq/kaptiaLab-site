"""Regression tests for user-consented desktop Attach sessions."""
from __future__ import annotations
import unittest
from unittest import mock
from scripts import kaptia_attach as attach

class AttachTests(unittest.TestCase):
    def tearDown(self):
        attach.detach_all()

    def test_connect_requires_explicit_consent(self):
        with mock.patch.object(attach, "_validate_window") as validate:
            result = attach.attach_window(123, user_approved=False)
        self.assertFalse(result["ok"])
        validate.assert_not_called()

    def test_connect_binds_one_window_and_returns_limited_capabilities(self):
        with mock.patch.object(attach, "_validate_window", return_value=456):
            result = attach.attach_window(123, user_approved=True)
        self.assertTrue(result["ok"])
        with mock.patch.object(attach, "_validate_window", return_value=456):
            session = attach._get_session(result["session_id"])
        self.assertEqual(session["window_id"], 123)
        self.assertEqual(session["pid"], 456)
        self.assertIn("inspect", result["capabilities"])
        self.assertNotIn("shell", result["capabilities"])

    def test_detach_revokes_session(self):
        with mock.patch.object(attach, "_validate_window", return_value=456):
            result = attach.attach_window(123, user_approved=True)
        self.assertTrue(attach.detach_window(result["session_id"])["detached"])
        with self.assertRaises(PermissionError):
            attach._get_session(result["session_id"])

    def test_disconnect_all_revokes_every_session(self):
        with mock.patch.object(attach, "_validate_window", return_value=456):
            first = attach.attach_window(123, user_approved=True)
            second = attach.attach_window(124, user_approved=True)
        self.assertEqual(attach.detach_all()["detached_count"], 2)
        with self.assertRaises(PermissionError):
            attach._get_session(first["session_id"])
        with self.assertRaises(PermissionError):
            attach._get_session(second["session_id"])

    def test_expired_session_is_rejected(self):
        with mock.patch.object(attach, "_validate_window", return_value=456):
            result = attach.attach_window(123, user_approved=True)
        attach._SESSIONS[result["session_id"]]["created"] = attach.time.monotonic() - attach.SESSION_TTL_SECONDS - 1
        with mock.patch.object(attach, "_validate_window", return_value=456):
            with self.assertRaises(PermissionError):
                attach._get_session(result["session_id"])

    def test_click_requires_fresh_consent(self):
        result = attach.click_ui_element("x" * 32, {"name": "Save"}, user_approved=False)
        self.assertFalse(result["ok"])
        self.assertIn("逐次確認", result["error"])

    def test_text_input_is_bounded(self):
        result = attach.type_into_text_field("x" * 32, {"control_type": "Edit"},
                                             "x" * 4001, user_approved=True)
        self.assertFalse(result["ok"])
        self.assertIn("4000", result["error"])

    def test_proposal_does_not_execute_without_ui_approval(self):
        result = attach.approve_pending_action("not-a-real-id", user_approved=False)
        self.assertFalse(result["ok"])
        self.assertIn("明確批准", result["error"])

    def test_proposal_rejects_unknown_action(self):
        result = attach.propose_ui_action("x" * 32, "shell", {"name": "Run"})
        self.assertFalse(result["ok"])

    def test_pending_action_rejection_is_idempotent(self):
        self.assertFalse(attach.reject_pending_action("missing")["rejected"])

    def test_vision_proposal_is_queued_and_not_executed(self):
        session_id = "a" * 32
        with mock.patch.object(attach, "_get_session", return_value={"window_id": 10, "pid": 20}), \
             mock.patch.object(attach, "_window_rect", return_value=(100, 100, 900, 700)):
            result = attach.propose_vision_action(session_id, "vision_click", 120, 80)
        self.assertTrue(result["ok"])
        pending = attach.list_pending_actions()["pending"]
        self.assertEqual(pending[0]["action"], "vision_click")
        self.assertEqual(pending[0]["point"], {"x": 120, "y": 80})

    def test_vision_proposal_rejects_coordinates_outside_window(self):
        with mock.patch.object(attach, "_get_session", return_value={"window_id": 10, "pid": 20}), \
             mock.patch.object(attach, "_window_rect", return_value=(0, 0, 400, 300)):
            result = attach.propose_vision_action("a" * 32, "vision_click", 400, 10)
        self.assertFalse(result["ok"])
        self.assertIn("超出", result["error"])

    def test_vision_text_rejects_non_ascii(self):
        result = attach.propose_vision_action("a" * 32, "vision_type_text", 10, 10, "測試")
        self.assertFalse(result["ok"])
        self.assertIn("ASCII", result["error"])

    def test_vision_proposal_requires_explicit_approval_before_execution(self):
        result = attach.approve_pending_action("missing", user_approved=False)
        self.assertFalse(result["ok"])
        self.assertIn("明確批准", result["error"])

    def test_selector_rejects_unsupported_control_type(self):
        class Info:
            enabled = True
            visible = True
            name = "Run"
            automation_id = "run"
            control_type = "Pane"
        class Element:
            element_info = Info()
        class Window:
            def descendants(self):
                return [Element()]
        with self.assertRaises(PermissionError):
            attach._find_unique_control(Window(), {"name": "Run", "control_type": "Pane"}, attach.ALLOWED_CLICK_TYPES)

if __name__ == "__main__":
    unittest.main(verbosity=2)
