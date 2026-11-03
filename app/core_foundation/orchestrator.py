"""M1 orchestration facade: submit plans, claim ready work and gate completion."""
from __future__ import annotations

from typing import Any, Callable

from .contracts import ExecutionResult, ModelRequest, TaskPlan
from .model_router import ModelRouter
from .repository import TaskRepository
from .verification import VerificationEngine


class CoreOrchestrator:
    """Coordinates durable task state and verification without owning tool side effects."""

    def __init__(
        self, repository: TaskRepository, model_router: ModelRouter | None = None,
        verifier: VerificationEngine | None = None,
    ):
        self.repository = repository
        self.model_router = model_router
        self.verifier = verifier or VerificationEngine()

    def submit(self, plan: TaskPlan) -> dict[str, Any]:
        return self.repository.create_plan(plan)

    def run_once(
        self, worker_id: str, executor: Callable[[dict[str, Any]], str | ExecutionResult],
        *, limit: int = 1,
    ) -> list[dict[str, Any]]:
        """Claim dependency-ready steps and execute each once; executor owns approved tools."""
        claimed = self.repository.claim_ready_steps(worker_id, limit=limit)
        results = []
        for step in claimed:
            try:
                raw = executor(step)
                execution = raw if isinstance(raw, ExecutionResult) else ExecutionResult(output=raw)
                verification = self.verifier.verify(execution.output, step.get("verification", ()))
                self.repository.transition_step(
                    step["step_id"], "verifying", "執行器已回傳結果，進入驗收",
                    result={
                        "output": execution.output,
                        "provider_id": execution.provider_id,
                        "evidence": dict(execution.evidence),
                    },
                )
                final_status = "completed" if verification.passed else "failed"
                saved = self.repository.transition_step(
                    step["step_id"], final_status,
                    "驗收通過" if verification.passed else "驗收未通過",
                    verification=verification.to_dict(),
                )
                results.append({
                    "step_id": step["step_id"], "status": final_status,
                    "verification": verification.to_dict(), "task_status": saved["task_status"],
                })
            except Exception as exc:
                try:
                    self.repository.transition_step(
                        step["step_id"], "failed",
                        f"執行器錯誤：{type(exc).__name__}: {str(exc)[:300]}",
                    )
                except (KeyError, ValueError, PermissionError):
                    pass
                results.append({
                    "step_id": step["step_id"], "status": "failed",
                    "error_type": type(exc).__name__,
                })
        return results

    def route_model(self, request: ModelRequest) -> dict[str, Any]:
        if self.model_router is None:
            raise RuntimeError("尚未設定 ModelRouter")
        return self.model_router.generate(request)
