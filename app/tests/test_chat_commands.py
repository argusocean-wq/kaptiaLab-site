import unittest

from chat import (COMMANDS, SPECIALIST_PROMPTS, SPECIALIST_PROFILES, CODE_LANGUAGE_PROMPTS, CODE_LANGUAGE_LABELS, _help_text, _status_text)


class ChatCommandTests(unittest.TestCase):
    def test_help_is_generated_from_registry(self):
        rendered = _help_text()
        for command, _description, _usage in COMMANDS:
            self.assertIn(command, rendered)

    def test_help_contains_usage_and_unknown_command_hint(self):
        rendered = _help_text()
        self.assertIn("/research <研究問題>", rendered)
        self.assertIn("/mode [fast|deep]", rendered)
        self.assertIn("/code [python|c|lua|general]", rendered)
        for command in ("/paper", "/code", "/math", "/data", "/general"):
            self.assertIn(command, rendered)
        self.assertIn("未知的 / 指令", rendered)

    def test_status_reports_runtime_configuration(self):
        rendered = _status_text("deep", True, 12000, 12000, [{"role": "user", "content": "x"}])
        self.assertIn("深度思考", rendered)
        self.assertIn("專業模式：一般助理", rendered)
        self.assertIn("子代理：啟用", rendered)
        self.assertIn("目前工作階段：1 則訊息", rendered)

    def test_specialist_profiles_are_defined_and_distinct(self):
        self.assertEqual(set(SPECIALIST_PROFILES) - {"general"}, set(SPECIALIST_PROMPTS))
        self.assertIn("學術論文模式", SPECIALIST_PROMPTS["paper"])
        self.assertIn("軟體工程模式", SPECIALIST_PROMPTS["code"])
        self.assertIn("數學與形式推理模式", SPECIALIST_PROMPTS["math"])
        self.assertIn("資料分析模式", SPECIALIST_PROMPTS["data"])

    def test_code_language_profiles_are_defined_and_distinct(self):
        self.assertEqual(set(CODE_LANGUAGE_PROMPTS), {"python", "c", "lua"})
        self.assertEqual(set(CODE_LANGUAGE_LABELS), {"python", "c", "lua"})
        self.assertIn("PEP 8", CODE_LANGUAGE_PROMPTS["python"])
        self.assertIn("未定義行為", CODE_LANGUAGE_PROMPTS["c"])
        self.assertIn("Lua 版本", CODE_LANGUAGE_PROMPTS["lua"])


if __name__ == "__main__":
    unittest.main()
