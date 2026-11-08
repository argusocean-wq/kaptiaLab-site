"""Desktop-only, approval-gated inbox for external AI instructions."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
import secrets
import threading
from typing import Any

PROTOCOL_VERSION = "1"
MAX_TASK_CHARS = 12_000
MAX_ACTIONS = 8
MAX_TTL_SECONDS = 900
ALLOWED_ACTIONS = frozenset({"inspect_project", "propose_patch", "apply_patch", "run_tests", "inspect_test_results"})

class DelegationError(ValueError):
    """Invalid or unauthorized external delegation request."""

@dataclass(frozen=True)
class DelegatedTask:
    request_id: str
    sender: str
    task: str
    requested_actions: tuple[str, ...]
    received_at: str
    expires_at: str
    status: str = "pending_approval"

class DesktopCommandInbox:
    """Validates and queues requests; never executes commands or writes files."""
    def __init__(self, *, desktop_enabled: bool, max_pending: int = 20) -> None:
        if not desktop_enabled:
            raise RuntimeError("External AI delegation is available only in Kaptia Desktop.")
        if not 1 <= max_pending <= 100:
            raise ValueError("max_pending must be between 1 and 100.")
        self._max_pending = max_pending
        self._token = secrets.token_urlsafe(32)
        self._lock = threading.Lock()
        self._pending: dict[str, DelegatedTask] = {}

    @property
    def pairing_token(self) -> str:
        return self._token

    def rotate_pairing_token(self) -> str:
        with self._lock:
            self._token = secrets.token_urlsafe(32)
            return self._token

    def submit(self, envelope: dict[str, Any], token: str) -> DelegatedTask:
        if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
            raise DelegationError("Invalid pairing token.")
        if not isinstance(envelope, dict):
            raise DelegationError("Request envelope must be an object.")
        required = {"protocol_version", "request_id", "sender", "task", "requested_actions", "expires_at"}
        if not required.issubset(envelope):
            raise DelegationError("Request envelope is missing required fields.")
        if envelope["protocol_version"] != PROTOCOL_VERSION:
            raise DelegationError("Unsupported delegation protocol version.")
        request_id, sender, task, actions = (envelope[k] for k in ("request_id", "sender", "task", "requested_actions"))
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise DelegationError("request_id must be a non-empty string up to 128 characters.")
        if not isinstance(sender, str) or not 1 <= len(sender.strip()) <= 80:
            raise DelegationError("sender must be a non-empty label up to 80 characters.")
        if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARS:
            raise DelegationError(f"task must contain 1–{MAX_TASK_CHARS} characters.")
        if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
            raise DelegationError(f"requested_actions must contain 1–{MAX_ACTIONS} entries.")
        if any(not isinstance(a, str) or a not in ALLOWED_ACTIONS for a in actions):
            raise DelegationError("Request contains an unsupported action.")
        if len(set(actions)) != len(actions):
            raise DelegationError("requested_actions must not contain duplicates.")
        try:
            expires = datetime.fromisoformat(envelope["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None:
                raise ValueError("timezone required")
        except (AttributeError, TypeError, ValueError):
            raise DelegationError("expires_at must be an ISO-8601 timestamp with timezone.") from None
        now = datetime.now(timezone.utc)
        ttl = (expires.astimezone(timezone.utc) - now).total_seconds()
        if ttl <= 0 or ttl > MAX_TTL_SECONDS:
            raise DelegationError("Request is expired or exceeds the 15-minute lifetime.")
        with self._lock:
            if request_id in self._pending:
                raise DelegationError("Duplicate request_id.")
            if len(self._pending) >= self._max_pending:
                raise DelegationError("Desktop delegation inbox is full.")
            item = DelegatedTask(request_id, sender.strip(), task.strip(), tuple(actions), now.isoformat(), expires.astimezone(timezone.utc).isoformat())
            self._pending[request_id] = item
            return item

    def list_pending(self) -> tuple[DelegatedTask, ...]:
        now = datetime.now(timezone.utc)
        with self._lock:
            for key in [k for k, v in self._pending.items() if datetime.fromisoformat(v.expires_at) <= now]:
                del self._pending[key]
            return tuple(self._pending.values())

    def approve(self, request_id: str, *, locally_confirmed: bool) -> DelegatedTask:
        if locally_confirmed is not True:
            raise DelegationError("Local user confirmation is required.")
        with self._lock:
            item = self._pending.get(request_id)
            if item is None:
                raise DelegationError("Request not found or expired.")
            approved = DelegatedTask(item.request_id, item.sender, item.task, item.requested_actions, item.received_at, item.expires_at, "approved")
            self._pending[request_id] = approved
            return approved

    def reject(self, request_id: str) -> None:
        with self._lock:
            if self._pending.pop(request_id, None) is None:
                raise DelegationError("Request not found or expired.")
