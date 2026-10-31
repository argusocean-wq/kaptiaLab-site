"""Post-deployment smoke checks for the public Kaptia Pages shell."""
from __future__ import annotations

import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

USER_AGENT = "Kaptia-Pages-SmokeCheck/2.0"
TIMEOUT_SECONDS = 15
ATTEMPTS = 6
RETRY_DELAY_SECONDS = 5


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
    """Verify the product page and the one public Setup download; no release feed."""
    base, host = _normalise_base(raw_url)
    paths = {
        "html": base,
        "service_worker": base + "sw.js",
        "manifest": base + "manifest.webmanifest",
        "installer": base + "downloads/Kaptia-Setup.exe",
    }
    last_error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            results: dict[str, str] = {}
            html_bytes, html_type = _fetch(paths["html"], host)
            html = html_bytes.decode("utf-8", errors="replace")
            if not any(name in html for name in ("Kaptia", "kaptiaLab")):
                raise RuntimeError("部署後 HTML 缺少產品標題")
            if 'href="./downloads/Kaptia-Setup.exe"' not in html:
                raise RuntimeError("網站缺少唯一 Setup 下載連結")
            if any(marker in html.lower() for marker in ("releases.json", "release-announcements", "github.com/releases")):
                raise RuntimeError("網站仍暴露版本資訊或 GitHub Release 入口")
            if "html" not in html_type.lower():
                raise RuntimeError(f"HTML Content-Type 不符合預期：{html_type}")
            results["html"] = "200 + product shell + one latest-Setup download path"

            sw_bytes, sw_type = _fetch(paths["service_worker"], host)
            sw = sw_bytes.decode("utf-8", errors="replace")
            if "kaptia-pages-v19" not in sw or "NAVIGATION_TIMEOUT_MS" not in sw:
                raise RuntimeError("Service Worker 版本或逾時保護標記不符預期")
            if "javascript" not in sw_type.lower() and "ecmascript" not in sw_type.lower() and "text/plain" not in sw_type.lower():
                raise RuntimeError(f"Service Worker Content-Type 不符合預期：{sw_type}")
            results["service_worker"] = "200 + expected cache/timeout markers"

            manifest_bytes, manifest_type = _fetch(paths["manifest"], host)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, dict) or not str(manifest.get("name", "")).lower().startswith("kaptia"):
                raise RuntimeError("Web manifest JSON 格式或產品名稱不符預期")
            if "json" not in manifest_type.lower() and "manifest" not in manifest_type.lower() and "text/plain" not in manifest_type.lower():
                raise RuntimeError(f"Manifest Content-Type 不符合預期：{manifest_type}")
            results["manifest"] = "200 + valid product JSON"

            installer_bytes, installer_type = _fetch(paths["installer"], host)
            if len(installer_bytes) < 1024 or not installer_bytes.startswith(b"MZ"):
                raise RuntimeError("官網 Setup 缺失、過小或不是 Windows PE 檔案")
            results["installer"] = f"200 + Windows PE ({len(installer_bytes)} bytes)"
            return results
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
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
