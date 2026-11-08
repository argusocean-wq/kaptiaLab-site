"""Regression tests for the native Kaptia Windows icon helper."""
from __future__ import annotations

from pathlib import Path

from scripts.kaptia_windows_icon import apply_windows_window_icon


def test_missing_icon_is_ignored_safely():
    assert apply_windows_window_icon(object(), Path("__kaptia_missing_icon__.ico")) is False
