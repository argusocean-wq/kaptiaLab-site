import unittest

from kaptia_identity import KAPTIA_NAME, SYSTEM_PROMPT


class KaptiaIdentityTests(unittest.TestCase):
    def test_product_identity_is_kaptia(self):
        self.assertEqual(KAPTIA_NAME, "Kaptia")
        self.assertIn("你是 Kaptia", SYSTEM_PROMPT)

    def test_policy_prioritizes_evidence_and_uncertainty(self):
        for phrase in ("事實", "推論", "假設", "未知", "測試"):
            self.assertIn(phrase, SYSTEM_PROMPT)

    def test_policy_requests_summary_not_hidden_internal_trace(self):
        self.assertIn("推理摘要", SYSTEM_PROMPT)
        self.assertIn("不輸出隱藏的逐字思考過程", SYSTEM_PROMPT)

    def test_companion_tone_is_natural_and_concise(self):
        for phrase in ("像一個好聊又可靠的朋友", "簡單問題先直接回答", "不要使用空泛的"):
            # The exact prompt wording can evolve; these are stable behavioral guardrails.
            self.assertIn(phrase, SYSTEM_PROMPT)

    def test_emotional_support_is_specific_not_empty_reassurance(self):
        self.assertIn("先用真誠、具體的一句話接住對方", SYSTEM_PROMPT)
        self.assertIn("不要使用空泛的", SYSTEM_PROMPT)

    def test_persona_does_not_claim_human_experience_or_create_dependency(self):
        self.assertIn("不能把想像說成自己真實經歷", SYSTEM_PROMPT)
        self.assertIn("不製造依賴", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
