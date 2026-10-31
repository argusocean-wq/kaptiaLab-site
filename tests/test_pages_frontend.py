"""Static and JavaScript syntax guardrails for the latest-Setup-only Pages frontend."""
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
        self.links: list[dict[str, str]] = []
        self.inline_scripts: list[str] = []
        self._inside_inline_script = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        if tag.lower() == "a":
            self.links.append(attributes)
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

    def test_product_sections_and_direct_setup_links_exist(self) -> None:
        for element in ("overview", "get-started", "requirements", "topDownload", "download"):
            self.assertIn(element, self.parser.ids)
        self.assertNotIn("releaseList", self.parser.ids)
        self.assertNotIn("release-announcements", self.html)
        self.assertNotIn("setupDialog", self.parser.ids)
        self.assertNotIn("plans", self.parser.ids)
        self.assertNotIn("planGrid", self.parser.ids)
        self.assertNotIn("Free、Pro、Ultra", self.html)
        setup_links = [link for link in self.parser.links if link.get("href") == "./downloads/Kaptia-Setup.exe"]
        self.assertGreaterEqual(len(setup_links), 2)
        self.assertTrue(all(link.get("download") == "Kaptia-Setup.exe" for link in setup_links))
        self.assertGreaterEqual(len(self.parser.inline_scripts), 1)

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
                self.assertEqual(result.returncode, 0, f"{filename} syntax error:\\n{result.stderr}")

    def test_site_does_not_expose_release_history_or_repository_links(self) -> None:
        lowered = self.html.lower()
        for marker in ("releases.json", "release-announcements", "github.com/releases", "raw.githubusercontent.com"):
            self.assertNotIn(marker, lowered)
        self.assertIn('href="./downloads/Kaptia-Setup.exe"', self.html)
        self.assertIn("下載最新 Setup", self.html)
        self.assertIn("安裝程式會透過安全下載服務取得核心套件", self.html)

    def test_removed_background_canvas_stays_absent(self) -> None:
        self.assertNotIn('id="interactiveBackground"', self.html)

    def test_service_worker_keeps_navigation_timeout_and_download_out_of_cache(self) -> None:
        self.assertIn("NAVIGATION_TIMEOUT_MS = 8000", self.sw)
        self.assertIn("new AbortController()", self.sw)
        self.assertIn("if (response.status >= 500)", self.sw)
        self.assertIn("A storage/quota failure must not discard a good network response", self.sw)
        self.assertIn('const CACHE = "kaptia-pages-v19"', self.sw)
        self.assertIn('Kaptia-Setup.exe', self.sw)


if __name__ == "__main__":
    unittest.main()
