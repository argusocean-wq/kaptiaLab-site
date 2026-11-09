"""Detect security-policy drift; baseline updates require an explicit action."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .identity import mtls_required
from .policy import policy_summary


def _file_digest(value: str) -> str | None:
    path = str(value or "").strip()
    if not path or not Path(path).is_file():
        return None
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def current_policy_fingerprint(env=None) -> str:
    source = os.environ if env is None else env
    network_value = source.get("KAPTIA_WORKER_ALLOWED_CIDRS") or source.get("KAPTIA_MAC_ALLOWED_CIDRS", "")
    network = policy_summary(network_value)
    payload = {
        "network": network,
        "mtls_required": mtls_required(source),
        "server_cert": _file_digest(source.get("KAPTIA_MTLS_SERVER_CERT", "")),
        "server_key": _file_digest(source.get("KAPTIA_MTLS_SERVER_KEY", "")),
        "client_ca": _file_digest(source.get("KAPTIA_MTLS_CLIENT_CA_FILE", "")),
        "client_cert": _file_digest(source.get("KAPTIA_MTLS_CLIENT_CERT", "")),
        "client_key": _file_digest(source.get("KAPTIA_MTLS_CLIENT_KEY", "")),
        "server_ca": _file_digest(source.get("KAPTIA_MTLS_CA_FILE", "")),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class PolicyIntegrity:
    def __init__(self, baseline_path: str | Path):
        self.path = Path(baseline_path)

    def check(self, env=None) -> dict:
        current = current_policy_fingerprint(env)
        if not self.path.exists():
            self.approve(env)
            return {"ok": True, "drift": False, "initialized": True, "fingerprint": current}
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            baseline = str(stored.get("fingerprint", ""))
            if len(baseline) != 64:
                raise ValueError("invalid fingerprint")
        except (OSError, ValueError, json.JSONDecodeError, AttributeError):
            return {"ok": False, "drift": True, "initialized": False,
                    "fingerprint": current, "error": "Policy baseline is unreadable; review required"}
        drift = current != baseline
        return {"ok": not drift, "drift": drift, "initialized": False,
                "fingerprint": current, "baseline": baseline}

    def approve(self, env=None) -> dict:
        current = current_policy_fingerprint(env)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps({"fingerprint": current}, indent=2), encoding="utf-8")
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, self.path)
        return {"ok": True, "fingerprint": current}
