"""Unit tests for the Pages post-deployment health checker; no network access."""
import json
import unittest
from unittest.mock import patch

try:
    import check_published_site as checker
except ImportError:
    from scripts import check_published_site as checker

_normalise_base = checker._normalise_base
verify_deployed_site = checker.verify_deployed_site


class FakeResponse:
    def __init__(self, body, url, content_type="text/html; charset=utf-8", status=200):
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.url = url
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return self.url

    def read(self):
        return self.body


class PublishedSiteTests(unittest.TestCase):
    def test_requires_https_and_rejects_query(self):
        with self.assertRaises(ValueError):
            _normalise_base("http://example.com/")
        with self.assertRaises(ValueError):
            _normalise_base("https://example.com/?cache=1")

    def test_valid_base_url_adds_trailing_slash(self):
        base, host = _normalise_base("https://example.github.io/kaptia")
        self.assertEqual(base, "https://example.github.io/kaptia/")
        self.assertEqual(host, "example.github.io")

    def test_latest_setup_only_site_passes(self):
        base = "https://example.github.io/kaptia/"
        html = '<title>kaptiaLab</title><a id="download" href="./downloads/Kaptia-Setup.exe" download="Kaptia-Setup.exe">下載最新 Setup</a>'
        sw = 'const CACHE = "kaptia-pages-v19"; const NAVIGATION_TIMEOUT_MS = 8000;'
        manifest = json.dumps({"name": "kaptiaLab"})
        installer = b"MZ" + (b"0" * 2048)
        responses = [
            FakeResponse(html, base, "text/html"),
            FakeResponse(sw, base + "sw.js", "text/javascript"),
            FakeResponse(manifest, base + "manifest.webmanifest", "application/manifest+json"),
            FakeResponse(installer, base + "downloads/Kaptia-Setup.exe", "application/octet-stream"),
        ]
        with patch.object(checker, "urlopen", side_effect=responses):
            result = verify_deployed_site(base)
        self.assertEqual(set(result), {"html", "service_worker", "manifest", "installer"})
        self.assertIn("Windows PE", result["installer"])

    def test_release_history_is_rejected(self):
        base = "https://example.github.io/kaptia/"
        html = '<title>kaptiaLab</title><a href="./downloads/Kaptia-Setup.exe">Setup</a><section id="release-announcements"></section>'
        responses = [FakeResponse(html, base, "text/html")]
        with patch.object(checker, "urlopen", side_effect=responses):
            with patch.object(checker.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "仍暴露版本資訊"):
                    verify_deployed_site(base)

    def test_non_pe_setup_is_rejected(self):
        base = "https://example.github.io/kaptia/"
        html = '<title>kaptiaLab</title><a href="./downloads/Kaptia-Setup.exe">Setup</a>'
        sw = 'const CACHE = "kaptia-pages-v19"; const NAVIGATION_TIMEOUT_MS = 8000;'
        manifest = json.dumps({"name": "kaptiaLab"})
        responses = [
            FakeResponse(html, base, "text/html"),
            FakeResponse(sw, base + "sw.js", "text/javascript"),
            FakeResponse(manifest, base + "manifest.webmanifest", "application/manifest+json"),
            FakeResponse(b"not-an-exe", base + "downloads/Kaptia-Setup.exe", "application/octet-stream"),
        ]
        with patch.object(checker, "urlopen", side_effect=responses):
            with patch.object(checker.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "Windows PE"):
                    verify_deployed_site(base)

    def test_cross_host_redirect_is_rejected(self):
        base = "https://example.github.io/kaptia/"
        fake = FakeResponse("<title>other</title>", "https://other-domain.example/")
        with patch.object(checker, "urlopen", return_value=fake):
            with patch.object(checker.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "重新導向"):
                    verify_deployed_site(base)


if __name__ == "__main__":
    unittest.main()
