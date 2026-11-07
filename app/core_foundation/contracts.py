"""Typed contracts shared by the M1 core modules."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
import uuid


DATA_CLASSIFICATIONS = {"local_only", "private", "public"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PlanValidationError(ValueError):
    """Raised when a task plan is structurally unsafe or inconsistent."""


@dataclass(frozen=True)
class StepSpec:
    step_id: str
    title: str
    objective: str
    depends_on: tuple[str, ...] = ()
    agent_id: str = "kaptia-director"
    required_capabilities: tuple[str, ...] = ()
    data_classification: str = "private"
    max_attempts: int = 2
    verification: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["depends_on"] = list(self.depends_on)
        value["required_capabilities"] = list(self.required_capabilities)
        value["verification"] = [dict(item) for item in self.verification]
        return value


@dataclass(frozen=True)
class TaskPlan:
    task_id: str
    title: str
    objective: str
    steps: tuple[StepSpec, ...]
    created_at: str = field(default_factory=utc_now)


@dataclass(frozen=True)
class ModelRequest:
    prompt: Any
    task_type: str = "general"
    required_capabilities: tuple[str, ...] = ()
    data_classification: str = "private"
    preferred_provider_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    output: str
    provider_id: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.output, str):
            raise TypeError("ExecutionResult.output 必須是文字")
        if not isinstance(self.evidence, Mapping):
            raise TypeError("ExecutionResult.evidence 必須是 mapping")


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    checks: tuple[Mapping[str, Any], ...]
    issues: tuple[str, ...]
    verified_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [dict(item) for item in self.checks],
            "issues": list(self.issues),
            "verified_at": self.verified_at,
        }
