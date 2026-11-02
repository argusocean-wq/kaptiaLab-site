"""Compatibility entry point; KaptiaLab desktop UI is implemented with PyWebView."""
from __future__ import annotations
import sys
try:
    from kaptia_webview import main
except ImportError:
    from scripts.kaptia_webview import main
if __name__ == "__main__":
    sys.exit(main())
