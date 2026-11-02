"""Compatibility entry point; the installer UI is implemented with PyWebView."""
from __future__ import annotations
import sys
try:
    from webview_installer import main
except ImportError:
    from installer.webview_installer import main
if __name__ == "__main__":
    sys.exit(main())
