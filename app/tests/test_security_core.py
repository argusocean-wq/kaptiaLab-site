from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from security.anomaly import SecurityAnomalyDetector
from security.audit import SecurityAuditLog
from security.identity import SecurityConfigurationError, build_client_ssl_context, identity_status
from security.integrity import PolicyIntegrity
from security.lockdown import LockdownState
from security.permissions import CapabilityPermissions
from security.policy import client_allowed, trusted_networks


class NetworkPolicyTests(unittest.TestCase):
    def test_default_is_loopback_only(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(client_allowed("127.0.0.1"))
            self.assertTrue(client_allowed("::1"))
            self.assertFalse(client_allowed("192.168.1.20"))

    def test_one_tailscale_device_is_allowed(self):
        self.assertTrue(client_allowed("100.90.1.2", "100.90.1.2/32"))
        self.assertFalse(client_allowed("100.90.1.3", "100.90.1.2/32"))

    def test_broad_tailscale_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "too broad"):
            trusted_networks("100.64.0.0/10")

    def test_invalid_policy_fails_closed(self):
        self.assertFalse(client_allowed("127.0.0.1", "not-a-cidr"))

    def test_generic_worker_allowlist_takes_precedence(self):
        with patch.dict(os.environ, {
            "KAPTIA_WORKER_ALLOWED_CIDRS": "100.90.1.2/32",
            "KAPTIA_MAC_ALLOWED_CIDRS": "100.90.1.3/32",
        }, clear=True):
            self.assertTrue(client_allowed("100.90.1.2"))
            self.assertFalse(client_allowed("100.90.1.3"))


class IdentityTests(unittest.TestCase):
    def test_mtls_required_without_client_certificate_fails_closed(self):
        with self.assertRaises(SecurityConfigurationError):
            build_client_ssl_context({"KAPTIA_MTLS_REQUIRED": "1"})

    def test_client_context_requires_tls_12_or_newer(self):
        context = build_client_ssl_context({})
        self.assertGreaterEqual(context.minimum_version, __import__("ssl").TLSVersion.TLSv1_2)

    def test_server_identity_status_checks_server_pair_and_client_ca(self):
        with tempfile.TemporaryDirectory() as temp:
            cert = Path(temp) / "server.crt"
            key = Path(temp) / "server.key"
            ca = Path(temp) / "client-ca.crt"
            for path in (cert, key, ca):
                path.write_text("test", encoding="utf-8")
            result = identity_status({
                "KAPTIA_MTLS_REQUIRED": "1",
                "KAPTIA_MTLS_SERVER_CERT": str(cert),
                "KAPTIA_MTLS_SERVER_KEY": str(key),
                "KAPTIA_MTLS_CLIENT_CA_FILE": str(ca),
            })
            self.assertTrue(result["ok"])
            self.assertEqual(result["identity_side"], "server")


class AuditAndAnomalyTests(unittest.TestCase):
    def test_audit_only_writes_allowlisted_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "audit.jsonl"
            SecurityAuditLog(path).record(
                "test_event", actor="127.0.0.1", reason="test",
                authorization="DO_NOT_LOG", prompt="PRIVATE PROMPT"
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["event"], "test_event")
            self.assertNotIn("authorization", payload)
            self.assertNotIn("prompt", payload)

    def test_repeated_auth_failures_trigger_temporary_cooldown(self):
        detector = SecurityAnomalyDetector(auth_limit=3, cooldown_seconds=45)
        self.assertEqual(detector.record_auth_failure("device-a"), (False, 0))
        self.assertEqual(detector.record_auth_failure("device-a"), (False, 0))
        blocked, retry = detector.record_auth_failure("device-a")
        self.assertTrue(blocked)
        self.assertEqual(retry, 45)
        self.assertFalse(detector.allow_request("device-a")[0])


class PluginPermissionTests(unittest.TestCase):
    def test_capabilities_are_default_deny(self):
        with tempfile.TemporaryDirectory() as temp:
            permissions = CapabilityPermissions(Path(temp) / "permissions.json")
            self.assertFalse(permissions.allowed("plugin-a", "plugin.network"))

    def test_explicit_capability_grant_and_revocation(self):
        with tempfile.TemporaryDirectory() as temp:
            permissions = CapabilityPermissions(Path(temp) / "permissions.json")
            permissions.set_grant("plugin-a", "plugin.network", True)
            self.assertTrue(permissions.allowed("plugin-a", "plugin.network"))
            permissions.revoke_plugin("plugin-a")
            self.assertFalse(permissions.allowed("plugin-a", "plugin.network"))

    def test_corrupt_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "permissions.json"
            path.write_text("{broken", encoding="utf-8")
            permissions = CapabilityPermissions(path)
            self.assertFalse(permissions.allowed("plugin-a", "plugin.network"))
            with self.assertRaisesRegex(RuntimeError, "損壞"):
                permissions.set_grant("plugin-a", "plugin.network", True)

    def test_malformed_nested_permission_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "permissions.json"
            path.write_text(json.dumps({"schema": 1, "grants": {"plugin-a": True}}), encoding="utf-8")
            permissions = CapabilityPermissions(path)
            self.assertFalse(permissions.allowed("plugin-a", "plugin.network"))
            self.assertTrue(permissions.status()["corrupt"])


class StateTests(unittest.TestCase):
    def test_corrupt_lockdown_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "lockdown.json"
            path.write_text("{broken", encoding="utf-8")
            state = LockdownState(path)
            self.assertTrue(state.is_enabled())
            self.assertTrue(state.status()["state_corrupt"])

    def test_manager_status_fails_when_plugin_permissions_are_corrupt(self):
        from security.manager import SecurityManager
        with tempfile.TemporaryDirectory() as temp:
            manager = SecurityManager(Path(temp))
            manager.permissions.path.write_text("{broken", encoding="utf-8")
            status = manager.status()
            self.assertFalse(status["ok"])
            self.assertTrue(status["plugin_permissions"]["corrupt"])

    def test_policy_drift_requires_explicit_reapproval(self):
        with tempfile.TemporaryDirectory() as temp:
            baseline = PolicyIntegrity(Path(temp) / "baseline.json")
            with patch.dict(os.environ, {"KAPTIA_MAC_ALLOWED_CIDRS": "127.0.0.1/32"}, clear=True):
                self.assertTrue(baseline.check()["initialized"])
                with patch.dict(os.environ, {"KAPTIA_MAC_ALLOWED_CIDRS": "192.168.1.20/32"}, clear=True):
                    self.assertTrue(baseline.check()["drift"])
                    baseline.approve()
                    self.assertFalse(baseline.check()["drift"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
