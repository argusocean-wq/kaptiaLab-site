"""Deterministic orchestration policy owned by Kaptia, not the base language model.

The base model generates language. This module selects bounded workflow metadata
using explicit, testable rules; it does not claim semantic understanding.
"""
from pathlib import Path

LONG_TASK_TERMS = (
    "完整專案", "完整計畫", "完整方案", "詳細報告", "完整文件", "逐步", "分階段",
    "長篇", "企劃書", "研究報告", "full project", "full report", "step by step",
    "detailed plan", "comprehensive",
)
FILE_TERMS = (
    "建立檔案", "輸出檔案", "產生檔案", "匯出檔案", "做成檔案", "下載檔案",
    "建立文件", "產生文件", "製作簡報", "輸出成", "save as", "export file",
    "create a file", "generate a document",
)
RESEARCH_TERMS = (
    "最新", "目前價格", "今天", "近期", "現在是否", "查網路", "搜尋網路",
    "來源查證", "最新消息", "latest", "current price", "today", "recent",
    "search the web", "verify sources", "latest news",
)
OUTPUT_TERMS = {
    "code": ("程式碼", "寫程式", "修程式", "debug", "python", "javascript", "lua", "程式", "code", "script"),
    "presentation": ("簡報", "投影片", "powerpoint", "pptx", "slides"),
    "document": ("報告", "企劃書", "文件", "論文", "docx", "report", "proposal", "document"),
    "table": ("表格", "比較表", "csv", "table", "spreadsheet"),
}


def build_plan(user_text):
    """Return bounded workflow metadata without spending an LLM call on JSON planning."""
    if not isinstance(user_text, str) or not user_text.strip():
        raise ValueError("user_text 必須是非空字串")
    if len(user_text) > 20000:
        raise ValueError("user_text 超過 20000 字元上限")

    text = user_text.casefold()
    output_type = "text"
    for candidate, terms in OUTPUT_TERMS.items():
        if any(term.casefold() in text for term in terms):
            output_type = candidate
            break

    long_task = len(user_text) >= 900 or any(term.casefold() in text for term in LONG_TASK_TERMS)
    needs_file = any(term.casefold() in text for term in FILE_TERMS)
    needs_research = any(term.casefold() in text for term in RESEARCH_TERMS)

    if long_task:
        outline = ["目標與背景", "需求與設計", "實作與驗收", "限制與後續工作"]
        checks = ["逐段遵守原始需求", "避免重複內容", "明確區分已驗證與未驗證事項"]
    else:
        outline = []
        checks = ["直接回答原始需求", "避免捏造來源或執行結果"]

    assumptions = [
        "工作流程分類由明確規則決定，不代表已完整理解語意。",
        "需要外部資料時，必須由實際可用且成功執行的來源工具查證。",
    ]
    return {
        "task_size": "long" if long_task else "short",
        "output_type": output_type,
        "needs_research": needs_research,
        "needs_file": needs_file,
        "outline": outline,
        "assumptions": assumptions,
        "checks": checks,
        "planner": "kaptia_deterministic_rules_v1",
    }
