"""SQLite-backed task journal with transactional claiming and auditable transitions."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
import uuid

from .contracts import TaskPlan, utc_now

DEFAULT_DB = Path(__file__).resolve().parents[1] / "state" / "core_foundation.sqlite3"
STEP_TRANSITIONS = {
    "pending": {"running", "cancelled"},
    "running": {"verifying", "failed", "blocked", "cancelled"},
    "verifying": {"completed", "failed"},
    "blocked": {"pending", "cancelled"},
    "failed": {"pending", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class TaskRepository:
    """Small durable repository; every mutation is committed in a SQLite transaction."""

    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_steps (
                    step_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    worker_id TEXT,
                    required_capabilities_json TEXT NOT NULL,
                    data_classification TEXT NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    verification_json TEXT NOT NULL,
                    result_json TEXT,
                    verification_result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, step_id)
                );
                CREATE TABLE IF NOT EXISTS step_dependencies (
                    step_id TEXT NOT NULL REFERENCES task_steps(step_id) ON DELETE CASCADE,
                    depends_on_step_id TEXT NOT NULL REFERENCES task_steps(step_id) ON DELETE CASCADE,
                    PRIMARY KEY(step_id, depends_on_step_id),
                    CHECK(step_id <> depends_on_step_id)
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                    step_id TEXT,
                    event_type TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_steps_status ON task_steps(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, event_id);
            """)

    @staticmethod
    def _event(conn: sqlite3.Connection, task_id: str, step_id: str | None,
               event_type: str, detail: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO task_events(task_id, step_id, event_type, detail_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (task_id, step_id, event_type, json.dumps(detail, ensure_ascii=False), utc_now()),
        )

    @staticmethod
    def _refresh_task_status(conn: sqlite3.Connection, task_id: str) -> str:
        rows = conn.execute("SELECT status FROM task_steps WHERE task_id=?", (task_id,)).fetchall()
        statuses = [row["status"] for row in rows]
        if statuses and all(status == "completed" for status in statuses):
            status = "completed"
        elif any(item == "failed" for item in statuses):
            status = "failed"
        elif any(item in {"running", "verifying"} for item in statuses):
            status = "running"
        elif any(item == "blocked" for item in statuses):
            status = "blocked"
        elif statuses and all(item == "cancelled" for item in statuses):
            status = "cancelled"
        else:
            status = "queued"
        conn.execute("UPDATE tasks SET status=?, updated_at=? WHERE task_id=?", (status, utc_now(), task_id))
        return status

    def create_plan(self, plan: TaskPlan) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO tasks(task_id,title,objective,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (plan.task_id, plan.title, plan.objective, "queued", plan.created_at or now, now),
            )
            for step in plan.steps:
                conn.execute(
                    """INSERT INTO task_steps(
                        step_id,task_id,title,objective,agent_id,required_capabilities_json,
                        data_classification,max_attempts,attempts,status,verification_json,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (step.step_id, plan.task_id, step.title, step.objective, step.agent_id,
                     json.dumps(list(step.required_capabilities)),
                     step.data_classification, step.max_attempts, 0, "pending",
                     json.dumps([dict(item) for item in step.verification], ensure_ascii=False), now, now),
                )
            for step in plan.steps:
                for dependency in step.depends_on:
                    conn.execute(
                        "INSERT INTO step_dependencies(step_id,depends_on_step_id) VALUES(?,?)",
                        (step.step_id, dependency),
                    )
            self._event(conn, plan.task_id, None, "task_created", {"title": plan.title, "step_count": len(plan.steps)})
            return self.get_task(plan.task_id, connection=conn)

    def claim_ready_steps(self, worker_id: str, limit: int = 1) -> list[dict[str, Any]]:
        if not isinstance(worker_id, str) or not worker_id.strip() or len(worker_id) > 120:
            raise ValueError("worker_id 必須是 1–120 字元的非空字串")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 16:
            raise ValueError("limit 必須介於 1 到 16")
        claimed = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("""
                SELECT s.* FROM task_steps s
                JOIN tasks t ON t.task_id=s.task_id
                WHERE s.status='pending' AND t.status NOT IN ('failed','cancelled')
                  AND NOT EXISTS (
                    SELECT 1 FROM step_dependencies d
                    JOIN task_steps dep ON dep.step_id=d.depends_on_step_id
                    WHERE d.step_id=s.step_id AND dep.status <> 'completed'
                  )
                ORDER BY s.created_at, s.step_id
                LIMIT ?
            """, (limit,)).fetchall()
            for row in rows:
                now = utc_now()
                conn.execute(
                    "UPDATE task_steps SET status='running',worker_id=?,attempts=attempts+1,updated_at=? WHERE step_id=? AND status='pending'",
                    (worker_id.strip(), now, row["step_id"]),
                )
                if conn.execute("SELECT changes()").fetchone()[0] != 1:
                    continue
                self._event(conn, row["task_id"], row["step_id"], "step_claimed", {"worker_id": worker_id.strip()})
                self._refresh_task_status(conn, row["task_id"])
                claimed.append(self._step_dict(conn.execute(
                    "SELECT * FROM task_steps WHERE step_id=?", (row["step_id"],)
                ).fetchone()))
            return claimed

    def transition_step(
        self, step_id: str, new_status: str, detail: str,
        *, result: dict[str, Any] | None = None,
        verification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(detail, str) or not detail.strip() or len(detail) > 2000:
            raise ValueError("detail 必須是 1–2000 字元的非空字串")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM task_steps WHERE step_id=?", (step_id,)).fetchone()
            if row is None:
                raise KeyError("找不到指定步驟")
            old_status = row["status"]
            if new_status not in STEP_TRANSITIONS.get(old_status, set()):
                raise ValueError(f"不允許的步驟狀態轉換：{old_status} -> {new_status}")
            if new_status == "completed":
                if old_status != "verifying" or not isinstance(verification, dict) or verification.get("passed") is not True:
                    raise PermissionError("步驟必須具有通過的驗收結果才能完成")
            if result is not None and not isinstance(result, dict):
                raise ValueError("result 必須是 JSON object")
            if verification is not None and not isinstance(verification, dict):
                raise ValueError("verification 必須是 JSON object")
            now = utc_now()
            conn.execute(
                """UPDATE task_steps SET status=?,result_json=COALESCE(?,result_json),
                   verification_result_json=COALESCE(?,verification_result_json),updated_at=? WHERE step_id=?""",
                (new_status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                 json.dumps(verification, ensure_ascii=False) if verification is not None else None,
                 now, step_id),
            )
            self._event(conn, row["task_id"], step_id, "step_status_changed", {
                "from": old_status, "to": new_status, "detail": detail,
            })
            task_status = self._refresh_task_status(conn, row["task_id"])
            updated = self._step_dict(conn.execute("SELECT * FROM task_steps WHERE step_id=?", (step_id,)).fetchone())
            updated["task_status"] = task_status
            return updated

    def retry_failed_step(self, step_id: str, detail: str = "受控重試") -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM task_steps WHERE step_id=?", (step_id,)).fetchone()
            if row is None:
                raise KeyError("找不到指定步驟")
            if row["status"] not in {"failed", "blocked"}:
                raise ValueError("只有 failed 或 blocked 步驟可以重新排入")
            if row["attempts"] >= row["max_attempts"]:
                raise ValueError("已達最大嘗試次數")
            conn.execute(
                "UPDATE task_steps SET status='pending',worker_id=NULL,result_json=NULL,verification_result_json=NULL,updated_at=? WHERE step_id=?",
                (utc_now(), step_id),
            )
            self._event(conn, row["task_id"], step_id, "step_requeued", {"detail": detail, "attempts": row["attempts"]})
            self._refresh_task_status(conn, row["task_id"])
            return self._step_dict(conn.execute("SELECT * FROM task_steps WHERE step_id=?", (step_id,)).fetchone())

    @staticmethod
    def _step_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "step_id": row["step_id"], "task_id": row["task_id"], "title": row["title"],
            "objective": row["objective"], "agent_id": row["agent_id"], "worker_id": row["worker_id"],
            "required_capabilities": json.loads(row["required_capabilities_json"]),
            "data_classification": row["data_classification"], "max_attempts": row["max_attempts"],
            "attempts": row["attempts"], "status": row["status"],
            "verification": json.loads(row["verification_json"]),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "verification_result": json.loads(row["verification_result_json"]) if row["verification_result_json"] else None,
        }

    def get_task(self, task_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
        own = connection is None
        conn = connection or self._connect()
        try:
            task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise KeyError("找不到指定任務")
            steps = conn.execute("SELECT * FROM task_steps WHERE task_id=? ORDER BY created_at,step_id", (task_id,)).fetchall()
            events = conn.execute("SELECT * FROM task_events WHERE task_id=? ORDER BY event_id", (task_id,)).fetchall()
            return {
                "task_id": task["task_id"], "title": task["title"], "objective": task["objective"],
                "status": task["status"], "created_at": task["created_at"], "updated_at": task["updated_at"],
                "steps": [self._step_dict(row) for row in steps],
                "events": [{
                    "event_id": row["event_id"], "step_id": row["step_id"], "event_type": row["event_type"],
                    "detail": json.loads(row["detail_json"]), "created_at": row["created_at"],
                } for row in events],
            }
        finally:
            if own:
                conn.close()
