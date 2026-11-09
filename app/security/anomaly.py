"""Bounded in-memory request anomaly detection with temporary throttling."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SecurityAnomalyDetector:
    def __init__(self, request_limit: int = 120, auth_limit: int = 5,
                 window_seconds: int = 60, cooldown_seconds: int = 300):
        self.request_limit = max(10, int(request_limit))
        self.auth_limit = max(2, int(auth_limit))
        self.window = max(10, int(window_seconds))
        self.cooldown = max(30, int(cooldown_seconds))
        self._requests = defaultdict(deque)
        self._auth_failures = defaultdict(deque)
        self._blocked_until = {}
        self._lock = threading.RLock()

    def _trim(self, queue, now):
        while queue and now - queue[0] > self.window:
            queue.popleft()

    def allow_request(self, actor: str) -> tuple[bool, int]:
        key = str(actor or "unknown")[:80]
        now = time.monotonic()
        with self._lock:
            until = self._blocked_until.get(key, 0.0)
            if until > now:
                return False, max(1, int(until - now))
            queue = self._requests[key]
            self._trim(queue, now)
            queue.append(now)
            if len(queue) > self.request_limit:
                self._blocked_until[key] = now + self.cooldown
                queue.clear()
                return False, self.cooldown
            if len(self._requests) > 512:
                self._requests.pop(next(iter(self._requests)))
            return True, 0

    def record_auth_failure(self, actor: str) -> tuple[bool, int]:
        key = str(actor or "unknown")[:80]
        now = time.monotonic()
        with self._lock:
            queue = self._auth_failures[key]
            self._trim(queue, now)
            queue.append(now)
            if len(queue) >= self.auth_limit:
                self._blocked_until[key] = now + self.cooldown
                queue.clear()
                return True, self.cooldown
            if len(self._auth_failures) > 512:
                self._auth_failures.pop(next(iter(self._auth_failures)))
            return False, 0
