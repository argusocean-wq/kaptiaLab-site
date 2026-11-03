"""Structured task planning and dependency-DAG validation.

The planner validates explicit step proposals. It deliberately does not claim that
keyword rules or a model-generated outline constitute semantic understanding.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import replace
from typing import Any, Iterable, Mapping
import uuid

from .contracts import PlanValidationError, StepSpec, TaskPlan, utc_now

MAX_STEPS = 100
MAX_TITLE = 240
MAX_OBJECTIVE = 12000
MAX_STEP_TEXT = 4000
MAX_DEPENDENCIES = 30
MAX_ATTEMPTS = 5


def _required_text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise PlanValidationError(f"{field} 必須為 1–{limit} 字元的非空字串")
    return value.strip()


def _string_tuple(value: Any, field: str, limit: int = 30) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > limit:
        raise PlanValidationError(f"{field} 格式無效")
    rows = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > 120:
            raise PlanValidationError(f"{field} 包含無效項目")
        rows.append(item.strip())
    if len(set(rows)) != len(rows):
        raise PlanValidationError(f"{field} 不可包含重複項目")
    return tuple(rows)


def _validate_dag(steps: tuple[StepSpec, ...]) -> None:
    by_id = {step.step_id: step for step in steps}
    if len(by_id) != len(steps):
        raise PlanValidationError("step_id 不可重複")
    indegree = {step.step_id: 0 for step in steps}
    children: dict[str, list[str]] = defaultdict(list)
    for step in steps:
        if step.step_id in step.depends_on:
            raise PlanValidationError(f"任務步驟不可依賴自己：{step.step_id}")
        for dependency in step.depends_on:
            if dependency not in by_id:
                raise PlanValidationError(f"找不到依賴步驟：{dependency}")
            indegree[step.step_id] += 1
            children[dependency].append(step.step_id)
    queue = deque(key for key, count in indegree.items() if count == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(steps):
        raise PlanValidationError("任務依賴存在循環，無法執行")


def build_plan(
    title: str,
    objective: str,
    steps: Iterable[StepSpec | Mapping[str, Any]],
) -> TaskPlan:
    """Build a validated immutable task plan from explicit step specifications.

    Step identifiers are namespaced by task_id before persistence, so two
    independent plans may safely use the same human-readable step keys.
    """
    title = _required_text(title, "title", MAX_TITLE)
    objective = _required_text(objective, "objective", MAX_OBJECTIVE)
    raw_steps = list(steps)
    if not raw_steps or len(raw_steps) > MAX_STEPS:
        raise PlanValidationError(f"steps 數量必須介於 1 到 {MAX_STEPS}")
    normalized: list[StepSpec] = []
    for index, raw in enumerate(raw_steps, 1):
        if isinstance(raw, StepSpec):
            raw = raw.to_dict()
        if not isinstance(raw, Mapping):
            raise PlanValidationError("每個 step 必須是 StepSpec 或 mapping")
        step_id = _required_text(raw.get("step_id", f"step-{index:03d}"), "step_id", 80)
        step_title = _required_text(raw.get("title"), "step.title", MAX_TITLE)
        step_objective = _required_text(raw.get("objective", step_title), "step.objective", MAX_STEP_TEXT)
        classification = raw.get("data_classification", "private")
        if classification not in {"local_only", "private", "public"}:
            raise PlanValidationError("data_classification 必須是 local_only、private 或 public")
        attempts = raw.get("max_attempts", 2)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= MAX_ATTEMPTS:
            raise PlanValidationError(f"max_attempts 必須介於 1 到 {MAX_ATTEMPTS}")
        verification = raw.get("verification", ())
        if not isinstance(verification, (list, tuple)) or len(verification) > 12:
            raise PlanValidationError("verification 格式無效")
        if any(not isinstance(item, Mapping) for item in verification):
            raise PlanValidationError("verification 每個項目都必須是 object")
        normalized.append(StepSpec(
            step_id=step_id,
            title=step_title,
            objective=step_objective,
            depends_on=_string_tuple(raw.get("depends_on"), "depends_on", MAX_DEPENDENCIES),
            agent_id=_required_text(raw.get("agent_id", "kaptia-director"), "agent_id", 100),
            required_capabilities=_string_tuple(raw.get("required_capabilities"), "required_capabilities"),
            data_classification=classification,
            max_attempts=attempts,
            verification=tuple(dict(item) for item in verification),
        ))
    result = tuple(normalized)
    _validate_dag(result)

    task_id = uuid.uuid4().hex
    id_map = {step.step_id: f"{task_id}:{step.step_id}" for step in result}
    persisted_steps = tuple(
        replace(
            step,
            step_id=id_map[step.step_id],
            depends_on=tuple(id_map[item] for item in step.depends_on),
        )
        for step in result
    )
    return TaskPlan(
        task_id=task_id, title=title, objective=objective,
        steps=persisted_steps, created_at=utc_now(),
    )
