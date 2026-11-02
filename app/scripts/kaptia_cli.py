"""Unified Kaptia command-line interface.

Run with: python -m scripts.kaptia_cli [chat|attach|doctor]
The CLI exposes only predefined operations; it is not a system shell.
"""
from __future__ import annotations
import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

VERSION = "0.1.0"

def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))

def _load_attach():
    try:
        from kaptia_attach import (list_running_apps, attach_window, inspect_attached_window,
            capture_window_ocr, propose_ui_action, propose_vision_action, list_pending_actions,
            approve_pending_action, reject_pending_action, detach_window, detach_all)
    except ImportError:
        from scripts.kaptia_attach import (list_running_apps, attach_window, inspect_attached_window,
            capture_window_ocr, propose_ui_action, propose_vision_action, list_pending_actions,
            approve_pending_action, reject_pending_action, detach_window, detach_all)
    return {"list": list_running_apps, "connect": attach_window, "inspect": inspect_attached_window,
        "ocr": capture_window_ocr, "propose_ui": propose_ui_action, "propose_vision": propose_vision_action,
        "pending": list_pending_actions, "approve": approve_pending_action, "reject": reject_pending_action,
        "detach": detach_window, "detach_all": detach_all}

def _attach_repl() -> int:
    if os.name != "nt":
        print("Attach CLI 目前只支援 Windows。", file=sys.stderr)
        return 2
    api = _load_attach()
    print("Kaptia Attach CLI")
    print("命令：list | connect <window_id> | inspect <session_id> | ocr <session_id>")
    print("click <session_id> <selector-json> | type <session_id> <selector-json> <text>")
    print("vision-click <session_id> <x> <y> | vision-type <session_id> <x,y> <ASCII-text>")
    print("pending | approve <pending_id> | reject <pending_id> | detach <session_id> | exit")
    try:
        while True:
            try:
                line = input("kaptia-attach> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in {"exit", "quit"}:
                break
            parts = line.split(maxsplit=3)
            command = parts[0].lower()
            try:
                if command == "list" and len(parts) == 1:
                    _json(api["list"]())
                elif command == "connect" and len(parts) == 2:
                    window_id = int(parts[1], 10)
                    confirm = input(f"確認附加視窗 HWND={window_id}？輸入 ATTACH {window_id}：").strip()
                    _json(api["connect"](window_id, user_approved=True) if confirm == f"ATTACH {window_id}" else {"ok": False, "cancelled": True})
                elif command in {"inspect", "ocr", "detach"} and len(parts) == 2:
                    _json(api[command](parts[1]))
                elif command == "click" and len(parts) == 3:
                    selector = json.loads(parts[2])
                    if not isinstance(selector, dict): raise ValueError("selector 必須是 JSON object")
                    _json(api["propose_ui"](parts[1], "click", selector))
                elif command == "type" and len(parts) == 4:
                    selector = json.loads(parts[2])
                    if not isinstance(selector, dict): raise ValueError("selector 必須是 JSON object")
                    _json(api["propose_ui"](parts[1], "type_text", selector, parts[3]))
                elif command == "vision-click" and len(parts) == 4:
                    _json(api["propose_vision"](parts[1], "vision_click", int(parts[2]), int(parts[3])))
                elif command == "vision-type" and len(parts) == 4:
                    coords = parts[2].split(",", 1)
                    if len(coords) != 2: raise ValueError("座標格式必須是 x,y")
                    _json(api["propose_vision"](parts[1], "vision_type_text", int(coords[0]), int(coords[1]), parts[3]))
                elif command == "pending" and len(parts) == 1:
                    _json(api["pending"]())
                elif command == "approve" and len(parts) == 2:
                    pending_id = parts[1]
                    pending = api["pending"]()
                    item = next((x for x in pending.get("pending", []) if x.get("pending_id") == pending_id), None)
                    if item is None:
                        print("找不到待批准操作，或操作已逾時。")
                        continue
                    _json({"approval_target": item})
                    confirm = input(f"確認執行此操作？輸入 APPROVE {pending_id}：").strip()
                    if confirm == f"APPROVE {pending_id}":
                        _json(api["approve"](pending_id, user_approved=True))
                    else:
                        print("已取消；待批准操作仍保留。")
                elif command == "reject" and len(parts) == 2:
                    _json(api["reject"](parts[1]))
                else:
                    print("命令格式錯誤。請輸入 help 查看可用命令，或 exit 離開。")
            except (ValueError, json.JSONDecodeError) as exc:
                print(f"輸入錯誤：{exc}", file=sys.stderr)
            except Exception as exc:
                print(f"操作失敗：{type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        _json(api["detach_all"]())
    return 0

def _doctor() -> int:
    checks = {"python": sys.version.split()[0], "platform": platform.platform(),
              "provider": os.environ.get("KAPTIA_PROVIDER", "local"), "cwd": os.getcwd()}
    try:
        import importlib.util
        checks["webview_available"] = importlib.util.find_spec("webview") is not None
        checks["torch_available"] = importlib.util.find_spec("torch") is not None
        checks["attach_available"] = importlib.util.find_spec("pywinauto") is not None
        checks["vision_available"] = importlib.util.find_spec("rapidocr_onnxruntime") is not None
    except (ImportError, ValueError) as exc:
        checks["dependency_probe_error"] = str(exc)
    _json(checks)
    return 0


def _cloud_command(args) -> int:
    from kaptia_cloud_compute import CloudComputeClient, list_providers
    if args.cloud_action == "providers":
        _json(list_providers())
        return 0
    client = CloudComputeClient.from_environment()
    if args.cloud_action == "test":
        _json({"health": client.health(), "capabilities": client.capabilities()})
        return 0
    if args.cloud_action == "submit":
        source_path = Path(args.file).expanduser().resolve()
        if not source_path.is_file() or source_path.stat().st_size > 2_000_000:
            raise ValueError("任務檔案不存在或超過 2 MB")
        source = source_path.read_text(encoding="utf-8")
        print(f"即將傳送 {source_path.name} 至使用者設定的雲端伺服器。")
        print("請確認檔案不含密碼、API Token、私人金鑰或不應外傳的資料。")
        if input("輸入 SUBMIT 才會傳送：").strip() != "SUBMIT":
            print("已取消。")
            return 1
        _json(client.submit(args.task_type, source, args.timeout))
        return 0
    if args.cloud_action == "job":
        _json(client.get_job(args.job_id))
        return 0
    raise ValueError("未知的 Cloud Compute 操作")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kaptia",
        description="KaptiaLab CLI — terminal chat, diagnostics, and consent-based desktop Attach.")
    parser.add_argument("--version", action="version", version=f"Kaptia CLI {VERSION}")
    sub = parser.add_subparsers(dest="command")
    chat = sub.add_parser("chat", help="Start interactive Kaptia terminal chat.")
    chat.add_argument("--mode", choices=("fast", "deep"), default=None)
    chat.add_argument("--provider", choices=("local", "openai-compatible"), default=None)
    sub.add_parser("attach", help="Open the interactive, consent-based desktop Attach console.")
    sub.add_parser("doctor", help="Print runtime and optional dependency diagnostics.")
    cloud = sub.add_parser("cloud", help="Connect to a user-owned Cloud Compute worker (not an LLM API).")
    cloud_sub = cloud.add_subparsers(dest="cloud_action", required=True)
    cloud_sub.add_parser("providers", help="List supported worker hosting providers.")
    cloud_sub.add_parser("test", help="Test the configured HTTPS worker connection.")
    submit = cloud_sub.add_parser("submit", help="Submit a local Python or Blender script after confirmation.")
    submit.add_argument("--type", dest="task_type", choices=("python_script", "blender_background"), required=True)
    submit.add_argument("--file", required=True)
    submit.add_argument("--timeout", type=int, default=900)
    job = cloud_sub.add_parser("job", help="Read a remote job status.")
    job.add_argument("job_id")
    return parser

def _run_chat() -> int:
    try:
        from chat import main as chat_main
    except ImportError:
        from scripts.chat import main as chat_main
    return int(chat_main())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = args.command or "chat"
    if command == "chat":
        if args.command == "chat":
            if args.mode: os.environ["KAPTIA_MODE"] = args.mode
            if args.provider: os.environ["KAPTIA_PROVIDER"] = args.provider
        return _run_chat()
    if command == "attach": return _attach_repl()
    if command == "doctor": return _doctor()
    if command == "cloud": return _cloud_command(args)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
