"""Fast and deep task execution policies for Kaptia chat.

Deep mode is deliberately transparent: model self-review is not represented as an
executed test. Only externally supplied validator results may count as passed/failed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Any

MODES = ("fast", "deep")


@dataclass
class TestReport:
    passed: list[str]
    failed: list[str]
    pending: list[str]

    @property
    def total(self) -> int:
        return len(self.passed) + len(self.failed) + len(self.pending)

    def render(self) -> str:
        return (
            f"測試項目：{self.total} 項｜通過：{len(self.passed)}｜"
            f"未通過：{len(self.failed)}｜尚未執行：{len(self.pending)}\n"
            + _section("通過", self.passed)
            + _section("未通過", self.failed)
            + _section("尚未執行", self.pending)
        )


def _section(title: str, items: list[str]) -> str:
    body = "\n".join(f"- {item}" for item in items) if items else "- 無"
    return f"\n[{title}]\n{body}\n"


def normalize_mode(value: str) -> str:
    value = value.strip().lower()
    aliases = {"quick": "fast", "快速": "fast", "深度思考": "deep", "deep-thinking": "deep"}
    value = aliases.get(value, value)
    if value not in MODES:
        raise ValueError("模式只支援 fast 或 deep。")
    return value


def fast_prompt(user_request: str) -> str:
    return (
        "你正在 Kaptia 快速模式。優先以最短可靠路徑完成需求；"
        "不得省略必要的事實核對、邏輯檢查或安全限制。"
        "不確定時明確標示，不得猜測或宣稱未執行的測試已通過。"
        "先給可直接使用的結果，再簡短列出限制。\n\n"
        f"使用者需求：\n{user_request}"
    )


def deep_analysis_prompt(user_request: str) -> str:
    return (
        "你正在 Kaptia 深度思考模式。現在只做需求理解，不要開始產出最終成果。"
        "請輸出：1. 需求重述 2. 明確目標 3. 範圍內/範圍外 "
        "4. 假設與未知 5. 驗收標準 6. 風險與依賴。"
        "不可把推測當成使用者已確認的要求。\n\n"
        f"原始需求：\n{user_request}"
    )


def deep_baseline_prompt(user_request: str, analysis: str) -> str:
    return (
        "根據需求分析，先製作最小但完整、可檢查的基礎版本。"
        "不要過早加入非必要細節。輸出成果、設計決策、已知限制及如何驗證。"
        "不可聲稱未執行的測試通過。\n\n"
        f"原始需求：\n{user_request}\n\n需求分析：\n{analysis}"
    )


def deep_test_plan_prompt(user_request: str, analysis: str, baseline: str) -> str:
    return (
        "你是測試規劃器。針對基礎成果拆分可觀察、可判定的驗收項目。"
        "只輸出 JSON，不要 Markdown fence，格式："
        '{"tests":[{"id":"T01","name":"...","method":"...","expected":"...","status":"pending"}]}。'
        "每項 status 必須為 pending；你不能自行宣稱測試通過，"
        "因為目前尚未有外部測試執行結果。測試需涵蓋正常、邊界、錯誤處理、回歸與需求符合性。\\n\\n"
        f"需求：\n{user_request}\n\n分析：\n{analysis}\n\n基礎成果：\n{baseline}"
    )


def parse_test_plan(raw: str) -> TestReport:
    text = raw.strip()
    text = re.sub(r"^\`\`\`(?:json)?\s*|\s*\`\`\`$", "", text, flags=re.I)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return TestReport([], [], ["測試計畫格式無法解析；需要人工修正 JSON 後才能建立測試清單。"])
    tests = data.get("tests") if isinstance(data, dict) else None
    if not isinstance(tests, list):
        return TestReport([], [], ["測試計畫缺少 tests 陣列；需要重新產生。"])
    pending = []
    seen = set()
    for index, item in enumerate(tests, 1):
        if not isinstance(item, dict):
            pending.append(f"T{index:02d}：測試項目格式無效")
            continue
        name = str(item.get("name", "")).strip() or f"未命名測試 T{index:02d}"
        identifier = str(item.get("id", f"T{index:02d}"))
        if identifier in seen:
            pending.append(f"{identifier}：重複 ID，需修正")
        else:
            seen.add(identifier)
            pending.append(f"{identifier} {name}")
    if not pending:
        pending.append("模型未提供測試項目；需重新建立測試計畫。")
    return TestReport([], [], pending)


def deep_refinement_prompt(user_request: str, baseline: str, report: TestReport) -> str:
    return (
        "根據測試報告進行細化。先修正所有未通過項目；對尚未執行項目，"
        "只能補上可驗證性、測試方法或標示待驗證，不可將它們寫成通過。"
        "保留已符合的基礎功能，避免無關重寫。輸出：修正後成果、逐項變更、"
        "仍待執行的測試。\n\n"
        f"需求：\n{user_request}\n\n基礎成果：\n{baseline}\n\n"
        f"目前測試報告：\n{report.render()}"
    )


def run_deep_workflow(generate: Callable[..., str], user_request: str,
                      max_new_tokens: int = 768) -> tuple[str, dict[str, Any]]:
    """Run staged requirement analysis, baseline, test decomposition, and refinement."""
    analysis = generate([{"role": "user", "content": deep_analysis_prompt(user_request)}],
                        max_new_tokens=max_new_tokens, temperature=0.2)
    baseline = generate([{"role": "user", "content": deep_baseline_prompt(user_request, analysis)}],
                        max_new_tokens=max_new_tokens, temperature=0.2)
    plan = generate([{"role": "user", "content": deep_test_plan_prompt(user_request, analysis, baseline)}],
                    max_new_tokens=max_new_tokens, temperature=0.1)
    report = parse_test_plan(plan)
    refined = generate([{"role": "user", "content": deep_refinement_prompt(user_request, baseline, report)}],
                       max_new_tokens=max_new_tokens, temperature=0.2)
    output = (
        "【需求理解】\n" + analysis + "\n\n"
        "【基礎版本】\n" + baseline + "\n\n"
        "【測試拆分】\n" + report.render() + "\n"
        "注意：以上項目尚未由外部測試器實際執行；模型自我檢查不等於測試通過。\n\n"
        "【細化版本】\n" + refined
    )
    meta = {"analysis": analysis, "baseline": baseline, "test_plan_raw": plan,
            "passed": 0, "failed": 0, "pending": report.total}
    return output, meta
