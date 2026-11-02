"""Persistent task journal with validated state transitions.

This records workflow metadata only; it does not serialize model runtime state
or claim that an interrupted generation can resume token-for-token.
"""
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = ROOT / "state" / "tasks.json"
MAX_FILE_BYTES = 2_000_000
MAX_TASKS = 500
MAX_TEXT = 4000
STATUSES = {"queued", "in_progress", "blocked", "completed", "failed", "cancelled"}
TRANSITIONS = {
    "queued": {"in_progress", "cancelled"},
    "in_progress": {"blocked", "completed", "failed", "cancelled"},
    "blocked": {"in_progress", "failed", "cancelled"},
    "completed": set(), "failed": set(), "cancelled": set(),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise ValueError(f"{field} 必須為 1–{MAX_TEXT} 字元的非空字串")
    return value.strip()


def _load(path=None):
    path = Path(path or TASKS_PATH)
    if not path.exists():
        return {"schema_version": 1, "tasks": []}
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("任務資料檔超過大小限制")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("tasks"), list):
        raise ValueError("任務資料格式無效")
    if len(data["tasks"]) > MAX_TASKS:
        raise ValueError("任務數量超過限制")
    return data


def _save(data, path=None):
    path = Path(path or TASKS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if len(payload.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("儲存後任務資料超過大小限制")
    fd, temp_name = tempfile.mkstemp(prefix=".tasks-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def create_task(title, detail, path=None):
    title, detail = _text(title, "title"), _text(detail, "detail")
    data = _load(path)
    if len(data["tasks"]) >= MAX_TASKS:
        raise ValueError("任務數量已達上限")
    task = {
        "id": uuid.uuid4().hex,
        "title": title,
        "detail": detail,
        "status": "queued",
        "created_at": _now(),
        "updated_at": _now(),
        "events": [{"at": _now(), "type": "created", "detail": "任務已建立"}],
    }
    data["tasks"].append(task)
    _save(data, path)
    return task


def transition_task(task_id, status, detail, path=None):
    if status not in STATUSES:
        raise ValueError("未知任務狀態")
    detail = _text(detail, "detail")
    data = _load(path)
    task = next((item for item in data["tasks"] if item.get("id") == task_id), None)
    if task is None:
        raise KeyError("找不到指定任務")
    old = task.get("status")
    if status not in TRANSITIONS.get(old, set()):
        raise ValueError(f"不允許的狀態轉換：{old} -> {status}")
    task["status"] = status
    task["updated_at"] = _now()
    task.setdefault("events", []).append({
        "at": _now(), "type": "status_change",
        "from": old, "to": status, "detail": detail,
    })
    _save(data, path)
    return task


def list_tasks(status=None, limit=100, path=None):
    if status is not None and status not in STATUSES:
        raise ValueError("未知任務狀態")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit 必須介於 1 到 200")
    tasks = _load(path)["tasks"]
    if status:
        tasks = [task for task in tasks if task.get("status") == status]
    return tasks[-limit:]
