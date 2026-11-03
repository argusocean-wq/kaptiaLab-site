"""Deterministic, fail-closed output verification for M1."""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from .contracts import VerificationResult


class VerificationEngine:
    """Runs only built-in deterministic checks; unknown checks fail closed."""

    def verify(self, output: str, checks: Iterable[Mapping[str, Any]] = ()) -> VerificationResult:
        if not isinstance(output, str):
            output = ""
        specs = list(checks or ({"type": "non_empty"},))
        if len(specs) > 12:
            return VerificationResult(False, (), ("驗收項目超過 12 個上限",))
        results = []
        issues = []
        for index, spec in enumerate(specs, 1):
            if not isinstance(spec, Mapping):
                issues.append(f"CHECK-{index}: 驗收規格必須是 object")
                results.append({"index": index, "type": "invalid", "passed": False})
                continue
            kind = spec.get("type")
            passed = False
            detail = ""
            if kind == "non_empty":
                passed = bool(output.strip())
                detail = "輸出必須非空"
            elif kind == "contains_all":
                values = spec.get("values")
                valid = isinstance(values, list) and bool(values) and all(
                    isinstance(x, str) and x for x in values
                )
                passed = valid and all(value in output for value in values)
                detail = "輸出必須包含所有指定字串" if valid else "values 必須是非空字串清單"
            elif kind == "max_chars":
                limit = spec.get("value")
                valid = isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= 200000
                passed = valid and len(output) <= limit
                detail = f"輸出長度 {len(output)}，上限 {limit}" if valid else "value 必須是 1–200000 的整數"
            elif kind == "json":
                try:
                    json.loads(output)
                    passed = True
                except (json.JSONDecodeError, TypeError):
                    passed = False
                detail = "輸出必須是有效 JSON"
            else:
                detail = f"未知驗收類型：{kind}"
            results.append({"index": index, "type": kind, "passed": bool(passed), "detail": detail})
            if not passed:
                issues.append(f"CHECK-{index}: {detail}")
        return VerificationResult(not issues, tuple(results), tuple(issues))
