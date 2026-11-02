"""Explicit project-state memory for Kaptia; does not store chat transcripts.

Records only structured decisions/tasks supplied by the caller. The file is local,
append-only JSONL, size-bounded, and never executes embedded instructions.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "state" / "project_memory.jsonl"
KINDS = {"decision", "task", "note", "blocker"}
STATUSES = {"open", "in_progress", "blocked", "done", "superseded"}
MAX_FIELD = 4000
MAX_FILE_BYTES = 2_000_000


def _clean(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必須是非空字串")
    value = value.strip()
    if len(value) > MAX_FIELD:
        raise ValueError(f"{field} 超過 {MAX_FIELD} 字元")
    return value


def append_record(kind, title, detail, status="open", tags=None):
    if kind not in KINDS:
        raise ValueError(f"kind 必須為 {sorted(KINDS)}")
    if status not in STATUSES:
        raise ValueError(f"status 必須為 {sorted(STATUSES)}")
    title = _clean(title, "title")
    detail = _clean(detail, "detail")
    if tags is None:
        tags = []
    if not isinstance(tags, list) or len(tags) > 20 or any(
        not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9_\-\u3400-\u9fff]{1,40}", tag)
        for tag in tags
    ):
        raise ValueError("tags 必須是最多 20 個、每個 1–40 字元的標籤")
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if MEMORY_PATH.exists() and MEMORY_PATH.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("專案記憶超過大小上限；請先匯出或整理，不會自動刪除舊紀錄")
    record = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "kind": kind, "title": title, "detail": detail,
        "status": status, "tags": tags,
    }
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with MEMORY_PATH.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
    return record


def list_records(kind=None, status=None, query=None, limit=50):
    if kind is not None and kind not in KINDS:
        raise ValueError("kind 無效")
    if status is not None and status not in STATUSES:
        raise ValueError("status 無效")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError("limit 必須介於 1 到 200")
    if query is not None and (not isinstance(query, str) or len(query) > 500):
        raise ValueError("query 必須不超過 500 字元")
    if not MEMORY_PATH.exists():
        return []
    if MEMORY_PATH.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("專案記憶超過大小上限")
    records = []
    for line_no, line in enumerate(MEMORY_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("schema_version") != 1 or row.get("kind") not in KINDS:
            raise ValueError(f"第 {line_no} 行的記憶格式無效")
        if kind and row["kind"] != kind:
            continue
        if status and row.get("status") != status:
            continue
        if query and query.casefold() not in (row.get("title", "") + "\n" + row.get("detail", "")).casefold():
            continue
        records.append(row)
    return records[-limit:]


if __name__ == "__main__":
    print(json.dumps({"memory_file": str(MEMORY_PATH),
                      "records": len(list_records()),
                      "note": "僅儲存明確寫入的專案決策、任務、備註與阻礙；不自動保存對話。"},
                     ensure_ascii=False, indent=2))
