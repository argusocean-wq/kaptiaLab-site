import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from desktop.mcp_server import MCPTaskService, MCPProtocolError

TOKEN = "x" * 48

def args(**changes):
    data = {"pairing_token":TOKEN,"request_id":"mcp-1","sender":"Claude","task":"Review this project","requested_actions":["inspect_project","propose_patch"],"expires_at":(datetime.now(timezone.utc)+timedelta(minutes=4)).isoformat()}
    data.update(changes)
    return data

class MCPTaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MCPTaskService(Path(self.tmp.name)/"queue.sqlite3", TOKEN, desktop_enabled=True)
    def tearDown(self):
        self.tmp.cleanup()
    def test_desktop_gate(self):
        with self.assertRaises(RuntimeError):
            MCPTaskService(":memory:", TOKEN, desktop_enabled=False)
    def test_initialize_and_tools_list(self):
        init=self.service.handle({"jsonrpc":"2.0","id":1,"method":"initialize"})
        self.assertEqual(init["result"]["serverInfo"]["name"],"kaptialab-desktop-bridge")
        tools=self.service.handle({"jsonrpc":"2.0","id":2,"method":"tools/list"})
        self.assertEqual({x["name"] for x in tools["result"]["tools"]},{"submit_task","get_task_status"})
    def test_submit_persists_pending_request(self):
        result=self.service.handle({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"submit_task","arguments":args()}})
        self.assertFalse(result["result"]["isError"])
        self.assertIn("pending_approval",result["result"]["content"][0]["text"])
        status=self.service.get_task_status({"request_id":"mcp-1"})
        self.assertTrue(status["found"])
        self.assertEqual(status["status"],"pending_approval")
    def test_wrong_pairing_token_rejected(self):
        result=self.service.handle({"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"submit_task","arguments":args(pairing_token":"wrong")}})
        self.assertTrue(result["result"]["isError"])
    def test_duplicate_request_rejected(self):
        self.service.submit_task(args())
        with self.assertRaises(MCPProtocolError): self.service.submit_task(args())
    def test_shell_is_not_an_allowed_action(self):
        with self.assertRaises(MCPProtocolError): self.service.submit_task(args(requested_actions=["run_shell"]))
    def test_notification_has_no_response(self):
        self.assertIsNone(self.service.handle({"jsonrpc":"2.0","method":"notifications/initialized"}))

if __name__ == "__main__":
    unittest.main()
