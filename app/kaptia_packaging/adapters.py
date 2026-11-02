"""Built-in, non-executing archive adapters for UPTP."""
from __future__ import annotations

import gzip
import hashlib
import os
import shutil
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRIES = 20_000
MAX_EXPANDED_BYTES = 8 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


class PackagingError(ValueError):
    """A safe, user-actionable packaging failure."""


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _safe_member(root: Path, name: str) -> Path:
    # Archive paths are POSIX paths regardless of the host OS. Backslashes
    # are rejected because Windows treats them as separators.
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise PackagingError(f"Unsafe archive path: {name!r}")
    normalized = name[:-1] if name.endswith("/") else name
    member = PurePosixPath(normalized)
    raw_parts = normalized.split("/")
    if (member.is_absolute() or not member.parts or
            any(p in ("", ".", "..") for p in raw_parts) or
            any(":" in p for p in member.parts)):
        raise PackagingError(f"Unsafe archive path: {name!r}")
    target = root.joinpath(*member.parts)
    if not _inside(root, target):
        raise PackagingError(f"Archive path escapes destination: {name!r}")
    return target


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files(source_root: Path, inputs: list[str]) -> list[tuple[Path, str]]:
    root = source_root.resolve(strict=True)
    if not root.is_dir():
        raise PackagingError("source_root must be a directory")
    if not inputs:
        raise PackagingError("At least one input path is required")
    result: list[tuple[Path, str]] = []
    for item in inputs:
        rel = PurePosixPath(item.replace("\\", "/"))
        if rel.is_absolute() or not rel.parts or any(p in ("", ".", "..") or ":" in p for p in rel.parts):
            raise PackagingError(f"Unsafe input path: {item!r}")
        path = root.joinpath(*rel.parts)
        if not _inside(root, path) or path.is_symlink() or not path.is_file():
            raise PackagingError(f"Input must be a regular file inside source_root: {item!r}")
        result.append((path, rel.as_posix()))
    return result


class ZipAdapter:
    adapter_id = "zip"
    formats = ("zip", "whl")

    def capabilities(self) -> dict[str, Any]:
        return {"formats": list(self.formats), "operations": ["pack", "unpack", "inspect", "verify"]}

    def pack(self, source_root: Path, inputs: list[str], output: Path) -> dict[str, Any]:
        files = _source_files(source_root, inputs)
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path, name in files:
                archive.write(path, name)
        return {"path": str(output), "sha256": _hash(output), "entries": len(files), "bytes": output.stat().st_size}

    def inspect(self, archive_path: Path) -> dict[str, Any]:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            return {"format": "zip", "entries": len(infos), "uncompressed_bytes": sum(i.file_size for i in infos),
                    "compressed_bytes": archive_path.stat().st_size,
                    "names": [i.filename for i in infos[:200]]}

    def unpack(self, archive_path: Path, destination: Path) -> dict[str, Any]:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            _check_archive_limits(archive_path, len(infos), sum(i.file_size for i in infos))
            destination.mkdir(parents=True, exist_ok=True)
            root = destination.resolve()
            for info in infos:
                target = _safe_member(root, info.filename.rstrip("/")) if info.filename.rstrip("/") else None
                mode = (info.external_attr >> 16) & 0xFFFF
                if mode and (mode & 0o170000) == 0o120000:
                    raise PackagingError("Symbolic links are not allowed in archives")
                if target is None:
                    continue
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
        return {"path": str(destination), "entries": len(infos)}

    def verify(self, archive_path: Path) -> dict[str, Any]:
        with zipfile.ZipFile(archive_path) as archive:
            bad = archive.testzip()
            if bad:
                raise PackagingError(f"ZIP CRC verification failed: {bad}")
        return {"valid": True, "sha256": _hash(archive_path)}


