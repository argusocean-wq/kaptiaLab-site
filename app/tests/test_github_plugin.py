import unittest
from unittest.mock import Mock
from plugins.github_plugin import GitHubPlugin, GitHubPluginError


class FakeKeyring:
    def __init__(self): self.values = {}
    def set_password(self, service, key, value): self.values[(service, key)] = value
    def get_password(self, service, key): return self.values.get((service, key))
    def delete_password(self, service, key): self.values.pop((service, key), None)


class GitHubPluginTests(unittest.TestCase):
    def setUp(self):
        self.kr = FakeKeyring()
        self.plugin = GitHubPlugin(keyring_module=self.kr)
        self.plugin._request = Mock(return_value={"login": "test-user"})
        self.plugin.connect("ghp_" + "a" * 36)

    def test_token_saved_only_in_keyring(self):
        self.assertTrue(self.kr.values)
        self.assertNotIn("token", str(self.plugin.__dict__).lower())

    def test_repo_and_branch_validation(self):
        with self.assertRaises(GitHubPluginError): self.plugin.set_repository("../owner/repo")
        self.plugin.set_repository("owner/repo")
        with self.assertRaises(GitHubPluginError): self.plugin._validate_branch("../main")
        with self.assertRaises(GitHubPluginError): self.plugin._validate_branch("feature/")
        with self.assertRaises(GitHubPluginError): self.plugin._validate_path("src//main.py")
        with self.assertRaises(GitHubPluginError): self.plugin._validate_path("src/./main.py")

    def test_write_requires_explicit_approval(self):
        self.plugin.set_repository("owner/repo")
        with self.assertRaises(GitHubPluginError):
            self.plugin.write_file("README.md", "hello", "test", "feature/test")

    def test_write_uses_base64_and_approval(self):
        self.plugin.set_repository("owner/repo")
        self.plugin._request = Mock(return_value={"commit": {"sha": "abc"}})
        self.plugin.write_file("README.md", "hello", "test", "feature/test", user_approved=True)
        args = self.plugin._request.call_args
        self.assertEqual(args.args[0], "PUT")
        self.assertEqual(args.kwargs["payload"]["content"], "aGVsbG8=")

    def test_path_traversal_rejected(self):
        with self.assertRaises(GitHubPluginError): self.plugin._validate_path("../secret")

    def test_pr_is_draft(self):
        self.plugin.set_repository("owner/repo")
        self.plugin._request = Mock(return_value={"draft": True})
        result = self.plugin.create_pull_request("title", "body", "feature/a", "main", user_approved=True)
        self.assertTrue(result["draft"])
        self.assertTrue(self.plugin._request.call_args.kwargs["payload"]["draft"])

    def test_ai_file_write_is_only_a_pending_proposal(self):
        self.plugin.set_repository("owner/repo")
        proposal = self.plugin.propose_file_write("README.md", "new content", "update", "feature/a")
        self.assertEqual(proposal["status"], "pending_approval")
        self.assertEqual(len(self.plugin.list_pending_proposals()), 1)
        self.plugin._request = Mock(return_value={"commit": {"sha": "abc"}})
        with self.assertRaises(GitHubPluginError):
            self.plugin.approve_proposal(proposal["proposal_id"], locally_confirmed=False)
        self.assertEqual(self.plugin.list_pending_proposals()[0]["proposal_id"], proposal["proposal_id"])

    def test_local_approval_executes_queued_file_write(self):
        self.plugin.set_repository("owner/repo")
        proposal = self.plugin.propose_file_write("README.md", "new content", "update", "feature/a")
        self.plugin._request = Mock(return_value={"commit": {"sha": "abc"}, "content": {"sha": "def"}})
        result = self.plugin.approve_proposal(proposal["proposal_id"], locally_confirmed=True)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.plugin._request.call_args.args[0], "PUT")
        self.assertEqual(self.plugin._request.call_args.kwargs["payload"]["branch"], "feature/a")

    def test_proposal_bound_to_repository(self):
        self.plugin.set_repository("owner/repo")
        proposal = self.plugin.propose_branch("feature/a", "main")
        self.plugin.set_repository("owner/other")
        with self.assertRaises(GitHubPluginError):
            self.plugin.approve_proposal(proposal["proposal_id"], locally_confirmed=True)

    def test_ai_file_proposal_cannot_target_default_branch(self):
        self.plugin._request = Mock(return_value={"default_branch": "main"})
        self.plugin.set_repository("owner/repo")
        with self.assertRaises(GitHubPluginError):
            self.plugin.propose_file_write("README.md", "updated", "update", "main")
        with self.assertRaises(GitHubPluginError):
            self.plugin.write_file("README.md", "updated", "update", "main", user_approved=True)


if __name__ == "__main__": unittest.main()
