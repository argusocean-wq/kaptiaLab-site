import unittest

from chat import COMMANDS, _help_text, _status_text


class ChatCommandTests(unittest.TestCase):
    def test_help_is_generated_from_registry(self):
        rendered = _help_text()
        for command, _description, _usage in COMMANDS:
            self.assertIn(command, rendered)

    def test_help_contains_usage_and_unknown_command_hint(self):
        rendered = _help_text()
        self.assertIn("/research <研究問題>", rendered)
        self.assertIn("/mode [fast|deep]", rendered)
        self.assertIn("未知的 / 指令", rendered)

    def test_status_reports_runtime_configuration(self):
        rendered = _status_text("deep", True, 12000, 12000, [{"role": "user", "content": "x"}])
        self.assertIn("深度思考", rendered)
        self.assertIn("子代理：啟用", rendered)
        self.assertIn("目前工作階段：1 則訊息", rendered)


if __name__ == "__main__":
    unittest.main()
