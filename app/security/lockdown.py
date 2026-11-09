"""Persistent emergency remote-compute lockdown state."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


class LockdownState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._cached = None
        self._corrupt = False

    def _read(self):
        if not self.path.exists():
            return {"enabled": False, "reason": "", "updated_at": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
                raise ValueError("invalid lockdown state schema")
            return data
        except (OSError, ValueError, json.JSONDecodeError):
            # A corrupted state file must not silently restore remote access.
            self._corrupt = True
            return {"enabled": True, "reason": "lockdown state is corrupt; fail-closed", "updated_at": None}

    def is_enabled(self) -> bool:
        with self._lock:
            return bool(self._read().get("enabled", True))

    def status(self) -> dict:
        with self._lock:
            state = self._read()
            return {"enabled": bool(state.get("enabled")), "reason": state.get("reason", ""),
                    "updated_at": state.get("updated_at"), "state_corrupt": self._corrupt}

    def set_enabled(self, enabled: bool, reason: str = "manual") -> dict:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        state = {"enabled": enabled, "reason": str(reason)[:240] if enabled else "",
                 "updated_at": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            os.replace(temp, self.path)
            self._corrupt = False
            return self.status()
