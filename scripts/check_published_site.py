"""Post-deployment smoke checks for the public Kaptia Pages shell and installer."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

USER_AGENT = "Kaptia-Pages-SmokeCheck/3.0"
TIMEOUT_SECONDS = 20
ATTEMPTS = 4
RETRY_DELAY_SECONDS = 4


def _normalise_base(raw_url: str) -> tuple[str, str]:
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("部署網址不可為空")
    parts = urlsplit(raw_url.strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("部署網址必須是有效的 HTTPS URL")
    if parts.query or parts.fragment:
        raise ValueError("部署網址不可帶 query 或 fragment")
    host = parts.hostname.lower()
    path = parts.path.rstrip("/") + "/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")), host


def _fetch(url: str, expected_host: str) -> tuple[bytes, str]:
    request = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Cache-Control": "no-cache",
        "Accept": "*/*",
    })
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        final = urlsplit(response.geturl())
        if final.scheme != "https" or not final.hostname or final.hostname.lower() != expected_host:
            raise RuntimeError(f"不允許的跨網域或降級重新導向：{response.geturl()}")
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"HTTP 狀態不是 200：{status}（{url}）")
        return response.read(), response.headers.get("Content-Type", "")


def verify_deployed_site(raw_url: str) -> dict[str, str]:
    """Verify the live website, the fixed download URL, and the published checksum."""
    base, host = _normalise_base(raw_url)
    paths = {
        "html": base,
        "service_worker": base + "sw.js",
        "manifest": base + "manifest.webmanifest",
        "installer": base + "downloads/Kaptia-Setup.exe",
        "checksum": base + "downloads/Kaptia-Setup.exe.sha256",
    }
    last_error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            results: dict[str, str] = {}
            html_bytes, html_type = _fetch(paths["html"], host)
            html = html_bytes.decode("utf-8", errors="replace")
            lowered = html.lower()
            if not any(name in html for name in ("Kaptia", "kaptiaLab")):
                raise RuntimeError("部署後 HTML 缺少產品標題")
            if html.count('href="./downloads/Kaptia-Setup.exe"') < 2:
                raise RuntimeError("網站缺少固定的最新 Setup 下載入口")
            if any(marker in lowered for marker in (
                "releases.json", "release-announcements", "github.com/releases",
                "raw.githubusercontent.com", "workers.dev", "cloudflare worker",
            )):
                raise RuntimeError("網站仍暴露版本資訊、GitHub 入口或 Worker 依賴")
            if "html" not in html_type.lower():
                raise RuntimeError(f"HTML Content-Type 不符合預期：{html_type}")
            results["html"] = "200 + product shell + fixed Setup download path"

            sw_bytes, sw_type = _fetch(paths["service_worker"], host)
            sw = sw_bytes.decode("utf-8", errors="replace")
            if "kaptia-pages-v20" not in sw or "NAVIGATION_TIMEOUT_MS" not in sw:
                raise RuntimeError("Service Worker 版本或逾時保護標記不符預期")
            if not any(kind in sw_type.lower() for kind in ("javascript", "ecmascript", "text/plain")):
                raise RuntimeError(f"Service Worker Content-Type 不符合預期：{sw_type}")
            results["service_worker"] = "200 + expected cache/timeout markers"

            manifest_bytes, manifest_type = _fetch(paths["manifest"], host)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, dict) or not str(manifest.get("name", "")).lower().startswith("kaptia"):
                raise RuntimeError("Web manifest JSON 格式或產品名稱不符預期")
            if not any(kind in manifest_type.lower() for kind in ("json", "manifest", "text/plain")):
                raise RuntimeError(f"Manifest Content-Type 不符合預期：{manifest_type}")
            results["manifest"] = "200 + valid product JSON"

            checksum_bytes, _ = _fetch(paths["checksum"], host)
            checksum_text = checksum_bytes.decode("ascii", errors="strict").strip().split()
            if len(checksum_text) != 2 or checksum_text[1] != "Kaptia-Setup.exe" or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum_text[0]):
                raise RuntimeError("官網 Setup SHA-256 sidecar 格式無效")

            installer_bytes, installer_type = _fetch(paths["installer"], host)
            if len(installer_bytes) < 1024 * 1024 or not installer_bytes.startswith(b"MZ"):
                raise RuntimeError("官網 Setup 缺失、過小或不是 Windows PE 檔案")
            actual = hashlib.sha256(installer_bytes).hexdigest()
            if actual != checksum_text[0].lower():
                raise RuntimeError("官網 Setup SHA-256 不符")
            if installer_type and not any(kind in installer_type.lower() for kind in ("octet-stream", "application/x-msdownload", "binary")):
                raise RuntimeError(f"Setup Content-Type 不符合預期：{installer_type}")
            results["installer"] = f"200 + Windows PE + SHA-256 verified ({len(installer_bytes)} bytes)"
            results["checksum"] = "200 + valid SHA-256 sidecar"
            return results
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < ATTEMPTS:
                print(f"[Pages smoke check] Attempt {attempt}/{ATTEMPTS} failed: {type(exc).__name__}: {exc}")
                time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(
        f"部署後網站健康檢查失敗（{ATTEMPTS} 次有限嘗試）："
        f"{type(last_error).__name__}: {last_error}"
    ) from last_error


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_published_site.py <https-page-url>", file=sys.stderr)
        return 2
    try:
        result = verify_deployed_site(sys.argv[1])
    except Exception as exc:
        print(f"[FAIL] Kaptia Pages not healthy: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for name, status in result.items():
        print(f"[PASS] {name}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
