"""Post-deployment smoke checks for the public Kaptia Pages shell."""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


USER_AGENT = "Kaptia-Pages-SmokeCheck/1.0"
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
    base = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return base, host


def _fetch(url: str, expected_host: str) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache",
            "Accept": "*/*",
        },
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        final = urlsplit(response.geturl())
        if final.scheme != "https" or not final.hostname or final.hostname.lower() != expected_host:
            raise RuntimeError(
                f"不允許的跨網域或降級重新導向：{response.geturl()}"
            )
        status = getattr(response, "status", 200)
        if status != 200:
            raise RuntimeError(f"HTTP 狀態不是 200：{status}（{url}）")
        return response.read(), response.headers.get("Content-Type", "")


def verify_deployed_site(raw_url: str) -> dict[str, str]:
    """Fetch the HTML shell and its core public assets; refuse cross-host redirects."""
    base, host = _normalise_base(raw_url)
    checks = {
        "html": (base, "text/html"),
        "service_worker": (base + "sw.js", "javascript"),
        "manifest": (base + "manifest.webmanifest", "json"),
        "releases": (base + "releases.json", "json"),
        "installer": (base + "downloads/Kaptia-Setup.exe", "binary"),
    }
    last_error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            results: dict[str, str] = {}
            html, html_type = _fetch(checks["html"][0], host)
            html_text = html.decode("utf-8", errors="replace")
            if not any(name in html_text for name in ("Kaptia", "kaptiaLab")) or 'id="releaseList"' not in html_text:
                raise RuntimeError("部署後 HTML 缺少預期產品標題或版本公告區塊")
            if "interactiveBackground" not in html_text:
                raise RuntimeError("部署後 HTML 缺少背景 canvas 入口")
            if "html" not in html_type.lower():
                raise RuntimeError(f"HTML Content-Type 不符合預期：{html_type}")
            results["html"] = "200 + expected shell markers"

            sw_bytes, sw_type = _fetch(checks["service_worker"][0], host)
            sw_text = sw_bytes.decode("utf-8", errors="replace")
            if "kaptia-pages-v14" not in sw_text or "NAVIGATION_TIMEOUT_MS" not in sw_text:
                raise RuntimeError("Service Worker 版本或逾時保護標記不符預期")
            if "javascript" not in sw_type.lower() and "ecmascript" not in sw_type.lower() and "text/plain" not in sw_type.lower():
                raise RuntimeError(f"Service Worker Content-Type 不符合預期：{sw_type}")
            results["service_worker"] = "200 + expected cache/timeout markers"

            manifest_bytes, manifest_type = _fetch(checks["manifest"][0], host)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, dict) or not (str(manifest.get("name", "")).lower().startswith("kaptia") or manifest.get("short_name") == "Kaptia"):
                raise RuntimeError("Web manifest JSON 格式或產品名稱不符預期")
            if "json" not in manifest_type.lower() and "manifest" not in manifest_type.lower() and "text/plain" not in manifest_type.lower():
                raise RuntimeError(f"Manifest Content-Type 不符合預期：{manifest_type}")
            results["manifest"] = "200 + valid JSON/name"

            release_bytes, release_type = _fetch(checks["releases"][0], host)
            release_data = json.loads(release_bytes.decode("utf-8"))
            if not isinstance(release_data, dict) or not isinstance(release_data.get("releases"), list):
                raise RuntimeError("版本資訊 JSON 格式不符預期")
            if release_data.get("downloadReady") is not True:
                raise RuntimeError("版本資訊未標記安裝程式可下載")
            if not release_data["releases"]:
                raise RuntimeError("版本資訊沒有已發布版本")
            if "json" not in release_type.lower() and "text/plain" not in release_type.lower():
                raise RuntimeError(f"版本資訊 Content-Type 不符合預期：{release_type}")

            latest_tag = str(release_data["releases"][0].get("tag_name", ""))
            installer_meta = release_data.get("installer")
            if not isinstance(installer_meta, dict):
                raise RuntimeError("版本資訊缺少安裝檔完整性 metadata")
            if installer_meta.get("file_name") != "Kaptia-Setup.exe":
                raise RuntimeError("安裝檔 metadata 的檔名不符預期")
            if installer_meta.get("tag_name") != latest_tag or not latest_tag:
                raise RuntimeError("安裝檔版本標籤與最新發布版本不一致")
            expected_size = installer_meta.get("size_bytes")
            if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 1024:
                raise RuntimeError("安裝檔 metadata 的檔案大小無效")
            expected_sha256 = installer_meta.get("sha256")
            if not isinstance(expected_sha256, str) or re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256) is None:
                raise RuntimeError("安裝檔 metadata 的 SHA-256 格式無效")
            results["releases"] = "200 + same-origin release metadata and installer version match"

            installer_bytes, installer_type = _fetch(checks["installer"][0], host)
            if len(installer_bytes) < 1024 or not installer_bytes.startswith(b"MZ"):
                raise RuntimeError("官網安裝檔缺失、過小或不是 Windows PE 檔案")
            if len(installer_bytes) != expected_size:
                raise RuntimeError(f"安裝檔大小與 metadata 不一致：expected {expected_size}, got {len(installer_bytes)}")
            actual_sha256 = hashlib.sha256(installer_bytes).hexdigest()
            if actual_sha256.lower() != expected_sha256.lower():
                raise RuntimeError("官網安裝檔 SHA-256 與版本 metadata 不一致")
            results["installer"] = f"200 + Windows PE + SHA-256 match ({len(installer_bytes)} bytes)"

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
