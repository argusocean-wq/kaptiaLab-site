"""Local Qwen3 assistant runtime. No scratch model or fine-tuning adapter path."""
from __future__ import annotations

import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

try:
    from kaptia_runtime_config import validate_runtime_config
except ImportError:
    from scripts.kaptia_runtime_config import validate_runtime_config

try:
    from kaptia_identity import KAPTIA_NAME, SYSTEM_PROMPT
except ImportError:
    from scripts.kaptia_identity import KAPTIA_NAME, SYSTEM_PROMPT

DEFAULT_MODEL_ID = "Qwen/Qwen3-8B"


def load_language_engine():
    model_id = os.environ.get("KAPTIA_MODEL_ID", DEFAULT_MODEL_ID).strip()
    quantization = os.environ.get("KAPTIA_QUANTIZATION", "4bit").strip().lower()
    if not model_id:
        raise ValueError("KAPTIA_MODEL_ID 不可為空。")
    if quantization not in {"4bit", "none"}:
        raise ValueError("KAPTIA_QUANTIZATION 僅支援 4bit 或 none。")
    cuda_available = torch.cuda.is_available()
    backend = validate_runtime_config(
        cuda_available=cuda_available,
        quantization=quantization,
        allow_cpu=os.environ.get("KAPTIA_ALLOW_CPU", "0") == "1",
    )

    model_kwargs = {"low_cpu_mem_usage": True, "trust_remote_code": False}
    if cuda_available:
        model_kwargs["device_map"] = "auto"
        model_kwargs["torch_dtype"] = (
            torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        )
        if quantization == "4bit":
            try:
                from transformers import BitsAndBytesConfig
                import bitsandbytes  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "4-bit 推論依賴 bitsandbytes，但目前環境無法載入。"
                    "請確認 Windows、PyTorch、CUDA 與 bitsandbytes 版本相容，"
                    "或在有足夠 VRAM 時將量化方式改為「不量化」。"
                ) from exc
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=model_kwargs["torch_dtype"],
            )
    elif backend == "cpu":
        model_kwargs["device_map"] = {"": "cpu"}
        model_kwargs["torch_dtype"] = torch.float32

    print(f"[{KAPTIA_NAME}] 載入語言模型：{model_id}（量化：{quantization}）")
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True, trust_remote_code=False)
    except Exception as exc:
        raise RuntimeError(
            f"模型 tokenizer 載入失敗：{type(exc).__name__}: {exc}。"
            "請檢查網路、模型識別碼、磁碟空間與 Hugging Face 存取權限。"
        ) from exc
    try:
        model = AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)
    except Exception as exc:
        raise RuntimeError(
            f"模型權重載入失敗：{type(exc).__name__}: {exc}。"
            "請檢查 CUDA/VRAM、PyTorch/bitsandbytes 相容性與可用磁碟空間。"
        ) from exc
    model.eval()
    print(f"[{KAPTIA_NAME}] 語言模型載入完成；裝置映射：{getattr(model, 'hf_device_map', 'cpu')}")
    return tokenizer, model


def build_generator(tokenizer, model):
    def generate(messages, max_new_tokens=512, temperature=0.35):
        prepared = [{"role": "system", "content": SYSTEM_PROMPT}]
        prepared.extend(
            {"role": str(message.get("role", "user")), "content": str(message.get("content", ""))}
            for message in messages[-12:]
            if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
        )
        try:
            inputs = tokenizer.apply_chat_template(
                prepared, tokenize=True, add_generation_prompt=True,
                return_tensors="pt", return_dict=True, enable_thinking=False,
            )
        except TypeError:
            inputs = tokenizer.apply_chat_template(
                prepared, tokenize=True, add_generation_prompt=True,
                return_tensors="pt", return_dict=True,
            )
        input_ids = inputs["input_ids"] if isinstance(inputs, dict) else inputs
        attention_mask = inputs.get("attention_mask") if isinstance(inputs, dict) else None
        device = model.get_input_embeddings().weight.device
        input_ids = input_ids.to(device)
        kwargs = {
            "input_ids": input_ids,
            "max_new_tokens": max(1, min(int(max_new_tokens), 2048)),
            "do_sample": float(temperature) > 0,
            "pad_token_id": tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id,
            "eos_token_id": tokenizer.eos_token_id,
            "repetition_penalty": 1.05,
        }
        if attention_mask is not None:
            kwargs["attention_mask"] = attention_mask.to(device)
        if kwargs["do_sample"]:
            kwargs.update({"temperature": max(0.1, min(float(temperature), 1.2)), "top_p": 0.9})
        with torch.inference_mode():
            output = model.generate(**kwargs)
        answer = tokenizer.decode(output[0, input_ids.shape[-1]:], skip_special_tokens=True).strip()
        if not answer:
            raise RuntimeError("模型生成了空白回覆。請縮短輸入或檢查模型載入與生成日誌。")
        return answer
    return generate
