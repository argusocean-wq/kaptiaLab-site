from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Kaptia"
VERSION_PATH = ROOT / "version.json"
STATE_PATH = ROOT / "update-state.json"
UA = "Kaptia-Update-Checker"
RELEASE_API = "https://api.github.com/repos/argusocean-wq/kaptiaLab-site/releases/latest"
RELEASE_ASSET_BASE = "https://github.com/argusocean-wq/kaptiaLab-site/releases/download"


def read_json(path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def save_state(data):
    ROOT.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(STATE_PATH)


def get_bytes(url, limit):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Remote metadata exceeds the configured size limit")
    return data


def get_json(url):
    data = json.loads(get_bytes(url, 2 * 1024 * 1024).decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Invalid GitHub release metadata")
    return data


def get_text(url, limit=4096):
    return get_bytes(url, limit).decode("utf-8").strip()


def latest_release_manifest():
    release = get_json(RELEASE_API)
    if release.get("draft") or not release.get("published_at"):
        raise RuntimeError("Latest public release is not published")
    tag = str(release.get("tag_name", ""))
    match = re.fullmatch(r"kaptia-build-([0-9]+)", tag)
    if not match:
        raise RuntimeError("Latest public release does not use a supported Kaptia build tag")
    assets = {
        str(asset.get("name", "")): asset
        for asset in release.get("assets", [])
        if isinstance(asset, dict)
    }
    setup = assets.get("Kaptia-Setup.exe")
    checksum = assets.get("Kaptia-Setup.exe.sha256")
    if not setup or not checksum:
        raise RuntimeError("Latest public release is missing Setup or its SHA-256 sidecar")

    expected_setup_url = f"{RELEASE_ASSET_BASE}/{tag}/Kaptia-Setup.exe"
    expected_checksum_url = f"{RELEASE_ASSET_BASE}/{tag}/Kaptia-Setup.exe.sha256"
    setup_url = str(setup.get("browser_download_url", ""))
    checksum_url = str(checksum.get("browser_download_url", ""))
    if setup_url != expected_setup_url or checksum_url != expected_checksum_url:
        raise RuntimeError("Release assets are outside the trusted public site repository")

    sidecar = get_text(checksum_url)
    sidecar_parts = sidecar.split()
    if len(sidecar_parts) != 2 or sidecar_parts[1] != "Kaptia-Setup.exe" or not re.fullmatch(r"[0-9a-fA-F]{64}", sidecar_parts[0]):
        raise RuntimeError("Public Setup checksum sidecar is malformed")

    return {
        "schema": 1,
        "build_number": int(match.group(1)),
        "tag": tag,
        "source_commit": str(release.get("target_commitish", "unknown")),
        "setup": {
            "sha256": sidecar_parts[0].lower(),
            "url": setup_url,
            "size_bytes": int(setup.get("size", 0) or 0),
        },
    }


def download(url, path, limit, expected_size=0):
    """Download to a temporary file; never expose a partial installer as complete."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    partial = path.with_suffix(path.suffix + ".part")
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=90) as response, partial.open("wb") as output:
            declared = int(response.headers.get("Content-Length", "0") or 0)
            if declared > limit or (expected_size and declared and declared != expected_size):
                raise RuntimeError("Update asset size does not match the release manifest")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise RuntimeError("Update asset exceeds size limit")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if not total or (expected_size and total != expected_size):
            raise RuntimeError("Downloaded update size does not match the release manifest")
        partial.replace(path)
        return total
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def offer_update(manifest):
    number = int(manifest["build_number"])
    tag = str(manifest["tag"])
    setup_meta = manifest.get("setup") or {}
    expected = str(setup_meta.get("sha256", "")).lower()
    url = str(setup_meta.get("url", ""))
    expected_url = f"{RELEASE_ASSET_BASE}/{tag}/Kaptia-Setup.exe"
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("Public release has an invalid Setup SHA-256")
    if url != expected_url:
        raise RuntimeError("Setup URL is outside the trusted public site repository")

    version = read_json(VERSION_PATH, {}).get("build_number", "unknown")
    root = tk.Tk()
    root.withdraw()
    yes = messagebox.askyesno(
        "Kaptia update available",
        f"A new Kaptia build is available.\\n\\nInstalled build: {version}\\nAvailable build: {number}\\n\\nDownload and verify the installer?",
        parent=root,
    )
    root.destroy()
    if not yes:
        state = read_json(STATE_PATH, {})
        state.update({"defer_until": int(time.time()) + 86400, "last_deferred_tag": tag})
        save_state(state)
        return

    update_dir = ROOT / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    installer = update_dir / f"Kaptia-Setup-{number}.exe"
    try:
        download(url, installer, 250 * 1024 * 1024, int(setup_meta.get("size_bytes", 0) or 0))
        with installer.open("rb") as executable:
            if executable.read(2) != b"MZ":
                raise RuntimeError("Downloaded update is not a valid Windows executable")
        actual = sha256_file(installer)
        if actual != expected:
            raise RuntimeError("SHA-256 mismatch; refusing to launch the installer")
        save_state({"last_notified_tag": tag, "last_notified_at": int(time.time()), "defer_until": 0})

        root = tk.Tk()
        root.withdraw()
        proceed = messagebox.askokcancel(
            "Ready to update Kaptia",
            "The installer passed SHA-256 verification. Save your work and close Kaptia before continuing. The installer will then open.",
            parent=root,
        )
        root.destroy()
        if not proceed:
            save_state({"defer_until": int(time.time()) + 86400, "last_deferred_tag": tag})
            return
        subprocess.Popen([str(installer)], cwd=str(update_dir))
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "Kaptia update ready",
            "The installer passed SHA-256 verification and has been opened. Follow its instructions to update.",
            parent=root,
        )
        root.destroy()
    except Exception:
        installer.unlink(missing_ok=True)
        raise


def main():
    settings = read_json(ROOT / "settings.json", {})
    if settings.get("auto_updates", True) is False:
        print("[Kaptia updater] Automatic updates are disabled by the user.")
        return 0
    if os.name != "nt":
        print("[Kaptia updater] Desktop notifications currently support Windows only.")
        return 0
    try:
        current = read_json(VERSION_PATH, {})
        current_number = int(current.get("build_number", 0) or 0)
        state = read_json(STATE_PATH, {})
        now = int(time.time())
        # Avoid redundant GitHub API requests if the checker is started repeatedly.
        last_check = int(state.get("last_check_at", 0) or 0)
        if now - last_check < 5 * 60 * 60:
            print("[Kaptia updater] Recent successful check is still fresh.")
            return 0
        manifest = latest_release_manifest()
        state["last_check_at"] = now
        save_state(state)
        number = manifest["build_number"]
        tag = manifest["tag"]
        if number <= current_number:
            print(f"[Kaptia updater] Up to date (build {current_number}).")
            return 0
        if int(state.get("defer_until", 0) or 0) > now:
            return 0
        if state.get("last_notified_tag") == tag and now - int(state.get("last_notified_at", 0) or 0) < 21600:
            return 0
        offer_update(manifest)
        return 0
    except Exception as exc:
        print(f"[Kaptia updater] Check skipped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
