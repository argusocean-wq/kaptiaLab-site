"""Static and JavaScript syntax guardrails for the GitHub Pages frontend."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / "index.html"
SW_PATH = ROOT / "sw.js"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.inline_scripts: list[str] = []
        self._inside_inline_script = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        if tag.lower() == "script":
            self._inside_inline_script = not bool(attributes.get("src"))
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._inside_inline_script:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._inside_inline_script:
            self.inline_scripts.append("".join(self._parts))
            self._inside_inline_script = False
            self._parts = []


class PagesFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML_PATH.read_text(encoding="utf-8")
        cls.sw = SW_PATH.read_text(encoding="utf-8")
        cls.parser = PageParser()
        cls.parser.feed(cls.html)
        cls.parser.close()

    def test_required_page_elements_exist(self) -> None:
        self.assertIn("interactiveBackground", self.parser.ids)
        self.assertIn("releaseList", self.parser.ids)
        self.assertIn("release-announcements", self.parser.ids)
        self.assertNotIn("plans", self.parser.ids)
        self.assertNotIn("planGrid", self.parser.ids)
        self.assertNotIn("Free、Pro、Ultra", self.html)
        self.assertGreaterEqual(len(self.parser.inline_scripts), 3)

    def test_inline_javascript_and_service_worker_parse(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required by the Pages validation workflow.")
        sources = [(f"inline-{i}.js", script) for i, script in enumerate(self.parser.inline_scripts)]
        sources.append(("sw.js", self.sw))
        with tempfile.TemporaryDirectory(prefix="kaptia-pages-check-") as temp_dir:
            for filename, source in sources:
                path = Path(temp_dir) / filename
                path.write_text(source, encoding="utf-8")
                result = subprocess.run(
                    [node, "--check", str(path)],
                    capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(
                    result.returncode, 0,
                    f"{filename} has a JavaScript syntax error:\\n{result.stderr}",
                )


    def test_canvas_animation_has_bounded_cost_and_visibility_pause(self) -> None:
        self.assertIn("Math.min(42", self.html)
        self.assertIn("width < 640 ? 22", self.html)
        self.assertIn("1000 / 60", self.html)
        self.assertIn("const lineGap = 5 * 96 / 2.54", self.html)
        self.assertIn("const lineGapSq = lineGap * lineGap", self.html)
        self.assertIn("const cellSize = lineGap", self.html)
        self.assertIn("const grid = new Map()", self.html)
        self.assertIn("applyQualityLevel", self.html)
        self.assertIn("frameAccumulator", self.html)
        self.assertIn('document.addEventListener("visibilitychange"', self.html)
        self.assertIn("cancelAnimationFrame(raf)", self.html)
        self.assertIn("if (!ctx)", self.html)

    def test_releases_and_installer_stay_on_same_origin(self) -> None:
        self.assertIn('const releasesUrl = "./releases.json"', self.html)
        self.assertIn('const downloadUrl = "./downloads/Kaptia-Setup.exe"', self.html)
        self.assertIn('downloadReady === true', self.html)
        self.assertNotIn("github.com", self.html.lower())
        self.assertNotIn("raw.githubusercontent.com", self.html.lower())
        self.assertIn('download="Kaptia-Setup.exe"', self.html)
        self.assertIn("installer.size_bytes", self.html)
        self.assertIn("installer.sha256", self.html)
        self.assertIn("為避免提供未驗證檔案，下載已暫停", self.html)
        self.assertNotIn("GitHub Releases 查看", self.html)

    def test_optional_service_worker_cannot_block_page_render(self) -> None:
        self.assertIn('navigator.serviceWorker.register("./sw.js"', self.html)
        self.assertIn("Offline caching is optional", self.html)

    def test_service_worker_has_network_timeout_and_cache_failure_guard(self) -> None:
        self.assertIn("NAVIGATION_TIMEOUT_MS = 8000", self.sw)
        self.assertIn("new AbortController()", self.sw)
        self.assertIn("if (response.status >= 500)", self.sw)
        self.assertIn("A storage/quota failure must not discard a good network response", self.sw)
        self.assertIn("const CACHE = \"kaptia-pages-v13\"", self.sw)


if __name__ == "__main__":
    unittest.main()
