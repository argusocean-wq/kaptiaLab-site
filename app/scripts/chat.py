"""Kaptia chat entry with bounded prompt history and explicit-cost subagents."""
from __future__ import annotations

import os
import sys
from kaptia_agents import run_agent_workflow
from kaptia_personal_memory import append_exchange, clear_memory, load_recent_messages, memory_status
from kaptia_modes import normalize_mode, run_deep_workflow, fast_prompt

DEFAULT_INPUT_CHARS = 12_000
DEFAULT_HISTORY_CHARS = 12_000
MAX_HISTORY_MESSAGES = 10
DEFAULT_RESPONSE_TOKENS = 320
DETAILED_RESPONSE_TOKENS = 768


def _env_limit(name: str, default: int, minimum: int, maximum: int) -> int:
    """Read an integer environment setting safely and clamp it to documented bounds."""
    try:
        value = int(os.environ.get(name, str(default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _history_char_count(history: list[dict[str, str]]) -> int:
    return sum(len(item.get("content", "")) for item in history)


def _response_token_budget(user_text: str) -> int:
    """Keep casual replies quick without starving detailed or code-heavy requests."""
    text = user_text.casefold()
    detail_cues = (
        "詳細", "完整", "逐步", "分析", "比較", "解釋", "原因", "範例",
        "程式碼", "寫程式", "除錯", "debug", "python", "javascript",
        "lua", "code", "script", "explain", "detailed", "step by step",
        "implement", "compare", "analyze",
    )
    if any(cue.casefold() in text for cue in detail_cues):
        return DETAILED_RESPONSE_TOKENS
    return DEFAULT_RESPONSE_TOKENS


def _response_temperature(user_text: str) -> float:
    """Allow a little more variation in casual chat and keep technical output focused."""
    text = user_text.casefold()
    technical_cues = ("程式碼", "寫程式", "除錯", "debug", "python", "javascript", "lua", "code", "script")
    detailed_cues = ("詳細", "完整", "逐步", "分析", "比較", "解釋", "範例", "explain", "detailed", "step by step", "analyze")
    if any(cue.casefold() in text for cue in technical_cues):
        return 0.25
    if any(cue.casefold() in text for cue in detailed_cues):
        return 0.35
    return 0.55


def _append_bounded_history(
    history: list[dict[str, str]], role: str, content: str, max_chars: int
) -> None:
    """Keep the newest message and evict oldest turns until history fits the budget."""
    history.append({"role": role, "content": content})
    while len(history) > 1 and (
        len(history) > MAX_HISTORY_MESSAGES or _history_char_count(history) > max_chars
    ):
        history.pop(0)


def _load_generator():
    """Load the configured local or external assistant engine."""
    provider = os.environ.get("KAPTIA_PROVIDER", "local").strip().lower()
    if provider in {"api", "openai-compatible", "openai_compatible"}:
        from kaptia_api_runtime import build_api_generator
        print("[Kaptia] 使用外接 OpenAI-compatible API；金鑰只從環境變數讀取。")
        return build_api_generator()
    if provider != "local":
        raise ValueError("KAPTIA_PROVIDER 僅支援 local 或 openai-compatible。")
    os.environ.pop("KAPTIA_SCRATCH_CHECKPOINT", None)
    from kaptia_qwen_runtime import load_language_engine, build_generator
    print("[Kaptia] 正在載入 Qwen 本機語言引擎；首次載入會下載模型權重。")
    tokenizer, model = load_language_engine()
    return build_generator(tokenizer, model)

def main() -> int:
    max_history_chars = _env_limit("KAPTIA_MAX_HISTORY_CHARS", DEFAULT_HISTORY_CHARS, 4_000, 40_000)
    max_input_chars = min(
        _env_limit("KAPTIA_MAX_INPUT_CHARS", DEFAULT_INPUT_CHARS, 1_000, 40_000),
        max_history_chars,
    )
    try:
        generate = _load_generator()
    except Exception as exc:
        print(f"[錯誤] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    subagents_enabled = os.environ.get("KAPTIA_ENABLE_SUBAGENTS", "0").strip() == "1"
    try:
        mode = normalize_mode(os.environ.get("KAPTIA_MODE", "fast"))
    except ValueError:
        mode = "fast"
    print("[Kaptia] 已就緒。預設快速模式。輸入 /mode fast 或 /mode deep 切換；/exit 離開；/memory 查看本機記憶；/forget 清除本機對話記憶。")
    print(
        f"[Kaptia] 輸入上限 {max_input_chars:,} 字元；"
        f"歷史預算 {max_history_chars:,} 字元；"
        f"子代理 {'已啟用' if subagents_enabled else '預設停用（可用 KAPTIA_ENABLE_SUBAGENTS=1 開啟）'}。"
    )
    try:
        history: list[dict[str, str]] = load_recent_messages(
            max_messages=MAX_HISTORY_MESSAGES, max_chars=max_history_chars
        )
        print(f"[Kaptia] 已載入 {len(history)} 則本機歷史訊息。")
    except Exception as exc:
        print(f"[記憶載入失敗] {type(exc).__name__}: {exc}", file=sys.stderr)
        print("[Kaptia] 為避免覆寫或忽略損壞的記憶，本次停止啟動。", file=sys.stderr)
        return 1
    while True:
        try:
            user_text = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[Kaptia] 已結束。")
            break
        command = user_text.lower()
        if command in {"/exit", "/quit", "exit", "quit"}:
            print("[Kaptia] 已結束。")
            break
        if command in {"/mode", "/mode fast", "/mode deep"}:
            requested = command.split(maxsplit=1)[1] if " " in command else ""
            if not requested:
                label = "快速 Fast" if mode == "fast" else "深度思考 Deep Thinking"
                print(f"[Kaptia] 目前模式：{label}。使用 /mode fast 或 /mode deep 切換。")
                continue
            try:
                mode = normalize_mode(requested)
                label = "快速 Fast" if mode == "fast" else "深度思考 Deep Thinking"
                print(f"[Kaptia] 已切換至：{label}。")
            except ValueError as exc:
                print(f"[Kaptia] {exc}")
            continue
        if command == "/memory":
            try:
                status = memory_status()
                print(f"[Kaptia 本機記憶] {status['exchanges']} 段對話、{status['messages']} 則訊息")
                print(f"[儲存位置] {status['path']}")
                print("[隱私] 記憶儲存在此 Windows 使用者的本機資料夾；此模組不會自行上傳。")
            except Exception as exc:
                print(f"[記憶讀取失敗] {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if command == "/forget":
            confirm = input("這會刪除此使用者的 Kaptia 本機對話記憶。輸入 DELETE 確認：").strip()
            if confirm == "DELETE":
                try:
                    clear_memory()
                    history.clear()
                    print("[Kaptia] 本機對話記憶已清除。")
                except Exception as exc:
                    print(f"[記憶清除失敗] {type(exc).__name__}: {exc}", file=sys.stderr)
            else:
                print("[Kaptia] 已取消，沒有清除記憶。")
            continue
        if not user_text:
            continue
        if len(user_text) > max_input_chars:
            print(
                f"[Kaptia] 這次輸入有 {len(user_text):,} 字元，"
                f"超過目前上限 {max_input_chars:,}。已拒絕此次輸入，未送入模型。"
            )
            continue

        _append_bounded_history(history, "user", user_text, max_history_chars)
        try:
            if mode == "deep":
                answer, deep_meta = run_deep_workflow(generate, user_text, max_new_tokens=DETAILED_RESPONSE_TOKENS)
                print(f"[Kaptia] 深度流程完成：需求分析、基礎版本、測試拆分、細化；測試尚待外部執行 {deep_meta['pending']} 項。")
            elif subagents_enabled and len(user_text) >= 120:
                # The current user turn is already appended; pass only prior turns as context.
                answer, agent_meta = run_agent_workflow(
                    generate, user_text, max_new_tokens=384, history=history[:-1]
                )
                print(f"[Kaptia] 已拆分為 {len(agent_meta)} 個子任務。")
            else:
                fast_history = list(history)
                fast_history[-1] = {"role": "user", "content": fast_prompt(user_text)}
                answer = generate(
                    fast_history,
                    max_new_tokens=_response_token_budget(user_text),
                    temperature=_response_temperature(user_text),
                )
            if not isinstance(answer, str) or not answer.strip():
                answer = "模型未產生有效文字；請檢查模型設定、記憶體與推論日誌。"
            print("\nKaptia：\n" + answer)
            _append_bounded_history(history, "assistant", answer, max_history_chars)
            try:
                append_exchange(user_text, answer)
            except Exception as exc:
                print(f"[記憶儲存失敗] {type(exc).__name__}: {exc}", file=sys.stderr)
                print("[Kaptia] 本次回答已產生，但未確認成功寫入長期記憶。", file=sys.stderr)
        except Exception as exc:
            print(f"[對話失敗] {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