class TarAdapter:
    adapter_id = "tar"
    formats = ("tar", "tar.gz", "tgz")

    def capabilities(self) -> dict[str, Any]:
        return {"formats": list(self.formats), "operations": ["pack", "unpack", "inspect", "verify"]}

    def pack(self, source_root: Path, inputs: list[str], output: Path) -> dict[str, Any]:
        files = _source_files(source_root, inputs)
        output.parent.mkdir(parents=True, exist_ok=True)
        mode = "w:gz" if output.name.lower().endswith((".tar.gz", ".tgz")) else "w"
        with tarfile.open(output, mode) as archive:
            for path, name in files:
                archive.add(path, arcname=name, recursive=False)
        return {"path": str(output), "sha256": _hash(output), "entries": len(files), "bytes": output.stat().st_size}

    def inspect(self, archive_path: Path) -> dict[str, Any]:
        with tarfile.open(archive_path, "r:*") as archive:
            members = archive.getmembers()
            return {"format": "tar", "entries": len(members), "uncompressed_bytes": sum(m.size for m in members),
                    "compressed_bytes": archive_path.stat().st_size,
                    "names": [m.name for m in members[:200]]}

    def unpack(self, archive_path: Path, destination: Path) -> dict[str, Any]:
        with tarfile.open(archive_path, "r:*") as archive:
            members = archive.getmembers()
            _check_archive_limits(archive_path, len(members), sum(max(0, m.size) for m in members))
            destination.mkdir(parents=True, exist_ok=True)
            root = destination.resolve()
            for member in members:
                target = _safe_member(root, member.name.rstrip("/")) if member.name.rstrip("/") else None
                if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                    raise PackagingError("Links, devices and FIFOs are not allowed in TAR archives")
                if target is None:
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise PackagingError(f"Cannot read TAR member: {member.name}")
                    with source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
        return {"path": str(destination), "entries": len(members)}

    def verify(self, archive_path: Path) -> dict[str, Any]:
        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive:
                if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                    raise PackagingError("Unsafe TAR member type")
                if member.size < 0:
                    raise PackagingError("Negative TAR member size")
        return {"valid": True, "sha256": _hash(archive_path)}


class GzipAdapter:
    adapter_id = "gzip"
    formats = ("gz",)

    def capabilities(self) -> dict[str, Any]:
        return {"formats": list(self.formats), "operations": ["pack", "unpack", "inspect", "verify"]}

    def pack(self, source_root: Path, inputs: list[str], output: Path) -> dict[str, Any]:
        files = _source_files(source_root, inputs)
        if len(files) != 1:
            raise PackagingError("GZIP accepts exactly one input file")
        output.parent.mkdir(parents=True, exist_ok=True)
        with files[0][0].open("rb") as src, gzip.open(output, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        return {"path": str(output), "sha256": _hash(output), "entries": 1, "bytes": output.stat().st_size}

    def inspect(self, archive_path: Path) -> dict[str, Any]:
        with gzip.open(archive_path, "rb") as stream:
            size = 0
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_EXPANDED_BYTES:
                    raise PackagingError("Expanded GZIP data exceeds the configured limit")
        return {"format": "gzip", "entries": 1, "uncompressed_bytes": size,
                "compressed_bytes": archive_path.stat().st_size}

    def unpack(self, archive_path: Path, destination: Path) -> dict[str, Any]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(archive_path, "rb") as src, destination.open("xb") as dst:
            total = 0
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_EXPANDED_BYTES:
                    raise PackagingError("Expanded GZIP data exceeds the configured limit")
                dst.write(chunk)
        return {"path": str(destination), "bytes": destination.stat().st_size}

    def verify(self, archive_path: Path) -> dict[str, Any]:
        self.inspect(archive_path)
        return {"valid": True, "sha256": _hash(archive_path)}


class ReadOnlyInstallerAdapter:
    """Inspect executable installer metadata without running or unpacking it."""
    adapter_id = "windows-installer"
    formats = ("exe", "msi")

    def capabilities(self) -> dict[str, Any]:
        return {"formats": list(self.formats), "operations": ["inspect", "verify"]}

    def inspect(self, archive_path: Path) -> dict[str, Any]:
        with archive_path.open("rb") as stream:
            header = stream.read(4096)
        suffix = archive_path.suffix.lower()
        if suffix == ".exe":
            valid = header.startswith(b"MZ")
            fmt = "pe-executable"
        else:
            valid = len(header) >= 8 and header[0:4] == bytes.fromhex("d0cf11e0")
            fmt = "msi-ole-container"
        if not valid:
            raise PackagingError(f"File does not have a recognized {suffix.upper()} container signature")
        return {"format": fmt, "bytes": archive_path.stat().st_size, "executable": True,
                "execution_performed": False}

    def verify(self, archive_path: Path) -> dict[str, Any]:
        metadata = self.inspect(archive_path)
        return {"valid": True, "sha256": _hash(archive_path), **metadata}


def _check_archive_limits(path: Path, entries: int, expanded: int) -> None:
    compressed = path.stat().st_size
    if compressed > MAX_ARCHIVE_BYTES:
        raise PackagingError("Archive exceeds the compressed-size limit")
    if entries > MAX_ENTRIES:
        raise PackagingError("Archive contains too many entries")
    if expanded > MAX_EXPANDED_BYTES:
        raise PackagingError("Archive exceeds the expanded-size limit")
    if compressed > 0 and expanded / compressed > MAX_COMPRESSION_RATIO:
        raise PackagingError("Archive exceeds the compression-ratio limit")


BUILTIN_ADAPTERS = (ZipAdapter(), TarAdapter(), GzipAdapter(), ReadOnlyInstallerAdapter())
