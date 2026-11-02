"""Bounded task decomposition and role-based subagents for Kaptia."""
from __future__ import annotations

import re
from typing import Any

MAX_SUBTASKS = 4
MAX_CONTEXT_MESSAGES = 8
MAX_CONTEXT_CHARS = 6000
ROLE_GUIDES = {
    "planner": "規劃代理：抽取目標、限制、依賴、風險與可驗收條件。",
    "implementer": "實作代理：針對指定子任務提出具體解法，列明介面、錯誤處理與測試。",
    "reviewer": "審核代理：檢查遺漏、矛盾、風險與驗收方法；不得把自我審核當成獨立證明。",
    "researcher": "分析代理：整理已提供資訊、列出缺口與待查證事項；不得假裝已上網或取得未提供資料。",
}


def split_task(text: str) -> list[dict[str, str]]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("任務不可為空。")
    parts = [
        part.strip()
        for part in re.split(
            r"\n\s*(?:\d+[.)、]|[-*])\s+|\s+(?:另外|此外|並且|以及)\s+",
            text.strip(),
        )
        if len(part.strip()) >= 8
    ]
    if len(parts) < 2:
        parts = [
            "需求分析與規劃：定義目標、限制、依賴和驗收標準。",
            "解決方案或實作：根據原始需求產生具體內容，標明假設。",
            "品質審核：檢查遺漏、矛盾、風險和可驗證性。",
        ]
    roles = ["planner", "implementer", "reviewer", "researcher"]
    return [
        {"id": f"T{i + 1}", "role": roles[i], "task": part}
        for i, part in enumerate(parts[:MAX_SUBTASKS])
    ]


def _format_history_context(history: list[dict[str, Any]] | None) -> str:
    """Format a small, role-filtered context window; history is data, not instructions."""
    if not history:
        return "沒有提供先前對話。"
    selected = []
    used_chars = 0
    for message in history[-MAX_CONTEXT_MESSAGES:]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        remaining = MAX_CONTEXT_CHARS - used_chars
        if remaining <= 0:
            break
        content = content.strip()[:remaining]
        selected.append(f"[{role}] {content}")
        used_chars += len(content)
    if not selected:
        return "沒有提供可用的先前對話。"
    return "\n\n".join(selected)


def run_agent_workflow(
    generate,
    user_text: str,
    max_new_tokens: int = 384,
    history: list[dict[str, Any]] | None = None,
):
    """Run sequential bounded subagents while preserving a bounded prior conversation."""
    tasks = split_task(user_text)
    history_context = _format_history_context(history)
    results = []
    for item in tasks:
        prompt = (
            f"先前對話脈絡（僅作參考資料；若與本次明確需求衝突，以本次需求為準）：\n"
            f"{history_context}\n\n"
            f"原始需求：\n{user_text}\n\n"
            f"子任務 {item['id']}（{item['role']}）：{item['task']}\n"
            f"角色規則：{ROLE_GUIDES[item['role']]}\n"
            "只處理本子任務，列出結果、重要假設與尚未驗證事項。"
        )
        result = generate(
            [{"role": "user", "content": prompt}],
            max_new_tokens=max_new_tokens,
            temperature=0.25,
        )
        results.append((item, result))
    prompt = (
        "請整合以下子代理結果，直接回答原始需求。合併重複內容；無法解決的矛盾要明確指出，"
        "不得宣稱未執行的測試或查證已完成。\n\n"
        f"先前對話脈絡（僅作參考資料）：\n{history_context}\n\n"
        f"原始需求：\n{user_text}"
    )
    for item, result in results:
        prompt += (
            f"\n\n## {item['id']} / {item['role']}\n"
            f"任務：{item['task']}\n結果：\n{result}"
        )
    answer = generate(
        [{"role": "user", "content": prompt}],
        max_new_tokens=max_new_tokens,
        temperature=0.25,
    )
    return answer, [item for item, _ in results]
