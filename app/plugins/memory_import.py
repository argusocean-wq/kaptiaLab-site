"""Import external AI conversation exports into Kaptia's local history.

Imports are previewed first and require an explicit local confirmation. Imported
text remains ordinary conversation data, never system instructions.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MAX_IMPORT_BYTES = 4_000_000
MAX_MESSAGES = 2000
MAX_MESSAGE_CHARS = 20_000
SUPPORTED = {".json", ".jsonl", ".md", ".txt"}


class MemoryImportError(ValueError):
    pass


def _text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for part in (_text_content(x) for x in value) if part)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("parts"), list):
            return _text_content(value["parts"])
    return ""


def _chatgpt_messages(conversation: dict) -> list[dict]:
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        return []
    items = []
    for node in mapping.values():
        message = node.get("message") if isinstance(node, dict) else None
        if not isinstance(message, dict):
            continue
        author = message.get("author") or {}
        role = author.get("role") if isinstance(author, dict) else None
        if role not in {"user", "assistant"}:
            continue
        content = _text_content(message.get("content", {})).strip()
        if not content:
            continue
        timestamp = message.get("create_time")
        items.append((float(timestamp) if isinstance(timestamp, (int, float)) else 0.0,
                      {"role": role, "content": content}))
    items.sort(key=lambda x: x[0])
    return [item for _, item in items]


def _normalize_json(data: Any) -> list[dict]:
    if isinstance(data, dict) and isinstance(data.get("conversations"), list):
        data = data["conversations"]
    if isinstance(data, dict) and isinstance(data.get("mapping"), dict):
        return _chatgpt_messages(data)
    if isinstance(data, list):
        result = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("mapping"), dict):
                result.extend(_chatgpt_messages(item))
            elif isinstance(item, dict):
                role = item.get("role")
                content = _text_content(item.get("content", item.get("text", ""))).strip()
                if role in {"user", "assistant"} and content:
                    result.append({"role": role, "content": content})
        return result
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        return _normalize_json(data["messages"])
    raise MemoryImportError("JSON 格式不受支援；請使用 ChatGPT conversations.json 或 role/content 訊息格式。")


def parse_memory_file(path: str | Path) -> dict:
    source = Path(path).expanduser()
    if source.suffix.lower() not in SUPPORTED or not source.is_file():
        raise MemoryImportError("僅支援 JSON、JSONL、Markdown、TXT 檔案。")
    if source.stat().st_size > MAX_IMPORT_BYTES:
        raise MemoryImportError("匯入檔案不得超過 4 MB。")
    raw = source.read_text(encoding="utf-8-sig")
    suffix = source.suffix.lower()
    if suffix == ".json":
        try:
            messages = _normalize_json(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise MemoryImportError(f"JSON 格式錯誤：第 {exc.lineno} 行。") from None
    elif suffix == ".jsonl":
        messages = []
        for line_no, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                raise MemoryImportError(f"JSONL 第 {line_no} 行格式錯誤。") from None
            messages.extend(_normalize_json([row]))
    else:
        messages = [{"role": "user", "content": raw.strip()}] if raw.strip() else []
    if not messages:
        raise MemoryImportError("檔案中沒有可匯入的 user/assistant 對話內容。")
    if len(messages) > MAX_MESSAGES:
        raise MemoryImportError(f"訊息超過 {MAX_MESSAGES} 則上限；請先分割匯入。")
    normalized = []
    for index, item in enumerate(messages, 1):
        role, content = item.get("role"), item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        content = content.strip()
        if len(content) > MAX_MESSAGE_CHARS:
            content = content[:MAX_MESSAGE_CHARS] + "\n[匯入截斷：單則訊息超過 20,000 字元]"
        normalized.append({"role": role, "content": content})
    if not normalized:
        raise MemoryImportError("沒有符合格式的訊息。")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {"source_name": source.name, "source_sha256": digest, "messages": normalized,
            "count": len(normalized), "user_messages": sum(x["role"] == "user" for x in normalized),
            "assistant_messages": sum(x["role"] == "assistant" for x in normalized),
            "preview": [{"role": x["role"], "content": x["content"][:240]} for x in normalized[:6]]}


def import_memory_file(path: str | Path, *, locally_confirmed: bool = False,
                      expected_sha256: str | None = None) -> dict:
    if locally_confirmed is not True:
        raise MemoryImportError("匯入前必須由使用者在 Kaptia Desktop 確認預覽內容。")
    parsed = parse_memory_file(path)
    if expected_sha256 is not None and parsed["source_sha256"] != expected_sha256:
        raise MemoryImportError("檔案在預覽後已變更；請重新預覽，再確認匯入。")
    try:
        from kaptia_personal_memory import import_messages
    except ImportError:
        from scripts.kaptia_personal_memory import import_messages
    result = import_messages(parsed["messages"], source_ref=parsed["source_sha256"], locally_confirmed=True)
    return {**{k: v for k, v in parsed.items() if k != "messages"}, **result}
