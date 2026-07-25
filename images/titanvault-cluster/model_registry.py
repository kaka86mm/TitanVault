"""
model_registry.py — 本地模型扫描 + 层信息

不预置模型列表 (避免列出用户没下载的模型造成困惑)。
只展示本地实际存在的 GGUF 推理模型, 去重。
"""
import os
import logging

logger = logging.getLogger("cluster.models")

MODEL_DIR = os.environ.get("MODEL_DIR", "/data/models")

# 常见模型的层数映射 (用于层分配计算)
KNOWN_LAYERS = {
    "Qwen3.6-35B": 64,
    "Qwen3-35B": 64,
    "Qwopus": 64,
    "QUEST-9B": 40,
    "Llama-3.3-70B": 80,
    "Llama-3.1-70B": 80,
    "Llama-3-70B": 80,
    "DeepSeek-R1-Distill-Qwen-32B": 64,
    "DeepSeek-V2": 60,
    "Mistral-7B": 32,
    "Qwen2.5-7B": 28,
    "Qwen2-7B": 28,
}


def get_all_models() -> list[dict]:
    """获取所有本地可用的推理模型 (去重)。

    只返回本地实际存在的文件, 不预置未下载的模型。
    """
    from node import scan_local_models

    result = []
    seen_names = set()

    for local in scan_local_models():
        name = local["name"]
        # 去重 (同名的只保留第一个, 通常是不同量化版本)
        if name in seen_names:
            continue
        seen_names.add(name)

        layers = _guess_layers(name)
        result.append({
            "name": name,
            "path": local["path"],
            "size_gb": local["size_gb"],
            "layers": layers,
            "recommended_vram_gb": round(local["size_gb"] * 1.3, 1),
            "source": "local",
            "available_locally": True,
        })

    return result


def get_model_info(path: str) -> dict | None:
    """获取单个模型的详细信息。"""
    for model in get_all_models():
        if model["path"] == path:
            return model
    return None


def _guess_layers(name: str) -> int | None:
    """根据模型名猜测层数。"""
    name_lower = name.lower()
    for key, layers in KNOWN_LAYERS.items():
        if key.lower() in name_lower:
            return layers
    # 按参数量估算
    if "70b" in name_lower or "72b" in name_lower:
        return 80
    if "35b" in name_lower or "32b" in name_lower or "34b" in name_lower:
        return 64
    if "14b" in name_lower or "13b" in name_lower:
        return 48
    if "9b" in name_lower or "8b" in name_lower or "7b" in name_lower:
        return 32
    if "3b" in name_lower:
        return 36
    return None
