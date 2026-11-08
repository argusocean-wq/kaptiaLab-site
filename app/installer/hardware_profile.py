"""Windows hardware discovery and conservative Kaptia runtime profile selection.

All values are best-effort observations. Missing GPU telemetry never blocks a CPU
installation, and no browser-reported hardware values are trusted here.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class HardwareReport:
    os_name: str
    os_version: str
    architecture: str
    cpu_logical_cores: int
    ram_total_gb: float | None
    gpus: tuple[dict[str, Any], ...]
    profile_id: str
    profile_label: str
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run(command: list[str], timeout: int = 8) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _ram_total_gb() -> float | None:
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            state = MEMORYSTATUSEX()
            state.dwLength = ctypes.sizeof(state)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
                return round(state.ullTotalPhys / (1024 ** 3), 2)
        except (AttributeError, OSError, ValueError):
            pass
    try:
        if hasattr(os, "sysconf"):
            return round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1024 ** 3), 2)
    except (ValueError, OSError, AttributeError):
        pass
    return None


def _nvidia_gpus() -> list[dict[str, Any]]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        candidates = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                  "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe")]
        exe = next((p for p in candidates if os.path.isfile(p)), None)
    if not exe:
        return []
    output = _run([exe, "--query-gpu=name,memory.total,driver_version",
                   "--format=csv,noheader,nounits"], timeout=12)
    gpus = []
    for line in output.splitlines():
        fields = [part.strip() for part in line.split(",")]
        if len(fields) < 3:
            continue
        try:
            vram_mb = int(re.sub(r"[^0-9]", "", fields[1]))
        except ValueError:
            vram_mb = None
        gpus.append({"name": fields[0], "vendor": "NVIDIA",
                     "vram_mb": vram_mb, "driver_version": fields[2],
                     "source": "nvidia-smi"})
    return gpus


def _windows_display_adapters() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    script = ("Get-CimInstance Win32_VideoController | "
              "Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress")
    output = _run(["powershell.exe", "-NoProfile", "-NonInteractive",
                   "-ExecutionPolicy", "Bypass", "-Command", script], timeout=15)
    if not output:
        return []
    try:
        payload = json.loads(output)
        if isinstance(payload, dict):
            payload = [payload]
        result = []
        for item in payload if isinstance(payload, list) else []:
            name = str(item.get("Name") or "Unknown display adapter")
            try:
                adapter_ram = int(item.get("AdapterRAM") or 0)
            except (ValueError, TypeError):
                adapter_ram = 0
            result.append({"name": name, "vendor": "Unknown",
                           "vram_mb": round(adapter_ram / (1024 ** 2)) if adapter_ram > 0 else None,
                           "driver_version": str(item.get("DriverVersion") or ""),
                           "source": "Windows CIM (VRAM may be capped or inaccurate)"})
        return result
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def detect_hardware() -> HardwareReport:
    os_name = platform.system()
    os_version = platform.version()
    architecture = platform.machine() or "unknown"
    cores = os.cpu_count() or 1
    ram = _ram_total_gb()
    gpus = _nvidia_gpus()
    notes: list[str] = []
    if not gpus:
        gpus = _windows_display_adapters()
        if gpus:
            notes.append("Windows display-adapter VRAM is a driver-reported estimate; NVIDIA telemetry was unavailable.")
    else:
        notes.append("NVIDIA GPU and VRAM were read from nvidia-smi.")
    if not gpus:
        notes.append("No reliable discrete-GPU telemetry found; selecting a conservative CPU-compatible profile.")
    # Only NVIDIA telemetry is eligible for CUDA model profiles. Windows CIM may
    # report large shared/system memory for Intel or AMD display adapters; that is
    # not dedicated CUDA VRAM and must never promote the machine to a GPU profile.
    max_vram = max((g.get("vram_mb") or 0 for g in gpus if g.get("vendor") == "NVIDIA"), default=0)
    ram_value = ram or 0
    if max_vram >= 12 * 1024 and ram_value >= 24:
        profile_id, label = "gpu_high", "High GPU profile"
    elif max_vram >= 8 * 1024 and ram_value >= 16:
        profile_id, label = "gpu_standard", "Standard GPU profile"
    elif max_vram >= 4 * 1024 and ram_value >= 12:
        profile_id, label = "gpu_light", "Light GPU profile"
    else:
        profile_id, label = "cpu_safe", "CPU-safe / low-memory profile"
    if ram is None:
        notes.append("System RAM could not be measured; conservative profile selected.")
    return HardwareReport(os_name, os_version, architecture, cores, ram,
                          tuple(gpus), profile_id, label, tuple(notes))


