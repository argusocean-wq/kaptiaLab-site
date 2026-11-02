from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch, MagicMock

from kaptia_api_runtime import build_api_generator


class ApiRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_requires_model_id(self):
        with self.assertRaisesRegex(ValueError, "KAPTIA_API_MODEL"):
            build_api_generator()

    def test_rejects_remote_plain_http(self):
        os.environ["KAPTIA_API_MODEL"] = "test-model"
        os.environ["KAPTIA_API_BASE_URL"] = "http://example.com/v1"
        os.environ["KAPTIA_API_KEY"] = "not-a-real-key"
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            build_api_generator()

    def test_ordinary_chat_includes_kaptia_system_prompt(self):
        os.environ["KAPTIA_API_MODEL"] = "test-model"
        os.environ["KAPTIA_API_BASE_URL"] = "http://127.0.0.1:1234/v1"
        generate = build_api_generator()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": "ok"}}]
        }).encode()
        with patch("urllib.request.urlopen", return_value=response) as open_url:
            generate([{"role": "user", "content": "今天心情不太好"}])
        payload = json.loads(open_url.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("你是 Kaptia", payload["messages"][0]["content"])

    def test_explicit_workflow_system_prompt_is_not_replaced(self):
        from kaptia_api_runtime import _normalise_messages
        messages = _normalise_messages([
            {"role": "system", "content": "workflow-specific instructions"},
            {"role": "user", "content": "hello"},
        ])
        self.assertEqual(messages[0]["content"], "workflow-specific instructions")
        self.assertEqual(sum(m["role"] == "system" for m in messages), 1)

    def test_localhost_can_run_without_api_key(self):
        os.environ["KAPTIA_API_MODEL"] = "test-model"
        os.environ["KAPTIA_API_BASE_URL"] = "http://127.0.0.1:1234/v1"
        generate = build_api_generator()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": "ok"}}]
        }).encode()
        with patch("urllib.request.urlopen", return_value=response) as open_url:
            self.assertEqual(generate([{"role": "user", "content": "hello"}]), "ok")
            self.assertIn("/chat/completions", open_url.call_args.args[0].full_url)

    def test_requires_key_for_remote_https(self):
        os.environ["KAPTIA_API_MODEL"] = "test-model"
        os.environ["KAPTIA_API_BASE_URL"] = "https://api.example.com/v1"
        with self.assertRaisesRegex(ValueError, "KAPTIA_API_KEY"):
            build_api_generator()


if __name__ == "__main__":
    unittest.main()
