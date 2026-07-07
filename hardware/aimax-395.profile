# hardware/aimax-395.profile
# AMD Ryzen AI Max+ 395 (Radeon 8060S / gfx1151) 硬件参数。
#
# install.sh Phase 2/5 source 此文件, 注入到:
#   - GRUB 内核参数 (Phase 2)
#   - llama.cpp systemd 模板 (Phase 5 envsubst 渲染)
# 本文件提供 native/llama.cpp/*.service.tpl 所需的全部硬件相关变量。

# ===== Vulkan =====
GGML_VULKAN_DEVICE=0   # 395 仅一个核显, 选 device 0

# ===== GRUB 内核参数 (install.sh Phase 2 写入 /etc/default/grub) =====
# amdgpu.gttsize=126976   GTT 显存: 124GB (128G统一内存留4G给系统内核)
#                         单位 MB, 支持 70G+ 大模型全 offload
# ttm.pages_limit=32505856  TTM 页数限制 (匹配 GTT)
# amd_iommu=off           关闭 IOMMU (提升 GPU 直显存访问性能)
# radeon.cik_support=0    禁用旧 radeon 驱动, 强制走 amdgpu
# amdgpu.cik_support=0    同上
GRUB_PARAMS="amdgpu.gttsize=126976 radeon.cik_support=0 amdgpu.cik_support=0 amd_iommu=off ttm.pages_limit=32505856"

# ===== 主力 LLM (Qwen3.6-35B-A3B MoE, MTP 版) =====
# MTP (Multi-Token Prediction) 版推理更快。unsloth UD-Q4_K_XL 是生产验证甜点量化
# (22.8GB, 395 GTT 内存够全 offload)。1.22 生产实测可用。
LLM_MODEL_NAME=Qwen3.6-35B-A3B
LLM_QUANT=UD-Q4_K_XL     # unsloth dynamic quant, 22.8GB
# 总上下文 = 模型最大原生上下文(262144) × 并发数(4) = 1048576。
# llama-server -c 是所有 slot 共享的总大小, --parallel N 分成 N 个 slot,
# 每 slot = ctx/parallel = 262144 (256K, 模型原生上限)。
LLM_CTX=1048576
LLM_NGL=999              # -ngl 999 = 全部层卸载 GPU
# 每请求最大输出 token (litellm 用 max_output_tokens 提示客户端)
LLM_MAX_OUTPUT_TOKENS=32768
# 每并发 slot 的上下文 (= LLM_CTX / LLAMA_MAIN_SLOTS)。供 hermes/opensquilla 等
# agent 客户端配 context_length (它们要知道单次对话可用窗口, 不是总 ctx)。
LLM_CTX_PER_SLOT=262144
# 多模态投影文件 (支持图片输入; 留空则禁用多模态)
LLM_MMPROJ=mmproj-F16.gguf

# ===== Embedding (Qwen3-Embedding-0.6B) =====
EMBED_MODEL_NAME=Qwen3-Embedding-0.6B
EMBED_QUANT=Q8_0         # 0.7GB

# ===== 并发调优 =====
LLAMA_MAIN_SLOTS=4       # llama-server 并发 slot 数 (每 slot 256K 上下文)
SENSEVOICE_NCPU=8        # sensevoice CPU 推理线程 (395 16 核分一半)

# ===== 模型存放根 (systemd 模板用此拼路径) =====
MODEL_DIR=${DATA_DIR:-/data}/models
