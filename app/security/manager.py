"""Composition root for Kaptia's independent Security Core."""
from __future__ import annotations

import os
import platform
from pathlib import Path

from .anomaly import SecurityAnomalyDetector
from .audit import SecurityAuditLog
from .identity import identity_status
from .integrity import PolicyIntegrity
from .lockdown import LockdownState
from .permissions import CapabilityPermissions
from .policy import policy_summary


def default_security_dir() -> Path:
    configured = os.environ.get("KAPTIA_SECURITY_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Kaptia"
    elif platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support" / "Kaptia"
    else:
        root = Path.home() / ".local" / "share" / "Kaptia"
    return root / "security"


class SecurityManager:
    def __init__(self, root: str | Path | None = None):
        directory = Path(root) if root else default_security_dir()
        directory.mkdir(parents=True, exist_ok=True)
        self.root = directory
        self.audit = SecurityAuditLog(directory / "audit.jsonl")
        self.anomaly = SecurityAnomalyDetector()
        self.lockdown = LockdownState(directory / "lockdown.json")
        self.permissions = CapabilityPermissions(directory / "plugin-permissions.json")
        self.integrity = PolicyIntegrity(directory / "policy-baseline.json")

    def request_allowed(self, actor: str) -> tuple[bool, int]:
        allowed, retry = self.anomaly.allow_request(actor)
        if not allowed:
            self.audit.record("request_throttled", actor=actor, outcome="blocked", reason="request_rate_limit")
        return allowed, retry

    def auth_failed(self, actor: str) -> tuple[bool, int]:
        blocked, retry = self.anomaly.record_auth_failure(actor)
        self.audit.record("authentication_failed", actor=actor, outcome="denied")
        if blocked:
            self.audit.record("temporary_actor_cooldown", actor=actor, outcome="blocked",
                              reason="repeated_authentication_failures", count=self.anomaly.auth_limit)
        return blocked, retry

    def event(self, name: str, **fields) -> None:
        self.audit.record(name, **fields)

    def plugin_capability_allowed(self, plugin_id: str, capability: str) -> bool:
        allowed = self.permissions.allowed(plugin_id, capability)
        if not allowed:
            self.audit.record("plugin_capability_denied", actor=plugin_id,
                              target=capability, outcome="denied", reason="default_deny")
        return allowed

    def require_plugin_capability(self, plugin_id: str, capability: str) -> None:
        if not self.plugin_capability_allowed(plugin_id, capability):
            raise PermissionError(
                f"Plugin {plugin_id!r} does not have the explicit capability grant {capability!r}"
            )

    def status(self) -> dict:
        network = policy_summary()
        tls = identity_status()
        integrity = self.integrity.check()
        lockdown = self.lockdown.status()
        permissions = self.permissions.status()
        return {
            "ok": bool(network["ok"] and tls["ok"] and integrity["ok"]
                       and permissions["ok"] and not lockdown["state_corrupt"]),
            "network_policy": network,
            "identity": tls,
            "policy_integrity": integrity,
            "lockdown": lockdown,
            "audit_log": str(self.audit.path),
            "plugin_permissions": permissions,
            "anomaly_protection": {"request_limit_per_minute": self.anomaly.request_limit,
                                   "auth_failure_limit": self.anomaly.auth_limit,
                                   "temporary_cooldown_seconds": self.anomaly.cooldown},
        }
