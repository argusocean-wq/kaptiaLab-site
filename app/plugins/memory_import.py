"""Preview-first import of external AI conversations into Kaptia local history.

Imports are selected by conversation and require explicit local confirmation.
Imported text remains conversation data, never system instructions.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MAX_IMPORT_BYTES = 4_000_000
MAX_MESSAGES = 2000
MAX_SOURCE_MESSAGES = 20_000
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


def _make_conversation(title: str, messages: list[dict], index: int, source_id: Any = None) -> dict:
    clean_title = title.strip()[:200] if isinstance(title, str) and title.strip() else f"Imported conversation {index}"
    stable_id = str(source_id).strip() if isinstance(source_id, (str, int)) and str(source_id).strip() else ""
    if not stable_id or len(stable_id) > 200:
        stable_id = hashlib.sha256(f"{index}\0{clean_title}".encode("utf-8")).hexdigest()[:24]
    return {"id": stable_id, "title": clean_title, "messages": messages}


def _normalize_json(data: Any) -> list[dict]:
    if isinstance(data, dict) and isinstance(data.get("conversations"), list):
        data = data["conversations"]
    if isinstance(data, dict) and isinstance(data.get("mapping"), dict):
        return [_make_conversation(data.get("title", ""), _chatgpt_messages(data), 1, data.get("id"))]
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        data = data["messages"]
    if isinstance(data, list):
        chatgpt = [item for item in data if isinstance(item, dict) and isinstance(item.get("mapping"), dict)]
        if chatgpt:
            return [
                _make_conversation(item.get("title", ""), _chatgpt_messages(item), index,
                                   item.get("id"))
                for index, item in enumerate(chatgpt, 1)
            ]
        messages = []
        for item in data:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = _text_content(item.get("content", item.get("text", ""))).strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        return [_make_conversation("Imported conversation", messages, 1)] if messages else []
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
            conversations = _normalize_json(json.loads(raw))
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
            if isinstance(row, dict) and row.get("role") in {"user", "assistant"}:
                text = _text_content(row.get("content", row.get("text", ""))).strip()
                if text:
                    messages.append({"role": row["role"], "content": text})
        conversations = [_make_conversation(source.stem, messages, 1)]
    else:
        conversations = [_make_conversation(source.stem, [{"role": "user", "content": raw.strip()}] if raw.strip() else [], 1)]
    normalized_conversations = []
    for conversation in conversations:
        normalized = []
        for item in conversation.get("messages", []):
            role, content = item.get("role"), item.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
                continue
            content = content.strip()
            if len(content) > MAX_MESSAGE_CHARS:
                content = content[:MAX_MESSAGE_CHARS] + "\n[匯入截斷：單則訊息超過 20,000 字元]"
            normalized.append({"role": role, "content": content})
        if normalized:
            normalized_conversations.append(_make_conversation(
                conversation.get("title", ""), normalized,
                len(normalized_conversations) + 1, conversation.get("id")))
    total = sum(len(item["messages"]) for item in normalized_conversations)
    if not total:
        raise MemoryImportError("檔案中沒有可匯入的 user/assistant 對話內容。")
    if total > MAX_SOURCE_MESSAGES:
        raise MemoryImportError(f"來源訊息超過 {MAX_SOURCE_MESSAGES} 則安全解析上限；請分割匯出檔。")
    flat = [message for conversation in normalized_conversations for message in conversation["messages"]]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {
        "source_name": source.name, "source_sha256": digest, "count": total,
        "conversation_count": len(normalized_conversations),
        "user_messages": sum(x["role"] == "user" for x in flat),
        "assistant_messages": sum(x["role"] == "assistant" for x in flat),
        "conversations": [{
            "id": item["id"], "title": item["title"], "count": len(item["messages"]),
            "user_messages": sum(x["role"] == "user" for x in item["messages"]),
            "assistant_messages": sum(x["role"] == "assistant" for x in item["messages"]),
            "preview": [{"role": x["role"], "content": x["content"][:180]} for x in item["messages"][:2]],
        } for item in normalized_conversations],
        "messages": flat,
        "preview": [{"role": x["role"], "content": x["content"][:240]} for x in flat[:6]],
        "_conversation_data": normalized_conversations,
    }


def import_memory_file(path: str | Path, *, locally_confirmed: bool = False,
                       expected_sha256: str | None = None,
                       selected_conversation_ids: list[str] | None = None) -> dict:
    if locally_confirmed is not True:
        raise MemoryImportError("匯入前必須由使用者在 Kaptia Desktop 確認預覽內容。")
    parsed = parse_memory_file(path)
    if expected_sha256 is not None and parsed["source_sha256"] != expected_sha256:
        raise MemoryImportError("檔案在預覽後已變更；請重新預覽，再確認匯入。")
    conversations = parsed["_conversation_data"]
    if selected_conversation_ids is None:
        selected = conversations
    else:
        if not isinstance(selected_conversation_ids, list) or not selected_conversation_ids:
            raise MemoryImportError("請至少選擇一段要匯入的對話。")
        if any(not isinstance(x, str) for x in selected_conversation_ids) or len(set(selected_conversation_ids)) != len(selected_conversation_ids):
            raise MemoryImportError("對話選取清單格式無效或包含重複項目。")
        wanted = set(selected_conversation_ids)
        selected = [item for item in conversations if item["id"] in wanted]
        if len(selected) != len(wanted):
            raise MemoryImportError("選取的對話不存在於這份匯出檔。")
    messages = [message for item in selected for message in item["messages"]]
    if len(messages) > MAX_MESSAGES:
        raise MemoryImportError(f"選取的訊息超過 {MAX_MESSAGES} 則上限；請減少選取的對話。")
    try:
        from kaptia_personal_memory import import_messages
    except ImportError:
        from scripts.kaptia_personal_memory import import_messages
    result = import_messages(messages, source_ref=parsed["source_sha256"], locally_confirmed=True)
    return {
        "ok": True, "source_name": parsed["source_name"], "source_sha256": parsed["source_sha256"],
        "imported": result["imported"], "duplicates": result["duplicates"],
        "total_messages": result["total_messages"], "count": len(messages),
        "selected_conversation_count": len(selected),
        "selected_conversations": [item["title"] for item in selected],
    }
