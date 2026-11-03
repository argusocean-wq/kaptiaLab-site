import tempfile, unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from desktop.mcp_server import MCPTaskService,MCPProtocolError
TOKEN="x"*48

def args(**changes):
    data={"request_id":"mcp-1","sender":"Claude","task":"Review this project","requested_actions":["inspect_project","propose_patch"],"expires_at":(datetime.now(timezone.utc)+timedelta(minutes=4)).isoformat()}
    data.update(changes); return data

class MCPTaskServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/"queue.sqlite3"
        self.service=MCPTaskService(self.path,TOKEN,desktop_enabled=True)
    def tearDown(self): self.tmp.cleanup()
    def test_desktop_gate(self):
        with self.assertRaises(RuntimeError): MCPTaskService(":memory:",TOKEN,desktop_enabled=False)
    def test_pairing_secret_required_at_startup(self):
        with self.assertRaises(ValueError): MCPTaskService(self.path,"short",desktop_enabled=True)
    def test_initialize_and_tools_list(self):
        init=self.service.handle({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}})
        self.assertEqual(init["result"]["serverInfo"]["name"],"kaptialab-desktop-bridge")
        tools=self.service.handle({"jsonrpc":"2.0","id":2,"method":"tools/list"})
        self.assertEqual({t["name"] for t in tools["result"]["tools"]},{"submit_task","get_task_status"})
        self.assertNotIn("pairing_token",str(tools))
    def test_submit_persists_pending_request(self):
        result=self.service.handle({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"submit_task","arguments":args()}})
        self.assertFalse(result["result"]["isError"])
        self.assertEqual(self.service.get_task_status({"request_id":"mcp-1"})["status"],"pending_approval")
        reopened=MCPTaskService(self.path,TOKEN,desktop_enabled=True)
        self.assertTrue(reopened.get_task_status({"request_id":"mcp-1"})["found"])
    def test_duplicate_request_rejected(self):
        self.service.submit_task(args())
        with self.assertRaises(MCPProtocolError): self.service.submit_task(args())
    def test_arbitrary_shell_rejected(self):
        with self.assertRaises(MCPProtocolError): self.service.submit_task(args(requested_actions=["run_shell"]))
    def test_expired_request_rejected(self):
        expired=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with self.assertRaises(MCPProtocolError): self.service.submit_task(args(expires_at=expired))
    def test_notification_has_no_response(self):
        self.assertIsNone(self.service.handle({"jsonrpc":"2.0","method":"notifications/initialized"}))

if __name__=="__main__": unittest.main()
