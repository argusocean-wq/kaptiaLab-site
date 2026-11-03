"""Capability-aware hybrid model routing with local-only data enforcement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .contracts import ModelRequest, DATA_CLASSIFICATIONS


class ModelRoutingError(RuntimeError):
    """No eligible model provider was available or all eligible providers failed."""


@dataclass(frozen=True)
class ModelRegistration:
    provider_id: str
    location: str
    capabilities: frozenset[str]
    adapter: Any
    priority: int = 100


class ModelRouter:
    """Routes requests across local, user-cloud and explicitly configured external models."""

    def __init__(self, policy: str = "local_first"):
        if policy not in {"local_first", "cloud_first", "balanced"}:
            raise ValueError("policy 必須是 local_first、cloud_first 或 balanced")
        self.policy = policy
        self._providers: dict[str, ModelRegistration] = {}

    def register(
        self, provider_id: str, adapter: Any, *, location: str,
        capabilities: set[str] | frozenset[str], priority: int = 100,
    ) -> None:
        if not isinstance(provider_id, str) or not provider_id.strip() or len(provider_id) > 100:
            raise ValueError("provider_id 無效")
        if location not in {"local", "user_cloud", "external"}:
            raise ValueError("location 必須是 local、user_cloud 或 external")
        if not callable(getattr(adapter, "generate", None)):
            raise TypeError("adapter 必須實作 generate(request)")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("priority 必須是整數")
        self._providers[provider_id] = ModelRegistration(
            provider_id=provider_id, location=location,
            capabilities=frozenset(capabilities), adapter=adapter, priority=priority,
        )

    def unregister(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)

    def candidates(self, request: ModelRequest) -> list[ModelRegistration]:
        if request.data_classification not in DATA_CLASSIFICATIONS:
            raise ValueError("data_classification 無效")
        required = set(request.required_capabilities)
        rows = [
            item for item in self._providers.values()
            if required.issubset(item.capabilities)
            and not (request.data_classification == "local_only" and item.location != "local")
        ]
        if request.preferred_provider_id:
            rows.sort(key=lambda item: (item.provider_id != request.preferred_provider_id, item.priority))
        elif self.policy == "cloud_first":
            rows.sort(key=lambda item: (item.location == "local", item.priority))
        elif self.policy == "local_first":
            rows.sort(key=lambda item: (item.location != "local", item.priority))
        else:
            rows.sort(key=lambda item: item.priority)
        return rows

    def generate(self, request: ModelRequest) -> dict[str, Any]:
        candidates = self.candidates(request)
        if not candidates:
            raise ModelRoutingError("沒有符合資料分級與能力需求的模型")
        failures = []
        for registration in candidates:
            try:
                output = registration.adapter.generate(request)
                if not isinstance(output, str) or not output.strip():
                    raise ValueError("模型回傳空白或非文字結果")
                return {
                    "output": output,
                    "provider_id": registration.provider_id,
                    "location": registration.location,
                    "fallback_used": bool(failures),
                    "previous_failures": failures,
                }
            except Exception as exc:
                failures.append({
                    "provider_id": registration.provider_id,
                    "error_type": type(exc).__name__,
                })
        raise ModelRoutingError(f"所有符合條件的模型均失敗：{failures}")
