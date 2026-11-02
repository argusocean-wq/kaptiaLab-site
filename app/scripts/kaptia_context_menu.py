"""Per-user Windows Explorer context menu for asking Kaptia about selected files/folders."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

APP_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Kaptia"
CONFIG_PATH = APP_ROOT / "context_menu.json"
REG_ROOT = r"Software\Classes"
MENU_KEY = "問問 Kaptia"
TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".ini", ".csv", ".html", ".css", ".xml", ".log", ".bat", ".ps1", ".lua", ".c", ".h", ".cpp", ".cs", ".java", ".rs", ".go"}
MAX_FILE_BYTES = 48_000
MAX_TOTAL_CHARS = 12_000
HOST = "http://127.0.0.1:43871"

def load_config():
    config = {"menu_label": "問問 Kaptia", "default_assistant": "Kaptia"}
    try:
        stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            label = stored.get("menu_label")
            assistant = stored.get("default_assistant")
            if isinstance(label, str) and label.strip():
                config["menu_label"] = label.strip()[:64]
            if isinstance(assistant, str) and assistant.strip():
                config["default_assistant"] = assistant.strip()[:80]
    except (OSError, ValueError):
        pass
    return config

def save_config(label=None, assistant=None):
    current = load_config()
    if label is not None:
        if not label.strip() or len(label.strip()) > 64:
            raise ValueError("選單名稱需為 1–64 個字元。")
        current["menu_label"] = label.strip()
    if assistant is not None:
        if not assistant.strip() or len(assistant.strip()) > 80:
            raise ValueError("預設助手名稱需為 1–80 個字元。")
        current["default_assistant"] = assistant.strip()
    APP_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current

def register_menu():
    if os.name != "nt":
        raise RuntimeError("Windows Explorer 右鍵選單僅支援 Windows。")
    import winreg
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    helper = Path(__file__).resolve()
    command = '"{}" "{}" --path "%1"'.format(pythonw, helper)
    label = load_config()["menu_label"]
    for class_key in (r"Software\Classes\*\shell\KaptiaAsk", r"Software\Classes\Directory\shell\KaptiaAsk"):
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, class_key) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, label)
            winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, str(APP_ROOT / "Kaptia-Setup.exe"))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, class_key + r"\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    return True

def unregister_menu():
    if os.name != "nt":
        return
    import winreg
    for key_path in (r"Software\Classes\*\shell\KaptiaAsk", r"Software\Classes\Directory\shell\KaptiaAsk"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path + r"\command")
        except OSError:
            pass
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except OSError:
            pass

def read_selected_paths(paths):
    pieces = []
    total = 0
    for raw in paths[:20]:
        path = Path(raw)
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())[:10]
        for candidate in candidates:
            if candidate.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                if candidate.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            room = MAX_TOTAL_CHARS - total
            if room <= 0:
                break
            snippet = data[:room]
            pieces.append(f"\n\n=== 檔案：{candidate} ===\n{snippet}")
            total += len(snippet)
        if total >= MAX_TOTAL_CHARS:
            break
    if not pieces:
        raise ValueError("選取項目中沒有可讀取的支援文字檔。為保護隱私，Kaptia 不會讀取二進位檔或超大檔案。")
    return "".join(pieces)

def ask_kaptia(question, selection, file_name):
    payload = json.dumps({"question": question, "selection": selection, "fileName": file_name}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(HOST + "/ask", data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=180) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("answer"):
        raise RuntimeError(result.get("message", "Kaptia 沒有產生回答。"))
    return result

def run_for_paths(paths):
    import tkinter as tk
    from tkinter import messagebox
    config = load_config()
    try:
        selection = read_selected_paths(paths)
        root = APP_ROOT
        python = root / ".venv" / "Scripts" / "python.exe"
        app = root / "app" / "scripts" / "kaptia_context_server.py"
        checkpoint = root / "model-data" / "kaptia-scratch-pretrain" / "best_checkpoint.pt"
        try:
            urllib.request.urlopen(HOST + "/health", timeout=1).read()
        except Exception:
            if not (python.is_file() and app.is_file() and checkpoint.is_file()):
                raise RuntimeError("找不到已安裝的 Kaptia 執行環境或模型 checkpoint。請先完成安裝與起步訓練。")
            subprocess.Popen([str(python), str(app)], cwd=str(root / "app"),
                env={**os.environ, "KAPTIA_SCRATCH_CHECKPOINT": str(checkpoint)},
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    urllib.request.urlopen(HOST + "/health", timeout=1).read()
                    break
                except Exception:
                    time.sleep(.4)
            else:
                raise RuntimeError("Kaptia 本機模型服務未能啟動。")
        result = ask_kaptia(
            f"請以「{config['default_assistant']}」的角色，用繁體中文分析以下選取檔案／資料夾中的文字內容，指出用途、重點與可能問題。",
            selection, Path(paths[0]).name)
        root_ui = tk.Tk()
        root_ui.withdraw()
        messagebox.showinfo(config["menu_label"] + " · 回答", result["answer"][:8000] + "\n\n[實驗性模型輸出，請自行核對]")
        root_ui.destroy()
    except Exception as exc:
        root_ui = tk.Tk()
        root_ui.withdraw()
        messagebox.showerror("問問 Kaptia 失敗", str(exc))
        root_ui.destroy()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-menu", action="store_true")
    parser.add_argument("--uninstall-menu", action="store_true")
    parser.add_argument("--set-label")
    parser.add_argument("--set-assistant")
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args()
    if args.set_label is not None or args.set_assistant is not None:
        save_config(args.set_label, args.set_assistant)
    if args.install_menu:
        register_menu()
    elif args.uninstall_menu:
        unregister_menu()
    elif args.path:
        run_for_paths(args.path)
    elif args.set_label is not None or args.set_assistant is not None:
        print(json.dumps(load_config(), ensure_ascii=False, indent=2))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
