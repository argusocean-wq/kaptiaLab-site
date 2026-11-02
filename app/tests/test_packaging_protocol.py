from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

from kaptia_packaging.adapters import PackagingError, ZipAdapter, GzipAdapter
from kaptia_packaging.protocol import JsonRpcStdioServer, PackagingService, RpcError


class UPTPAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "hello.txt").write_text("Kaptia UPTP test", encoding="utf-8")
        self.output = self.root / "bundle.zip"

    def tearDown(self):
        self.temp.cleanup()

    def test_zip_pack_verify_inspect_unpack_round_trip(self):
        adapter = ZipAdapter()
        packed = adapter.pack(self.source, ["hello.txt"], self.output)
        self.assertEqual(packed["entries"], 1)
        self.assertTrue(adapter.verify(self.output)["valid"])
        self.assertEqual(adapter.inspect(self.output)["entries"], 1)
        destination = self.root / "unpacked"
        adapter.unpack(self.output, destination)
        self.assertEqual((destination / "hello.txt").read_text(encoding="utf-8"), "Kaptia UPTP test")

    def test_zip_path_traversal_rejected(self):
        archive_path = self.root / "bad.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("../escape.txt", "not allowed")
        with self.assertRaises(PackagingError):
            ZipAdapter().unpack(archive_path, self.root / "out")
        self.assertFalse((self.root / "escape.txt").exists())

    def test_zip_symbolic_link_rejected(self):
        archive_path = self.root / "link.zip"
        info = zipfile.ZipInfo("linked")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(info, "target")
        with self.assertRaisesRegex(PackagingError, "Symbolic links"):
            ZipAdapter().unpack(archive_path, self.root / "out")

    def test_gzip_round_trip(self):
        adapter = GzipAdapter()
        compressed = self.root / "hello.gz"
        adapter.pack(self.source, ["hello.txt"], compressed)
        self.assertTrue(adapter.verify(compressed)["valid"])
        restored = self.root / "restored.txt"
        adapter.unpack(compressed, restored)
        self.assertEqual(restored.read_text(encoding="utf-8"), "Kaptia UPTP test")

    def test_duplicate_and_unsafe_input_paths_rejected(self):
        with self.assertRaises(PackagingError):
            ZipAdapter().pack(self.source, ["../secret.txt"], self.output)


class UPTPServiceTests(unittest.TestCase):
    def test_discovery_reports_capabilities_and_read_only_formats(self):
        result = PackagingService().discover()
        self.assertEqual(result["protocol_version"], "1.0")
        self.assertIn("zip", result["formats"])
        self.assertIn("whl", result["formats"])
        self.assertIn("exe", result["formats"])
        self.assertNotIn("unpack", result["formats"]["exe"]["operations"])

    def test_verify_expected_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("x.txt", "x")
            service = PackagingService()
            with self.assertRaisesRegex(Exception, "SHA-256 mismatch"):
                service.dispatch("VERIFY", {"format": "zip", "archive": str(path),
                                            "expected_sha256": "0" * 64})

    def test_protocol_version_negotiation(self):
        service = PackagingService()
        accepted = service.dispatch("rpc.negotiate", {"protocol_version": "1.0"})
        self.assertTrue(accepted["accepted"])
        with self.assertRaises(RpcError) as caught:
            service.dispatch("rpc.negotiate", {"protocol_version": "9.9"})
        self.assertEqual(caught.exception.code, -32001)

    def test_third_party_adapter_requires_matching_manifest_and_explicit_approval(self):
        class FakeAdapter:
            adapter_id = "vendor.fake"
            formats = ("7z",)
            manifest = {"schema_version": 1, "plugin_id": "vendor.fake", "version": "1.0.0",
                        "publisher": "Example Publisher", "formats": ["7z"], "operations": ["inspect"]}
            def capabilities(self):
                return {"formats": ["7z"], "operations": ["inspect"]}
            def inspect(self, archive):
                return {"format": "7z"}

        class FakeEntryPoint:
            name = "vendor.fake"
            def load(self):
                return lambda: FakeAdapter()

        with patch("kaptia_packaging.protocol.entry_points", return_value=[FakeEntryPoint()]):
            disabled = PackagingService()
            self.assertEqual(disabled.plugin_status[0]["status"], "disabled")
            enabled = PackagingService({"vendor.fake"})
            self.assertEqual(enabled.plugin_status[0]["status"], "enabled")
            self.assertIn("7z", enabled.discover()["formats"])

    def test_unknown_method_returns_method_not_found(self):
        from kaptia_packaging.protocol import RpcError
        with self.assertRaises(RpcError) as caught:
            PackagingService().dispatch("run_shell", {})
        self.assertEqual(caught.exception.code, -32601)

    def test_json_rpc_stdio_discovery_and_error_response(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "rpc.discover", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "does.not.exist", "params": {}},
        ]
        source = io.StringIO("".join(json.dumps(x) + "\n" for x in requests))
        sink = io.StringIO()
        JsonRpcStdioServer().serve(source, sink)
        responses = [json.loads(line) for line in sink.getvalue().splitlines()]
        by_id = {item["id"]: item for item in responses}
        self.assertEqual(by_id[1]["result"]["protocol_version"], "1.0")
        self.assertEqual(by_id[2]["error"]["code"], -32601)

    def test_request_line_limit_is_enforced(self):
        source = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"rpc.discover","params":{}}' + (" " * (1024 * 1024)) + "\n")
        sink = io.StringIO()
        JsonRpcStdioServer().serve(source, sink)
        response = json.loads(sink.getvalue().splitlines()[0])
        self.assertEqual(response["error"]["code"], -32600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
