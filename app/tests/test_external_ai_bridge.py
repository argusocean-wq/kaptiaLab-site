import unittest
from datetime import datetime, timedelta, timezone
from desktop.external_ai_bridge import DesktopCommandInbox, DelegationError

def envelope(**changes):
    data = {"protocol_version":"1","request_id":"req-1","sender":"Claude","task":"Inspect this project and propose a fix.","requested_actions":["inspect_project","propose_patch","run_tests"],"expires_at":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
    data.update(changes)
    return data

class DesktopCommandInboxTests(unittest.TestCase):
    def test_desktop_gate(self):
        with self.assertRaises(RuntimeError): DesktopCommandInbox(desktop_enabled=False)
    def test_queues_pending_approval(self):
        inbox=DesktopCommandInbox(desktop_enabled=True); item=inbox.submit(envelope(),inbox.pairing_token)
        self.assertEqual(item.sender,"Claude"); self.assertEqual(item.status,"pending_approval")
    def test_invalid_token(self):
        inbox=DesktopCommandInbox(desktop_enabled=True)
        with self.assertRaises(DelegationError): inbox.submit(envelope(),"invalid")
    def test_disallows_arbitrary_shell(self):
        inbox=DesktopCommandInbox(desktop_enabled=True)
        with self.assertRaises(DelegationError): inbox.submit(envelope(requested_actions=["run_shell"]),inbox.pairing_token)
    def test_expired_request(self):
        inbox=DesktopCommandInbox(desktop_enabled=True); expired=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with self.assertRaises(DelegationError): inbox.submit(envelope(expires_at=expired),inbox.pairing_token)
    def test_requires_local_approval(self):
        inbox=DesktopCommandInbox(desktop_enabled=True); inbox.submit(envelope(),inbox.pairing_token)
        with self.assertRaises(DelegationError): inbox.approve("req-1",locally_confirmed=False)
        self.assertEqual(inbox.approve("req-1",locally_confirmed=True).status,"approved")
    def test_rotation_invalidates_old_token(self):
        inbox=DesktopCommandInbox(desktop_enabled=True); old=inbox.pairing_token; inbox.rotate_pairing_token()
        with self.assertRaises(DelegationError): inbox.submit(envelope(),old)
    def test_duplicate_request_id(self):
        inbox=DesktopCommandInbox(desktop_enabled=True); token=inbox.pairing_token; inbox.submit(envelope(),token)
        with self.assertRaises(DelegationError): inbox.submit(envelope(),token)

if __name__ == "__main__": unittest.main()
