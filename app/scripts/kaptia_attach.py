"""User-consented Windows desktop application attachment for Kaptia.

Attach discovers visible top-level windows and grants a short-lived, per-window
UI Automation session only after an explicit user action. It does not inject code,
read process memory, launch applications, or expose an arbitrary shell.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import threading
import time
import uuid
from typing import Any

MAX_WINDOWS = 200
MAX_CONTROLS = 250
SESSION_TTL_SECONDS = 60 * 60
ALLOWED_CLICK_TYPES = {"Button", "TabItem", "MenuItem", "CheckBox", "RadioButton", "Hyperlink"}
ALLOWED_TEXT_TYPES = {"Edit", "Document"}
_SESSIONS: dict[str, dict[str, Any]] = {}
_PENDING: dict[str, dict[str, Any]] = {}
_OCR_ENGINE: Any = None
_OCR_LOCK = threading.Lock()
_LOCK = threading.RLock()


def _windows_only() -> None:
    if os.name != "nt":
        raise OSError("Attach 目前只支援 Windows 桌面工作階段。")


def _process_image(pid: int) -> str:
    """Return an executable path when Windows grants query access."""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def list_running_apps() -> dict[str, Any]:
    """List visible top-level application windows; multiple windows per app are retained."""
    try:
        _windows_only()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        rows: list[dict[str, Any]] = []

        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            title = ctypes.create_unicode_buffer(min(length + 1, 2048))
            user32.GetWindowTextW(hwnd, title, len(title))
            if not title.value.strip():
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return True
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, len(class_name))
            rows.append({
                "window_id": int(hwnd),
                "pid": int(pid.value),
                "process": os.path.basename(_process_image(int(pid.value))) or "unknown",
                "title": title.value[:500],
                "class_name": class_name.value[:255],
            })
            return len(rows) < MAX_WINDOWS

        user32.EnumWindows(callback_type(callback), 0)
        rows.sort(key=lambda item: (item["process"].casefold(), item["title"].casefold()))
        return {"ok": True, "windows": rows, "count": len(rows),
                "note": "只列出可見頂層視窗；背景程序及無視窗程序不會出現在清單。"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "windows": []}


def _validate_window(window_id: int, expected_pid: int | None = None) -> int:
    _windows_only()
    if isinstance(window_id, bool) or not isinstance(window_id, int) or window_id <= 0:
        raise ValueError("window_id 無效")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    if not user32.IsWindow(wintypes.HWND(window_id)) or not user32.IsWindowVisible(wintypes.HWND(window_id)):
        raise RuntimeError("目標視窗已關閉或不再可見；請重新掃描")
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(window_id), ctypes.byref(pid))
    if not pid.value or (expected_pid is not None and pid.value != expected_pid):
        raise RuntimeError("目標視窗程序已改變；拒絕沿用舊附加工作階段")
    return int(pid.value)


def attach_window(window_id: int, user_approved: bool = False) -> dict[str, Any]:
    """Create an ephemeral session for one exact window after explicit user consent."""
    if user_approved is not True:
        return {"ok": False, "error": "附加操作必須由使用者在介面明確確認。"}
    try:
        pid = _validate_window(window_id)
        session_id = uuid.uuid4().hex
        with _LOCK:
            _SESSIONS[session_id] = {
                "window_id": int(window_id), "pid": pid,
                "created": time.monotonic(), "last_used": time.monotonic(),
            }
        return {"ok": True, "session_id": session_id, "window_id": int(window_id),
                "pid": pid, "capabilities": ["inspect", "click_ui_element", "type_into_text_field"],
                "restrictions": [
                    "僅限已附加的單一視窗",
                    "不讀取程序記憶體、不注入程式碼、不執行 shell",
                    "每次點擊或輸入都必須再次取得使用者確認",
                ]}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _get_session(session_id: str) -> dict[str, Any]:
    if not isinstance(session_id, str) or len(session_id) != 32:
        raise ValueError("session_id 無效")
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if not session:
            raise PermissionError("Attach 工作階段不存在或已解除")
        if time.monotonic() - session["created"] > SESSION_TTL_SECONDS:
            _SESSIONS.pop(session_id, None)
            raise PermissionError("Attach 工作階段已逾時，請重新附加")
        _validate_window(session["window_id"], session["pid"])
        session["last_used"] = time.monotonic()
        return dict(session)


def inspect_attached_window(session_id: str) -> dict[str, Any]:
    """Inspect a bounded UI Automation tree without reading arbitrary app memory."""
    try:
        session = _get_session(session_id)
        from pywinauto import Desktop
        window = Desktop(backend="uia").window(handle=session["window_id"])
        controls = []
        for element in window.descendants()[:MAX_CONTROLS]:
            try:
                info = element.element_info
                controls.append({
                    "name": str(info.name or "")[:300],
                    "control_type": str(info.control_type or "")[:80],
                    "automation_id": str(info.automation_id or "")[:160],
                    "enabled": bool(info.enabled),
                    "visible": bool(info.visible),
                })
            except Exception:
                continue
        return {"ok": True, "window_id": session["window_id"],
                "controls": controls, "truncated": len(controls) >= MAX_CONTROLS}
    except ImportError:
        return {"ok": False, "error": "缺少可選依賴 pywinauto；請安裝 Attach UI Automation 元件。"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _find_unique_control(window: Any, selector: dict[str, str], allowed_types: set[str]):
    if not isinstance(selector, dict) or not selector:
        raise ValueError("必須提供 UI Automation selector")
    allowed_keys = {"name", "automation_id", "control_type"}
    if set(selector) - allowed_keys or any(not isinstance(v, str) or not v.strip() for v in selector.values()):
        raise ValueError("selector 只允許非空的 name、automation_id、control_type")
    if "control_type" in selector and selector["control_type"] not in allowed_types:
        raise PermissionError("此類 UI 控制項不允許執行該操作")
    matches = []
    for element in window.descendants():
        try:
            info = element.element_info
            if not info.enabled or not info.visible:
                continue
            if any(str(getattr(info, key, "") or "") != value for key, value in selector.items()):
                continue
            if info.control_type not in allowed_types:
                continue
            matches.append(element)
            if len(matches) > 1:
                break
        except Exception:
            continue
    if len(matches) != 1:
        raise ValueError("selector 必須精確匹配一個可見且啟用的控制項；目前匹配數：" + str(len(matches)))
    return matches[0]


def click_ui_element(session_id: str, selector: dict[str, str], user_approved: bool = False) -> dict[str, Any]:
    """Click one uniquely selected safe UI control; every action needs fresh approval."""
    if user_approved is not True:
        return {"ok": False, "error": "點擊操作必須由使用者逐次確認。"}
    try:
        session = _get_session(session_id)
        from pywinauto import Desktop
        window = Desktop(backend="uia").window(handle=session["window_id"])
        control = _find_unique_control(window, selector, ALLOWED_CLICK_TYPES)
        control.click_input()
        return {"ok": True, "action": "click", "selector": selector}
    except ImportError:
        return {"ok": False, "error": "缺少可選依賴 pywinauto。"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def type_into_text_field(session_id: str, selector: dict[str, str], text: str,
                         user_approved: bool = False) -> dict[str, Any]:
    """Enter bounded text into one uniquely selected edit/document control."""
    if user_approved is not True:
        return {"ok": False, "error": "輸入文字必須由使用者逐次確認。"}
    if not isinstance(text, str) or len(text) > 4000:
        return {"ok": False, "error": "輸入文字必須是 0–4000 字元。"}
    try:
        session = _get_session(session_id)
        from pywinauto import Desktop
        window = Desktop(backend="uia").window(handle=session["window_id"])
        control = _find_unique_control(window, selector, ALLOWED_TEXT_TYPES)
        control.set_edit_text(text)
        return {"ok": True, "action": "type_text", "characters": len(text)}
    except ImportError:
        return {"ok": False, "error": "缺少可選依賴 pywinauto。"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _window_rect(window_id: int) -> tuple[int, int, int, int]:
    _windows_only()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    rect = wintypes.RECT()
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    hwnd = wintypes.HWND(window_id)
    if user32.IsIconic(hwnd):
        raise RuntimeError("目標視窗已最小化；請先還原視窗")
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OSError(ctypes.get_last_error(), "無法取得視窗範圍")
    bounds = (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    if bounds[2] - bounds[0] < 80 or bounds[3] - bounds[1] < 60:
        raise RuntimeError("視窗尺寸不足，無法進行畫面辨識")
    return bounds


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        with _OCR_LOCK:
            if _OCR_ENGINE is None:
                from rapidocr_onnxruntime import RapidOCR
                _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def capture_window_ocr(session_id: str) -> dict[str, Any]:
    """Capture only the attached window and OCR it; no screenshot is persisted."""
    try:
        session = _get_session(session_id)
        bounds = _window_rect(session["window_id"])
        from PIL import ImageGrab
        image = ImageGrab.grab(bbox=bounds, all_screens=True)
        image = image.convert("RGB")
        original_width, original_height = image.size
        if image.width * image.height > 16_000_000:
            image.thumbnail((3200, 3200))
        scale_x = (bounds[2] - bounds[0]) / max(1, image.width)
        scale_y = (bounds[3] - bounds[1]) / max(1, image.height)
        try:
            engine = _get_ocr_engine()
        except ImportError:
            return {"ok": False, "error": "缺少 Vision OCR 元件；請安裝 requirements-attach-vision.txt。"}
        import numpy as np
        output, _elapsed = engine(np.asarray(image))
        elements = []
        for row in (output or [])[:MAX_CONTROLS]:
            try:
                polygon, text, score = row
                xs = [float(point[0]) for point in polygon]
                ys = [float(point[1]) for point in polygon]
                left, top, right, bottom = min(xs) * scale_x, min(ys) * scale_y, max(xs) * scale_x, max(ys) * scale_y
                elements.append({
                    "text": str(text)[:300],
                    "confidence": round(float(score), 3),
                    "bounds": {
                        "left": round(left), "top": round(top),
                        "right": round(right), "bottom": round(bottom),
                    },
                    "center": {"x": round((left + right) / 2), "y": round((top + bottom) / 2)},
                })
            except (TypeError, ValueError, IndexError):
                continue
        return {
            "ok": True, "window_id": session["window_id"],
            "image_size": {"width": original_width, "height": original_height},
            "screen_rect": {"left": bounds[0], "top": bounds[1], "right": bounds[2], "bottom": bounds[3]},
            "elements": elements, "count": len(elements),
            "note": "OCR 文字與座標是辨識結果，可能有誤；操作前必須由使用者批准。",
        }
    except ImportError:
        return {"ok": False, "error": "缺少 Pillow；請安裝 Attach Vision 元件。"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _focus_attached_window(session: dict[str, Any]) -> tuple[int, int, int, int]:
    bounds = _window_rect(session["window_id"])
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = wintypes.HWND(session["window_id"])
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    if int(user32.GetForegroundWindow() or 0) != session["window_id"]:
        raise PermissionError("Windows 未允許將目標視窗設為前景；拒絕執行座標操作")
    _validate_window(session["window_id"], session["pid"])
    return bounds


def propose_vision_action(session_id: str, action: str, x: int, y: int,
                          text: str = "") -> dict[str, Any]:
    """Queue a bounded screen-coordinate action. Nothing executes until UI approval."""
    if action not in {"vision_click", "vision_type_text"}:
        return {"ok": False, "error": "不支援的 Vision 操作類型"}
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (x, y)):
        return {"ok": False, "error": "座標必須是整數"}
    if action == "vision_type_text" and (
        not isinstance(text, str) or not text or len(text) > 1000 or not text.isascii()
    ):
        return {"ok": False, "error": "Vision 文字輸入目前限 1–1000 個 ASCII 字元；中文請使用 UI Automation 文字欄位"}
    try:
        session = _get_session(session_id)
        bounds = _window_rect(session["window_id"])
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError("座標超出附加視窗範圍")
        pending_id = uuid.uuid4().hex
        with _LOCK:
            if len(_PENDING) >= 20:
                raise ValueError("待批准的 Attach 操作已達 20 筆上限")
            _PENDING[pending_id] = {
                "session_id": session_id, "action": action, "selector": {},
                "point": {"x": x, "y": y},
                "text": text if action == "vision_type_text" else "",
                "created": time.monotonic(),
            }
        return {
            "ok": True, "pending_id": pending_id, "action": action,
            "point": {"x": x, "y": y}, "requires_user_approval": True,
            "note": "座標操作尚未執行；必須由使用者在 Attach 介面批准。",
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _execute_vision_action(item: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(item["session_id"])
    bounds = _focus_attached_window(session)
    point = item["point"]
    if not (0 <= point["x"] < bounds[2] - bounds[0] and
            0 <= point["y"] < bounds[3] - bounds[1]):
        return {"ok": False, "error": "視窗尺寸已變更，原座標不再有效；請重新辨識畫面"}
    screen_x, screen_y = bounds[0] + point["x"], bounds[1] + point["y"]
    try:
        import pyautogui
    except ImportError:
        return {"ok": False, "error": "缺少 pyautogui；請安裝 Attach Vision 元件。"}
    pyautogui.FAILSAFE = True
    if item["action"] == "vision_click":
        pyautogui.click(screen_x, screen_y)
        return {"ok": True, "action": "vision_click", "point": point}
    pyautogui.click(screen_x, screen_y)
    pyautogui.write(item["text"], interval=0.01)
    return {"ok": True, "action": "vision_type_text", "characters": len(item["text"])}


def propose_ui_action(session_id: str, action: str, selector: dict[str, str],
                       text: str = "") -> dict[str, Any]:
    """Queue an AI-proposed UI action for explicit user approval; never executes it."""
    if action not in {"click", "type_text"}:
        return {"ok": False, "error": "不支援的 Attach 操作類型"}
    if action == "type_text" and (not isinstance(text, str) or len(text) > 4000):
        return {"ok": False, "error": "輸入文字必須是 0–4000 字元"}
    try:
        session = _get_session(session_id)
        from pywinauto import Desktop
        window = Desktop(backend="uia").window(handle=session["window_id"])
        allowed = ALLOWED_CLICK_TYPES if action == "click" else ALLOWED_TEXT_TYPES
        _find_unique_control(window, selector, allowed)
        pending_id = uuid.uuid4().hex
        with _LOCK:
            if len(_PENDING) >= 20:
                raise ValueError("待批准的 Attach 操作已達 20 筆上限")
            _PENDING[pending_id] = {
                "session_id": session_id, "action": action, "selector": dict(selector),
                "text": text if action == "type_text" else "",
                "created": time.monotonic(),
            }
        return {"ok": True, "pending_id": pending_id, "action": action,
                "selector": selector, "requires_user_approval": True,
                "note": "操作尚未執行；必須由使用者在 Attach 介面批准。"}
    except ImportError:
        return {"ok": False, "error": "缺少可選依賴 pywinauto。"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def list_pending_actions() -> dict[str, Any]:
    now = time.monotonic()
    with _LOCK:
        expired = [key for key, value in _PENDING.items() if now - value["created"] > 300]
        for key in expired:
            _PENDING.pop(key, None)
        rows = [{
            "pending_id": key, "session_id": value["session_id"],
            "action": value["action"], "selector": value["selector"],
            "point": value.get("point"),
            "text_preview": value["text"][:160], "age_seconds": int(now - value["created"]),
        } for key, value in _PENDING.items()]
    return {"ok": True, "pending": rows, "count": len(rows)}


def approve_pending_action(pending_id: str, user_approved: bool = False) -> dict[str, Any]:
    if user_approved is not True:
        return {"ok": False, "error": "必須由使用者在 Attach 介面明確批准。"}
    with _LOCK:
        item = _PENDING.pop(str(pending_id), None)
    if not item:
        return {"ok": False, "error": "待批准操作不存在或已逾時。"}
    if time.monotonic() - item["created"] > 300:
        return {"ok": False, "error": "待批准操作已逾時，請讓 AI 重新提出。"}
    if item["action"] == "click":
        return click_ui_element(item["session_id"], item["selector"], user_approved=True)
    if item["action"] == "type_text":
        return type_into_text_field(item["session_id"], item["selector"], item["text"], user_approved=True)
    return _execute_vision_action(item)


def reject_pending_action(pending_id: str) -> dict[str, Any]:
    with _LOCK:
        existed = _PENDING.pop(str(pending_id), None) is not None
    return {"ok": existed, "rejected": existed}


def list_attached_sessions() -> dict[str, Any]:
    """Return metadata for active sessions; no application content is read."""
    rows = []
    with _LOCK:
        for session_id, session in list(_SESSIONS.items()):
            try:
                _validate_window(session["window_id"], session["pid"])
            except Exception:
                _SESSIONS.pop(session_id, None)
                continue
            rows.append({
                "session_id": session_id,
                "window_id": session["window_id"],
                "pid": session["pid"],
                "age_seconds": int(time.monotonic() - session["created"]),
            })
    return {"ok": True, "sessions": rows, "count": len(rows)}


def detach_window(session_id: str) -> dict[str, Any]:
    with _LOCK:
        existed = _SESSIONS.pop(str(session_id), None) is not None
    return {"ok": existed, "detached": existed}


def detach_all() -> dict[str, Any]:
    with _LOCK:
        count = len(_SESSIONS)
        _SESSIONS.clear()
        _PENDING.clear()
    return {"ok": True, "detached_count": count}
