"""Stable package entry point for the PyWebView Windows installer."""
from __future__ import annotations

import sys


def main() -> int:
    # This path is executed by CI against the frozen one-file executable. It
    # validates the same package imports used by the normal installer startup.
    if "--self-test-imports" in sys.argv:
        from installer.hardware_profile import detect_hardware
        from scripts.kaptia_locale import get_language, set_language
        from installer.webview_installer import InstallerAPI

        assert callable(detect_hardware)
        assert callable(get_language)
        assert callable(set_language)
        assert callable(InstallerAPI)
        return 0

    from installer.webview_installer import main as run_installer
    run_installer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
