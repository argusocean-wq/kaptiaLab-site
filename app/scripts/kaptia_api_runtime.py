"""Provider adapter for local Hugging Face models or OpenAI-compatible APIs.

Configure with KAPTIA_PROVIDER=local (default) or openai-compatible.
API keys are read from environment variables and never persisted by this module.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

try:
    from kaptia_identity import SYSTEM_PROMPT
except ImportError:
    from scripts.kaptia_identity import SYSTEM_PROMPT


def _normalise_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Always apply Kaptia's persona in ordinary chat without overriding workflow prompts."""
    filtered = [
        {"role": str(message.get("role", "user")), "content": str(message.get("content", ""))}
        for message in messages
        if isinstance(message, dict)
        and message.get("role") in {"system", "user", "assistant"}
    ]
    if not any(message["role"] == "system" for message in filtered):
        filtered.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    # Keep one leading system message and the newest conversational turns within the cap.
    systems = [message for message in filtered if message["role"] == "system"]
    conversation = [message for message in filtered if message["role"] != "system"]
    system_message = systems[0] if systems else {"role": "system", "content": SYSTEM_PROMPT}
    return [system_message, *conversation[-11:]]


def build_api_generator():
    base_url = os.environ.get("KAPTIA_API_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    model = os.environ.get("KAPTIA_API_MODEL", "").strip()
    api_key = os.environ.get("KAPTIA_API_KEY", "").strip()
    timeout = max(5, min(int(os.environ.get("KAPTIA_API_TIMEOUT", "120")), 600))
    if not model:
        raise ValueError("使用 API 模式時必須設定 KAPTIA_API_MODEL。")
    if not base_url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise ValueError("API 位址必須使用 HTTPS；僅允許 localhost 使用 HTTP。")
    if not api_key and not (base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")):
        raise ValueError("缺少 KAPTIA_API_KEY。請使用環境變數設定，勿寫入程式碼或提交到 Git。")

    def generate(messages: list[dict[str, str]], max_new_tokens: int = 512, temperature: float = 0.35) -> str:
        payload = {
            "model": model,
            "messages": _normalise_messages(messages),
            "max_tokens": max(1, min(int(max_new_tokens), 8192)),
            "temperature": max(0.0, min(float(temperature), 2.0)),
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise RuntimeError(f"API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"無法連線至模型 API：{exc.reason}") from exc
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("API 回應格式不符合 OpenAI Chat Completions 規格。") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("API 回傳空白或非文字內容。")
        return content.strip()
    return generate
