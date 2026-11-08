"""Apply the KaptiaLab icon to the native Windows PyWebView window."""
from __future__ import annotations

import os
from pathlib import Path

_ICON_HANDLES = []


def apply_windows_window_icon(window, icon_path: str | Path) -> bool:
    """Set process AppUserModelID and native titlebar/taskbar icons on Windows."""
    if os.name != "nt":
        return False
    path = Path(icon_path)
    if not path.is_file():
        return False

    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    set_app_id = shell32.SetCurrentProcessExplicitAppUserModelID
    set_app_id.argtypes = [wintypes.LPCWSTR]
    set_app_id.restype = ctypes.c_long
    if set_app_id("KaptiaLab.Desktop") < 0:
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    find_window = user32.FindWindowW
    find_window.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    find_window.restype = wintypes.HWND
    load_image = user32.LoadImageW
    load_image.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                           ctypes.c_int, ctypes.c_int, wintypes.UINT]
    load_image.restype = wintypes.HANDLE
    send_message = user32.SendMessageW
    send_message.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    send_message.restype = ctypes.c_ssize_t

    title = str(getattr(window, "title", "Kaptia · Personal Assistant"))
    hwnd = find_window(None, title)
    if not hwnd:
        return False

    # WM_SETICON: ICON_SMALL=0, ICON_BIG=1. Keep handles alive for the process.
    image_icon, load_from_file = 1, 0x0010
    handles = []
    for size in (16, 32, 48):
        handle = load_image(None, str(path), image_icon, size, size, load_from_file)
        if handle:
            handles.append(handle)
    if not handles:
        return False

    send_message(hwnd, 0x0080, 0, handles[0])
    send_message(hwnd, 0x0080, 1, handles[-1])
    _ICON_HANDLES.extend(handles)
    return True
