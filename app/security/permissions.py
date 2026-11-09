"""Default-deny capability grants for optional Agent and plugin integrations.

Capabilities are intentionally coarse-grained and do not grant OS permissions by
themselves. Callers must enforce the returned decision at the process boundary.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

ALLOWED_CAPABILITIES = {
    "plugin.network",
    "plugin.local_files.read",
    "plugin.local_files.write",
    "plugin.desktop.attach",
    "plugin.cloud.compute",
}
_LOCK = threading.RLock()


class CapabilityPermissions:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict)
                    or not isinstance(data.get("grants", {}), dict)):
                raise ValueError("invalid permissions schema")
            grants = data.get("grants", {})
            for plugin_id, record in grants.items():
                if not isinstance(plugin_id, str) or not isinstance(record, dict):
                    raise ValueError("invalid plugin permission record")
                if any(
                    capability not in ALLOWED_CAPABILITIES or not isinstance(enabled, bool)
                    for capability, enabled in record.items()
                ):
                    raise ValueError("invalid capability grant")
            return data
        except FileNotFoundError:
            return {"schema": 1, "grants": {}}
        except (OSError, ValueError, json.JSONDecodeError):
            # Corrupt grants never become implicit allow.
            return {"schema": 1, "grants": {}, "corrupt": True}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, self.path)

    def allowed(self, plugin_id: str, capability: str) -> bool:
        plugin_id = str(plugin_id or "").strip()
        capability = str(capability or "").strip()
        if not plugin_id or len(plugin_id) > 120 or capability not in ALLOWED_CAPABILITIES:
            return False
        with _LOCK:
            data = self._load()
            if data.get("corrupt"):
                return False
            record = data.get("grants", {}).get(plugin_id, {})
            return record.get(capability) is True

    def set_grant(self, plugin_id: str, capability: str, enabled: bool) -> dict:
        plugin_id = str(plugin_id or "").strip()
        capability = str(capability or "").strip()
        if not plugin_id or len(plugin_id) > 120 or any(ch in plugin_id for ch in "/\\"):
            raise ValueError("plugin_id 格式無效")
        if capability not in ALLOWED_CAPABILITIES:
            raise ValueError("不支援的 capability")
        if not isinstance(enabled, bool):
            raise ValueError("enabled 必須是布林值")
        with _LOCK:
            data = self._load()
            if data.get("corrupt"):
                raise RuntimeError("權限檔損壞；請先人工檢查或備份後重建，拒絕自動授權。")
            grants = data.setdefault("grants", {})
            record = grants.setdefault(plugin_id, {})
            record[capability] = enabled
            if not any(record.values()):
                grants.pop(plugin_id, None)
            self._save(data)
        return {"plugin_id": plugin_id, "capability": capability, "enabled": enabled}

    def revoke_plugin(self, plugin_id: str) -> bool:
        with _LOCK:
            data = self._load()
            if data.get("corrupt"):
                raise RuntimeError("權限檔損壞；拒絕修改。")
            removed = data.setdefault("grants", {}).pop(str(plugin_id), None) is not None
            self._save(data)
            return removed

    def status(self) -> dict:
        with _LOCK:
            data = self._load()
            if data.get("corrupt"):
                return {"ok": False, "corrupt": True, "grants": {}}
            grants = data.get("grants", {})
            return {"ok": True, "corrupt": False,
                    "grants": {name: dict(values) for name, values in grants.items()}}
