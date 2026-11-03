import unittest
from scripts.kaptia_agent_loop import TOOL_SCHEMAS, TOOL_LOOP_SYSTEM, _validate_request
from scripts.kaptia_tools import dispatch_tool


class GitHubAgentToolTests(unittest.TestCase):
    def test_github_read_and_proposal_tools_are_registered(self):
        expected = {
            "github_list_repositories", "github_select_repository", "github_list_branches",
            "github_read_file", "github_propose_branch", "github_propose_file_write",
            "github_propose_pull_request", "github_list_workflow_runs",
        }
        self.assertTrue(expected.issubset(TOOL_SCHEMAS))

    def test_file_write_tool_only_creates_a_proposal(self):
        request = _validate_request({
            "action": "tool", "name": "github_propose_file_write",
            "arguments": {"path":"README.md","content":"updated","message":"update README",
                          "branch":"feature/docs","existing_sha":""}
        })
        self.assertEqual(request["name"], "github_propose_file_write")
        self.assertNotIn("approve", request["name"])

    def test_agent_cannot_call_approval_or_direct_write(self):
        for name in ("github_approve_proposal", "github_write_file", "github_merge_pull_request"):
            with self.assertRaises(ValueError):
                _validate_request({"action":"tool","name":name,"arguments":{}})

    def test_tool_policy_explains_local_approval(self):
        self.assertIn("github_propose_file_write", TOOL_LOOP_SYSTEM)
        self.assertIn("逐筆批准", TOOL_LOOP_SYSTEM)
        self.assertNotIn('"name":"github_approve_proposal"', TOOL_LOOP_SYSTEM)

    def test_dispatch_rejects_direct_write_tool(self):
        result = dispatch_tool("github_write_file", {})
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
