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


if __name__ == "__main__": unittest.main()
