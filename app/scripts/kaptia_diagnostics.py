"""Preflight diagnostics for Kaptia's local model runtime.

This module deliberately imports heavy ML libraries only when diagnostics run.
It reports actionable checks and never silently switches a CUDA model to CPU.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import os
import platform
import shutil
import struct
from pathlib import Path
from typing import Any


def _check(checks: list[dict[str, str]], key: str, label: str,
           status: str, detail: str) -> None:
    checks.append({"id": key, "label": label, "status": status, "detail": detail})


def run_diagnostics(model_id: str = "Qwen/Qwen3-8B",
                    quantization: str = "4bit",
                    cache_dir: str | None = None) -> dict[str, Any]:
    """Inspect the current Windows/Python/CUDA stack before downloading model weights."""
    checks: list[dict[str, str]] = []
    hard_failures = 0
    warnings = 0

    def add(key: str, label: str, status: str, detail: str) -> None:
        nonlocal hard_failures, warnings
        _check(checks, key, label, status, detail)
        hard_failures += status == "fail"
        warnings += status == "warn"

    system = platform.system()
    architecture = platform.machine().lower()
    python_bits = struct.calcsize("P") * 8
    add("platform", "作業系統", "pass" if system == "Windows" and architecture in {"amd64", "x86_64"} else "warn",
        f"{system} / {architecture}；Kaptia 主要驗證目標為 Windows x64。")
    add("python", "Python 執行環境", "pass" if python_bits == 64 and sys_version_supported() else "fail",
        f"Python {platform.python_version()} / {python_bits}-bit；需要 64 位元 Python 3.10 或 3.11。")

    try:
        torch = importlib.import_module("torch")
        torch_version = str(getattr(torch, "__version__", "unknown"))
        cuda_version = getattr(getattr(torch, "version", None), "cuda", None)
        cuda_ok = bool(torch.cuda.is_available())
        add("pytorch", "PyTorch", "pass", f"版本 {torch_version}；CUDA runtime {cuda_version or '未包含'}。")
        if not cuda_ok:
            add("cuda", "NVIDIA CUDA", "fail",
                "PyTorch 無法使用 CUDA。請確認 NVIDIA 驅動程式與 CUDA 版 PyTorch 相容；目前不會自動退回高記憶體需求的 CPU 推論。")
            gpu_name = None
            vram_gb = None
            capability = None
        else:
            try:
                index = torch.cuda.current_device()
                props = torch.cuda.get_device_properties(index)
                gpu_name = str(props.name)
                vram_gb = round(float(props.total_memory) / (1024 ** 3), 2)
                capability = torch.cuda.get_device_capability(index)
                cc = f"{capability[0]}.{capability[1]}"
                add("cuda", "NVIDIA CUDA", "pass", f"{gpu_name}；CUDA {cuda_version}；Compute Capability {cc}。")
                if capability < (6, 0):
                    add("gpu_capability", "GPU 運算能力", "fail",
                        f"Compute Capability {cc} 低於 NF4 量化最低要求 6.0。")
                elif vram_gb < 8:
                    add("vram", "GPU VRAM", "fail",
                        f"{vram_gb} GB；低於 Kaptia Qwen3-8B 4-bit 的保守最低門檻 8 GB。")
                elif vram_gb < 12:
                    add("vram", "GPU VRAM", "warn",
                        f"{vram_gb} GB；可嘗試 4-bit，但較長上下文可能造成 OOM；建議 12 GB 以上。")
                else:
                    add("vram", "GPU VRAM", "pass", f"{vram_gb} GB；符合建議容量。")
                if quantization == "none" and vram_gb < 20:
                    add("unquantized_vram", "未量化 VRAM", "fail",
                        f"{vram_gb} GB；未量化 Qwen3-8B 建議至少 20 GB VRAM。")
            except Exception as exc:
                gpu_name, vram_gb, capability = None, None, None
                add("gpu_probe", "GPU 資訊", "fail", f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        torch = None
        gpu_name, vram_gb, capability = None, None, None
        add("pytorch", "PyTorch", "fail",
            f"無法載入 PyTorch：{type(exc).__name__}: {exc}。請重新安裝與目前 Python 相容的 PyTorch。")
        add("cuda", "NVIDIA CUDA", "fail", "PyTorch 未能載入，無法驗證 CUDA。")

    try:
        transformers = importlib.import_module("transformers")
        version = str(getattr(transformers, "__version__", "unknown"))
        try:
            parts = tuple(int(part) for part in version.split(".")[:2])
        except ValueError:
            parts = (0, 0)
        status = "pass" if parts >= (4, 51) else "fail"
        add("transformers", "Transformers", status,
            f"版本 {version}；Qwen3 需要 Transformers 4.51.0 或更新版本。")
    except Exception as exc:
        add("transformers", "Transformers", "fail",
            f"無法載入：{type(exc).__name__}: {exc}。")

    if quantization == "4bit":
        try:
            bnb = importlib.import_module("bitsandbytes")
            add("bitsandbytes", "4-bit 量化套件", "pass",
                f"bitsandbytes {getattr(bnb, '__version__', '已載入')} 可被目前 Python 載入。")
        except Exception as exc:
            add("bitsandbytes", "4-bit 量化套件", "fail",
                f"bitsandbytes 載入失敗：{type(exc).__name__}: {exc}。請檢查 PyTorch、CUDA 與 bitsandbytes 相容性。")
    elif quantization != "none":
        add("quantization", "量化設定", "fail", f"不支援的量化設定：{quantization!r}。")
    else:
        add("bitsandbytes", "4-bit 量化套件", "pass", "目前設定為不量化，不需要 bitsandbytes。")

    model_id = str(model_id).strip()
    add("model_id", "模型識別碼", "pass" if model_id and len(model_id) <= 200 and not any(c.isspace() for c in model_id) else "fail",
        model_id or "模型識別碼不可為空。")

    cache = Path(cache_dir or os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))
    try:
        cache.mkdir(parents=True, exist_ok=True)
        free_gb = round(shutil.disk_usage(cache).free / (1024 ** 3), 2)
        status = "pass" if free_gb >= 20 else "warn" if free_gb >= 16 else "fail"
        add("disk", "模型快取磁碟空間", status,
            f"{cache} 可用 {free_gb} GB；建議至少保留 20 GB 供模型下載與快取使用。")
    except Exception as exc:
        add("disk", "模型快取磁碟空間", "warn", f"無法檢查磁碟空間：{type(exc).__name__}: {exc}")

    ok = hard_failures == 0
    return {
        "ok": ok,
        "summary": ("環境預檢通過" if ok else f"環境預檢未通過：{hard_failures} 項必要檢查失敗")
                   + (f"，另有 {warnings} 項警告" if warnings else ""),
        "model_id": model_id,
        "quantization": quantization,
        "gpu": gpu_name,
        "vram_gb": vram_gb,
        "checks": checks,
        "failure_count": hard_failures,
        "warning_count": warnings,
    }


def sys_version_supported() -> bool:
    import sys
    return sys.version_info[:2] in {(3, 10), (3, 11)}
