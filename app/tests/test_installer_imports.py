"""Regression tests for installer package import paths."""
from __future__ import annotations

import importlib


def test_installer_modules_import_from_app_root():
    hardware = importlib.import_module("installer.hardware_profile")
    locale = importlib.import_module("scripts.kaptia_locale")
    bootstrapper = importlib.import_module("installer.webview_installer")

    assert callable(hardware.detect_hardware)
    assert callable(locale.get_language)
    assert callable(locale.set_language)
    assert callable(bootstrapper.main)
    assert callable(bootstrapper.InstallerAPI)
