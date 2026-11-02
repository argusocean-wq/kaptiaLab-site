"""Tests for the Kaptia CLI entry point."""
import os
import unittest
from unittest import mock
from scripts import kaptia_cli

class KaptiaCliTests(unittest.TestCase):
    def test_parser_accepts_chat_mode_and_provider(self):
        args = kaptia_cli.build_parser().parse_args(["chat", "--mode", "deep", "--provider", "openai-compatible"])
        self.assertEqual(args.command, "chat")
        self.assertEqual(args.mode, "deep")
        self.assertEqual(args.provider, "openai-compatible")

    def test_no_subcommand_defaults_to_chat(self):
        with mock.patch("scripts.kaptia_cli._run_chat", return_value=0) as chat_main:
            self.assertEqual(kaptia_cli.main([]), 0)
            chat_main.assert_called_once()

    def test_chat_options_are_forwarded_through_environment(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("scripts.kaptia_cli._run_chat", return_value=0):
            self.assertEqual(kaptia_cli.main(["chat", "--mode", "deep", "--provider", "openai-compatible"]), 0)
            self.assertEqual(os.environ["KAPTIA_MODE"], "deep")
            self.assertEqual(os.environ["KAPTIA_PROVIDER"], "openai-compatible")

    def test_cloud_provider_command(self):
        args = kaptia_cli.build_parser().parse_args(["cloud", "providers"])
        self.assertEqual(args.command, "cloud")
        self.assertEqual(args.cloud_action, "providers")

    def test_cloud_submit_requires_explicit_task_type_and_file(self):
        args = kaptia_cli.build_parser().parse_args([
            "cloud", "submit", "--type", "python_script", "--file", "job.py"
        ])
        self.assertEqual(args.task_type, "python_script")
        self.assertEqual(args.file, "job.py")

    def test_doctor_does_not_load_model(self):
        with mock.patch("scripts.kaptia_cli._json") as emit:
            self.assertEqual(kaptia_cli._doctor(), 0)
        payload = emit.call_args.args[0]
        self.assertIn("python", payload)
        self.assertIn("provider", payload)
        self.assertNotIn("model_loaded", payload)

if __name__ == "__main__":
    unittest.main()
