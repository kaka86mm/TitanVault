"""
model_registry.py — 预置模型列表 + 本地模型扫描
"""
import os
import logging
from typing import Optional

logger = logging.getLogger("cluster.models")

MODEL_DIR = os.environ.get("MODEL_DIR", "/data/models")
LLAMA_CPP_DIR = os.environ.get("LLAMA_CPP_DIR", "/opt/llama.cpp")

# 预置模型 (跟 hardware profile 对齐, 用户也可以手动填路径)
PRESET_MODELS = [
    {
        "name": "Qwen3.6-35B-A3B (Q5_K_M)",
        "path": "/data/models/llm/Qwen3.6-35B-A3B/Qwen3.6-35B-A3B-UD-Q5_K_M.gguf",
        "size_gb": 24.0,
        "layers": 64,
        "recommended_vram_gb": 28,
        "notes": "主力对话/代码模型, MoE 35B 实际激活 3B",
    },
    {
        "name": "QUEST-9B (Q4)",
        "path": "/data/models/llm/QUEST-9B-Q4-nomtp.gguf",
        "size_gb": 5.3,
        "layers": 40,
        "recommended_vram_gb": 8,
        "notes": "深度研究专用模型 (OSU NLP)",
    },
    {
        "name": "DeepSeek-R1-Distill-Qwen-32B (Q4_K_M)",
        "path": "/data/models/llm/DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf",
        "size_gb": 19.9,
        "layers": 64,
        "recommended_vram_gb": 24,
        "notes": "推理模型, 需要双机才能流畅运行",
    },
    {
        "name": "Llama-3.3-70B (Q4_K_M)",
        "path": "/data/models/llm/Llama-3.3-70B-Q4_K_M.gguf",
        "size_gb": 42.5,
        "layers": 80,
        "recommended_vram_gb": 48,
        "notes": "大模型, 单机 128GB 可跑但慢, 双机加速",
    },
]


def get_all_models() -> list[dict]:
    """获取所有可用模型: 预置 + 本地扫描, 去重。"""
    from node import scan_local_models

    result = []
    seen_paths = set()

    # 预置模型 (标注是否本地存在)
    for preset in PRESET_MODELS:
        model = dict(preset)
        model["source"] = "preset"
        model["available_locally"] = os.path.exists(preset["path"])
        result.append(model)
        seen_paths.add(preset["path"])

    # 本地扫描 (只加预置里没有的)
    for local in scan_local_models():
        if local["path"] not in seen_paths:
            model = {
                "name": local["name"],
                "path": local["path"],
                "size_gb": local["size_gb"],
                "layers": None,  # 未知, 需要读 GGUF 元数据
                "recommended_vram_gb": local["size_gb"] * 1.3,  # 估算
                "notes": "本地扫描",
                "source": "local",
                "available_locally": True,
            }
            result.append(model)
            seen_paths.add(local["path"])

    return result


def get_model_info(path: str) -> Optional[dict]:
    """获取单个模型的详细信息 (从预置列表或本地)。"""
    for model in get_all_models():
        if model["path"] == path:
            return model
    return None


def parse_gguf_layers(path: str) -> Optional[int]:
    """尝试从 GGUF 文件读取层数 (block_count)。

    GGUF 文件头部包含元数据, 但完整解析需要 gguf 库。
    这里用简单的方式: 预置表已知层数, 扫描的给 None。
    """
    for model in PRESET_MODELS:
        if model["path"] == path:
            return model.get("layers")
    return None
