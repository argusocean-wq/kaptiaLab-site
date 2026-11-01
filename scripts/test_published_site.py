"""Unit tests for the Pages post-deployment health checker; no network access."""
import hashlib
import json
import unittest
from unittest.mock import patch

try:
    import check_published_site as checker
except ImportError:
    from scripts import check_published_site as checker


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
    def payloads(self, base, *, installer=None, checksum=None, html=None):
        installer = installer if installer is not None else b"MZ" + (b"0" * (1024 * 1024))
        digest = hashlib.sha256(installer).hexdigest()
        checksum = checksum if checksum is not None else f"{digest}  Kaptia-Setup.exe"
        html = html or (
            '<title>kaptiaLab</title>'
            '<a id="topDownload" href="./downloads/Kaptia-Setup.exe" download="Kaptia-Setup.exe">Download</a>'
            '<a id="download" href="./downloads/Kaptia-Setup.exe" download="Kaptia-Setup.exe">下載最新 Setup</a>'
        )
        return {
            base: FakeResponse(html, base, "text/html"),
            base + "sw.js": FakeResponse(
                'const CACHE = "kaptia-pages-v20"; const NAVIGATION_TIMEOUT_MS = 8000;',
                base + "sw.js", "text/javascript"
            ),
            base + "manifest.webmanifest": FakeResponse(
                json.dumps({"name": "kaptiaLab"}), base + "manifest.webmanifest", "application/manifest+json"
            ),
            base + "downloads/Kaptia-Setup.exe.sha256": FakeResponse(
                checksum, base + "downloads/Kaptia-Setup.exe.sha256", "text/plain"
            ),
            base + "downloads/Kaptia-Setup.exe": FakeResponse(
                installer, base + "downloads/Kaptia-Setup.exe", "application/octet-stream"
            ),
        }

    def test_requires_https_and_rejects_query(self):
        with self.assertRaises(ValueError):
            checker._normalise_base("http://example.com/")
        with self.assertRaises(ValueError):
            checker._normalise_base("https://example.com/?cache=1")

    def test_valid_base_url_adds_trailing_slash(self):
        base, host = checker._normalise_base("https://example.github.io/kaptia")
        self.assertEqual(base, "https://example.github.io/kaptia/")
        self.assertEqual(host, "example.github.io")

    def test_latest_setup_only_site_passes_with_matching_checksum(self):
        base = "https://example.github.io/kaptia/"
        payloads = self.payloads(base)
        with patch.object(checker, "urlopen", side_effect=lambda request, timeout: payloads[request.full_url]):
            result = checker.verify_deployed_site(base)
        self.assertEqual(set(result), {"html", "service_worker", "manifest", "installer", "checksum"})
        self.assertIn("SHA-256 verified", result["installer"])

    def test_release_history_and_external_gateway_are_rejected(self):
        base = "https://example.github.io/kaptia/"
        payloads = self.payloads(
            base,
            html='<title>kaptiaLab</title><a href="./downloads/Kaptia-Setup.exe">Setup</a>'
                 '<a href="./downloads/Kaptia-Setup.exe">Download</a><section id="release-announcements"></section>',
        )
        with patch.object(checker, "urlopen", side_effect=lambda request, timeout: payloads[request.full_url]):
            with patch.object(checker.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "版本資訊"):
                    checker.verify_deployed_site(base)

    def test_non_pe_setup_is_rejected(self):
        base = "https://example.github.io/kaptia/"
        payloads = self.payloads(base, installer=b"not-an-exe")
        with patch.object(checker, "urlopen", side_effect=lambda request, timeout: payloads[request.full_url]):
            with patch.object(checker.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "Windows PE"):
                    checker.verify_deployed_site(base)

    def test_checksum_mismatch_fails_closed(self):
        base = "https://example.github.io/kaptia/"
        payloads = self.payloads(base, checksum=f'{"0" * 64}  Kaptia-Setup.exe')
        with patch.object(checker, "urlopen", side_effect=lambda request, timeout: payloads[request.full_url]):
            with patch.object(checker.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    checker.verify_deployed_site(base)

    def test_cross_host_redirect_is_rejected(self):
        base = "https://example.github.io/kaptia/"
        fake = FakeResponse("<title>other</title>", "https://other-domain.example/")
        with patch.object(checker, "urlopen", return_value=fake):
            with patch.object(checker.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "重新導向"):
                    checker.verify_deployed_site(base)


if __name__ == "__main__":
    unittest.main()
