"""Unit tests for the Pages post-deployment health checker; no network access."""
import hashlib
import io
import json
import unittest
from unittest.mock import patch

try:
    import check_published_site as checker
except ImportError:  # Also support python -m unittest scripts.test_published_site.
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

    def test_valid_published_assets_pass(self):
        base = "https://example.github.io/kaptia/"
        html = '<title>kaptiaLab</title><div id="releaseList"></div><canvas id="interactiveBackground"></canvas><a href="./downloads/Kaptia-Setup.exe">Download</a>'
        sw = 'const CACHE = "kaptia-pages-v13"; const NAVIGATION_TIMEOUT_MS = 8000;'
        manifest = json.dumps({"name": "kaptiaLab"})
        installer = b"MZ" + (b"0" * 2048)
        releases = json.dumps({
            "releases": [{"tag_name": "v9.0.0"}],
            "downloadReady": True,
            "installer": {
                "file_name": "Kaptia-Setup.exe",
                "tag_name": "v9.0.0",
                "size_bytes": len(installer),
                "sha256": hashlib.sha256(installer).hexdigest(),
            },
        })
        responses = [
            FakeResponse(html, base, "text/html"),
            FakeResponse(sw, base + "sw.js", "text/javascript"),
            FakeResponse(manifest, base + "manifest.webmanifest", "application/manifest+json"),
            FakeResponse(releases, base + "releases.json", "application/json"),
            FakeResponse(installer, base + "downloads/Kaptia-Setup.exe", "application/octet-stream"),
        ]
        with patch.object(checker, "urlopen", side_effect=responses):
            result = verify_deployed_site(base)
        self.assertEqual(set(result), {"html", "service_worker", "manifest", "releases", "installer"})
        self.assertIn("SHA-256 match", result["installer"])

    def test_installer_checksum_mismatch_fails_closed(self):
        base = "https://example.github.io/kaptia/"
        html = '<title>kaptiaLab</title><div id="releaseList"></div><canvas id="interactiveBackground"></canvas>'
        sw = 'const CACHE = "kaptia-pages-v13"; const NAVIGATION_TIMEOUT_MS = 8000;'
        manifest = json.dumps({"name": "kaptiaLab"})
        installer = b"MZ" + (b"0" * 2048)
        releases = json.dumps({
            "releases": [{"tag_name": "v9.0.0"}],
            "downloadReady": True,
            "installer": {
                "file_name": "Kaptia-Setup.exe",
                "tag_name": "v9.0.0",
                "size_bytes": len(installer),
                "sha256": "0" * 64,
            },
        })
        payloads = {
            base: (html, "text/html"),
            base + "sw.js": (sw, "text/javascript"),
            base + "manifest.webmanifest": (manifest, "application/manifest+json"),
            base + "releases.json": (releases, "application/json"),
            base + "downloads/Kaptia-Setup.exe": (installer, "application/octet-stream"),
        }

        def fake_urlopen(request, timeout):
            body, content_type = payloads[request.full_url]
            return FakeResponse(body, request.full_url, content_type)

        with patch.object(checker, "urlopen", side_effect=fake_urlopen):
            with patch.object(checker.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    verify_deployed_site(base)

    def test_cross_host_redirect_is_rejected(self):
        base = "https://example.github.io/kaptia/"
        fake = FakeResponse("<title>other</title>", "https://other-domain.example/")
        with patch.object(checker, "urlopen", return_value=fake):
            with self.assertRaisesRegex(RuntimeError, "重新導向"):
                # Patch sleep so the expected failure test finishes immediately.
                with patch.object(checker.time, "sleep"):
                    verify_deployed_site(base)


if __name__ == "__main__":
    unittest.main()
