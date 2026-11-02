"""Per-installation persistent conversation memory for Kaptia.

Memory is stored under the current OS user's home directory, never in the repository
or sent to a remote service by this module. This v1 retains recent chat turns rather
than claiming semantic memory or consciousness.
"""
from __future__ import annotations

import gzip
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 4_000_000
MAX_STORED_MESSAGES = 2000
MAX_MESSAGE_CHARS = 20_000


def _data_dir() -> Path:
    override = os.environ.get("KAPTIA_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "Kaptia"
    if os.environ.get("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]) / "kaptia"
    return Path.home() / ".kaptia"


def memory_path() -> Path:
    return _data_dir() / "memory" / "conversation.jsonl"


def _valid_row(row: object) -> bool:
    return (
        isinstance(row, dict)
        and row.get("schema_version") == SCHEMA_VERSION
        and row.get("role") in {"user", "assistant"}
        and isinstance(row.get("content"), str)
        and len(row["content"]) <= MAX_MESSAGE_CHARS
    )


def _read_rows() -> list[dict]:
    path = memory_path()
    if not path.exists():
        return []
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(
            f"Kaptia 本機記憶超過 {MAX_FILE_BYTES} bytes 上限；"
            "為避免自動丟棄資料，請先匯出或手動整理。"
        )
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Kaptia 本機記憶第 {line_no} 行格式損壞。") from exc
        if not _valid_row(row):
            raise ValueError(f"Kaptia 本機記憶第 {line_no} 行不符合支援的格式。")
        rows.append(row)
    return rows


def _archive_rows(rows: list[dict]) -> Path | None:
    """Persist evicted messages as an immutable compressed archive before active-file rewrite."""
    if not rows:
        return None
    archive_dir = memory_path().parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = archive_dir / f"conversation-{stamp}-{uuid.uuid4().hex[:8]}.jsonl.gz"
    temp = target.with_suffix(target.suffix + ".tmp")
    try:
        with gzip.open(temp, "wt", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        temp.replace(target)
        return target
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def load_recent_messages(max_messages: int = 12, max_chars: int = 20_000) -> list[dict[str, str]]:
    """Load newest messages within strict count and character budgets."""
    if isinstance(max_messages, bool) or not isinstance(max_messages, int) or not 1 <= max_messages <= 100:
        raise ValueError("max_messages 必須介於 1 到 100")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1000 <= max_chars <= 40000:
        raise ValueError("max_chars 必須介於 1000 到 40000")
    rows = _read_rows()
    result: list[dict[str, str]] = []
    total = 0
    for row in reversed(rows[-max_messages:]):
        item = {"role": row["role"], "content": row["content"]}
        if result and total + len(item["content"]) > max_chars:
            break
        if len(item["content"]) > max_chars:
            item["content"] = item["content"][-max_chars:]
        result.append(item)
        total += len(item["content"])
    result.reverse()
    return result


def append_exchange(user_text: str, assistant_text: str) -> None:
    """Persist one completed exchange locally, trimming old rows only when needed."""
    for label, value in (("user_text", user_text), ("assistant_text", assistant_text)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} 必須是非空字串")
        if len(value) > MAX_MESSAGE_CHARS:
            raise ValueError(f"{label} 超過 {MAX_MESSAGE_CHARS} 字元")
    path = memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _read_rows()
    now = datetime.now(timezone.utc).isoformat()
    rows.extend([
        {"schema_version": SCHEMA_VERSION, "timestamp_utc": now, "role": "user", "content": user_text},
        {"schema_version": SCHEMA_VERSION, "timestamp_utc": now, "role": "assistant", "content": assistant_text},
    ])
    if len(rows) > MAX_STORED_MESSAGES:
        overflow = rows[:-MAX_STORED_MESSAGES]
        _archive_rows(overflow)
        rows = rows[-MAX_STORED_MESSAGES:]
    encoded = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if len(encoded.encode("utf-8")) > MAX_FILE_BYTES:
        # Archive complete oldest exchanges; never silently discard conversation data.
        while rows and len(encoded.encode("utf-8")) > MAX_FILE_BYTES:
            evicted = rows[:2] if len(rows) >= 2 else rows[:]
            _archive_rows(evicted)
            rows = rows[len(evicted):]
            encoded = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    temp = path.with_suffix(".jsonl.tmp")
    temp.write_text(encoded, encoding="utf-8", newline="\n")
    temp.replace(path)


def _archive_path(archive_id: str) -> Path:
    """Resolve an archive by its generated basename; never accept arbitrary paths."""
    import re

    if not isinstance(archive_id, str) or not re.fullmatch(
        r"conversation-\d{8}T\d{12}Z-[0-9a-f]{8}\.jsonl\.gz", archive_id
    ):
        raise ValueError("封存識別碼格式無效")
    path = memory_path().parent / "archive" / archive_id
    if not path.is_file():
        raise FileNotFoundError("找不到指定的對話封存")
    return path


def _read_archive_rows(path: Path) -> list[dict]:
    """Read one bounded archive and reject corrupt or oversized data."""
    rows: list[dict] = []
    total_bytes = 0
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            total_bytes += len(line.encode("utf-8"))
            if total_bytes > MAX_FILE_BYTES or line_no > MAX_STORED_MESSAGES:
                raise ValueError("封存內容超出安全讀取上限")
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"封存第 {line_no} 行格式損壞") from exc
            if not _valid_row(row) or not isinstance(row.get("timestamp_utc"), str):
                raise ValueError(f"封存第 {line_no} 行不符合支援的格式")
            rows.append(row)
    return rows


def list_conversation_archives(offset: int = 0, limit: int = 50) -> dict:
    """Return bounded archive metadata, newest first."""
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 不可小於 0")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit 必須介於 1 到 100")
    archive_dir = memory_path().parent / "archive"
    files = sorted(
        archive_dir.glob("conversation-*.jsonl.gz"),
        key=lambda item: item.name,
        reverse=True,
    ) if archive_dir.exists() else []
    selected = files[offset:offset + limit]
    items = []
    for path in selected:
        rows = _read_archive_rows(path)
        user_rows = [row for row in rows if row["role"] == "user"]
        items.append({
            "archive_id": path.name,
            "messages": len(rows),
            "exchanges": len(user_rows),
            "first_timestamp": rows[0].get("timestamp_utc", "") if rows else "",
            "last_timestamp": rows[-1].get("timestamp_utc", "") if rows else "",
            "preview": (user_rows[0]["content"][:180] if user_rows else ""),
            "bytes": path.stat().st_size,
        })
    return {"ok": True, "total": len(files), "offset": offset, "limit": limit, "archives": items}


def read_conversation_archive(archive_id: str, offset: int = 0, limit: int = 200) -> dict:
    """Read a page of messages from one archive for the history viewer."""
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset 不可小於 0")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit 必須介於 1 到 500")
    path = _archive_path(archive_id)
    rows = _read_archive_rows(path)
    return {
        "ok": True,
        "archive_id": path.name,
        "total": len(rows),
        "offset": offset,
        "messages": rows[offset:offset + limit],
    }


