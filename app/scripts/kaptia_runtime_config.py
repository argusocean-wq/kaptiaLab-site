"""Pure validation for local model runtime configuration.

Kept independent of torch/transformers so configuration can be tested before
large ML dependencies are imported.
"""
from __future__ import annotations


def validate_runtime_config(cuda_available: bool, quantization: str,
                            allow_cpu: bool) -> str:
    """Return the selected backend or fail before allocating model memory."""
    if quantization not in {"4bit", "none"}:
        raise ValueError("KAPTIA_QUANTIZATION 僅支援 4bit 或 none。")
    if cuda_available:
        return "cuda"
    if not allow_cpu:
        raise RuntimeError(
            "沒有偵測到可用的 NVIDIA CUDA GPU。Qwen3-8B 本機模式需要相容的 NVIDIA GPU；"
            "若要在 CPU 上嘗試低速推論，請明確設定 KAPTIA_ALLOW_CPU=1。"
        )
    if quantization == "4bit":
        raise RuntimeError(
            "目前 CPU 路徑不支援此設定的 bitsandbytes 4-bit 量化；"
            "原本的行為會靜默改用 FP32，可能造成大量 RAM 使用或系統記憶體不足。"
            "請改用相容的 CUDA 4-bit 環境。CPU FP32 僅能在具備足夠系統記憶體時，"
            "明確設定 KAPTIA_QUANTIZATION=none 後嘗試。"
        )
    return "cpu"
