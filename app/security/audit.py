"""Privacy-conscious, append-only JSONL security audit log."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_ALLOWED_FIELDS = {"actor", "target", "outcome", "reason", "request_id", "policy", "count"}
_LOCK = threading.RLock()


class SecurityAuditLog:
    def __init__(self, path: str | Path, max_bytes: int = 2 * 1024 * 1024):
        self.path = Path(path)
        self.max_bytes = max(64 * 1024, int(max_bytes))

    def record(self, event: str, **fields) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        item = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": str(event)[:80],
        }
        for key, value in fields.items():
            if key not in _ALLOWED_FIELDS or value is None:
                continue
            item[key] = str(value)[:240] if key != "count" else int(value)
        encoded = (json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with _LOCK:
            if self.path.exists() and self.path.stat().st_size + len(encoded) > self.max_bytes:
                for index in (3, 2, 1):
                    source = self.path.with_suffix(self.path.suffix + f".{index}")
                    target = self.path.with_suffix(self.path.suffix + f".{index + 1}")
                    if source.exists():
                        if index == 3:
                            source.unlink()
                        else:
                            os.replace(source, target)
                os.replace(self.path, self.path.with_suffix(self.path.suffix + ".1"))
            with self.path.open("ab") as stream:
                stream.write(encoded)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