def search_conversation_archives(query: str, limit: int = 50) -> dict:
    """Search archived message text with bounded scan and result counts."""
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ValueError("搜尋文字必須介於 1 到 200 字元")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit 必須介於 1 到 100")
    needle = query.casefold()
    archive_dir = memory_path().parent / "archive"
    files = sorted(
        archive_dir.glob("conversation-*.jsonl.gz"),
        key=lambda item: item.name,
        reverse=True,
    ) if archive_dir.exists() else []
    scanned = files[:200]
    matches = []
    for path in scanned:
        for row in _read_archive_rows(path):
            if needle in row["content"].casefold():
                content = row["content"]
                index = content.casefold().find(needle)
                start = max(0, index - 100)
                end = min(len(content), index + len(query) + 180)
                matches.append({
                    "archive_id": path.name,
                    "timestamp_utc": row.get("timestamp_utc", ""),
                    "role": row["role"],
                    "content": content[start:end],
                })
                if len(matches) >= limit:
                    return {"ok": True, "query": query, "matches": matches,
                            "scanned_archives": len(scanned), "total_archives": len(files),
                            "truncated": len(files) > len(scanned) or len(matches) >= limit}
    return {"ok": True, "query": query, "matches": matches,
            "scanned_archives": len(scanned), "total_archives": len(files),
            "truncated": len(files) > len(scanned)}


def restore_conversation_archive(archive_id: str) -> dict:
    """Load one archive as active history after archiving the current active history.

    The source archive is retained as a recovery copy. This is a deliberate
    history switch, not a merge, so the active-history size cap remains intact.
    """
    source = _archive_path(archive_id)
    rows = _read_archive_rows(source)
    encoded = "".join(json.dumps(row, ensure_ascii=False) + "\\n" for row in rows)
    if len(rows) > MAX_STORED_MESSAGES or len(encoded.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("此封存超過目前活躍記憶容量，無法整批還原")
    path = memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _read_rows()
    backup_archive = _archive_rows(current) if current else None
    temp = path.with_suffix(".jsonl.restore.tmp")
    try:
        temp.write_text(encoded, encoding="utf-8", newline="\\n")
        temp.replace(path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return {
        "ok": True,
        "restored_messages": len(rows),
        "previous_messages_archived": len(current),
        "previous_history_archive": backup_archive.name if backup_archive else None,
        "source_archive_retained": True,
    }


def clear_memory() -> None:
    """Delete this installation user's active and archived conversation history."""
    path = memory_path()
    if path.exists():
        path.unlink()
    archive_dir = path.parent / "archive"
    if archive_dir.exists():
        for archive in archive_dir.glob("conversation-*.jsonl.gz"):
            archive.unlink()
        try:
            archive_dir.rmdir()
        except OSError:
            pass


def memory_status() -> dict[str, object]:
    rows = _read_rows()
    archive_dir = memory_path().parent / "archive"
    archives = list(archive_dir.glob("conversation-*.jsonl.gz")) if archive_dir.exists() else []
    return {
        "path": str(memory_path()),
        "messages": len(rows),
        "exchanges": sum(1 for row in rows if row["role"] == "assistant"),
        "bytes": memory_path().stat().st_size if memory_path().exists() else 0,
        "archive_files": len(archives),
        "archive_bytes": sum(item.stat().st_size for item in archives),
        "storage": "local-only",
    }
