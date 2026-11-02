"""Run a local, auditable political-neutrality probe suite against Kaptia.

This loads the configured local model and records raw answers for human review.
It does not assign an automated political-bias score or claim factual correctness.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "training" / "evaluations" / "political_neutrality_cases.jsonl"
DEFAULT_OUTPUT = ROOT / "artifacts" / "political_neutrality_results.jsonl"


def load_cases(path):
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: JSON 格式錯誤：{exc}") from exc
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not isinstance(row.get("prompt"), str):
                raise ValueError(f"{path}:{line_no}: 每筆資料必須包含字串 id 與 prompt")
            cases.append(row)
    if not cases:
        raise ValueError("測試案例為空")
    ids = [row["id"] for row in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("測試案例 id 重複")
    return cases


def run_suite(cases, generator):
    results = []
    for case in cases:
        started = datetime.now(timezone.utc).isoformat()
        try:
            # Run through the same staged pipeline used by the interactive CLI.
            from kaptia_pipeline import run_workflow
            workflow = run_workflow(generator, case["prompt"])
            answer = workflow.get("content", "")
            events = workflow.get("events", [])
            review = workflow.get("review", {})
            results.append({
                "id": case["id"], "category": case.get("category", "uncategorized"),
                "prompt": case["prompt"], "answer": answer,
                "events": events, "self_review": review,
                "started_at": started,
                "note": "模型自我審核不是獨立政治中立評估；答案需人工依證據與標準覆核。"
            })
        except Exception as exc:
            results.append({
                "id": case["id"], "category": case.get("category", "uncategorized"),
                "prompt": case["prompt"], "error": f"{type(exc).__name__}: {exc}",
                "started_at": started
            })
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="對本機 Kaptia 執行政治敏感議題測試")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    cases = load_cases(args.cases)
    # Lazy import avoids downloading/loading a multi-GB model for help or data validation.
    sys.path.insert(0, str(ROOT / "scripts"))
    from chat import load_language_engine, build_generator
    tokenizer, model = load_language_engine()
    generator = build_generator(tokenizer, model)
    results = run_suite(cases, generator)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({
        "case_count": len(cases), "result_count": len(results),
        "errors": sum("error" in row for row in results),
        "output": str(args.output),
        "review_status": "需要人工覆核；未計算自動政治偏見分數"
    }, ensure_ascii=False, indent=2))
    return 1 if any("error" in row for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
