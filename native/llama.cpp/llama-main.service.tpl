# native/llama.cpp/llama-main.service.tpl
# 主力 LLM 推理服务 (Vulkan GPU)。
#
# install.sh Phase 5 用 envsubst 渲染: ${DEPLOY_USER} / ${MODEL_DIR} / ${LLM_MODEL_NAME}
# / ${LLM_QUANT} / ${LLM_CTX} / ${LLM_NGL} / ${LLM_MMPROJ} 来自 hardware/aimax-395.profile + .env。
#
# 端口 8082: litellm config.yaml.tpl 经 host-gateway:8082 访问此服务。
[Unit]
Description=llama.cpp Main Server (Vulkan) - ${LLM_MODEL_NAME}
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
# ExecStart 参数对齐 1.22 生产验证配置:
#   --model        gguf 路径 (名=模型+量化, 如 Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf)
#   -ngl 999       全部层卸载到 GPU (395 GTT 内存够 35B Q4 全 offload)
#   -c             上下文长度 (profile 定义, 默认 131072)
#   --parallel     并发请求数
#   -fa on         Flash Attention (Vulkan 后端加速)
#   --cache-type-* KV cache 量化 (省显存, Q4 兼容)
#   --mmproj       多模态投影 (支持图片输入; ${MMPROJ_ARG} 为空则不传)
ExecStart=/opt/llama.cpp/llama-server \
    --model ${MODEL_DIR}/llm/${LLM_MODEL_NAME}-${LLM_QUANT}.gguf \
    -ngl ${LLM_NGL} -c ${LLM_CTX} \
    --parallel ${LLAMA_MAIN_SLOTS} -fa on \
    --cache-type-k q4_0 --cache-type-v q4_0 \
    -b 8192 -ub 4096 \
    --jinja --slots --top-k 20 \
    --reasoning on \
    --spec-type draft-mtp \
    --alias ${LLM_MODEL_NAME} \
    ${MMPROJ_ARG} \
    --host 0.0.0.0 --port 8082 --metrics
Restart=always
RestartSec=5
# GGML_VULKAN_DEVICE=0 选第一个 Vulkan 设备 (395 仅一个核显)
Environment=GGML_VULKAN_DEVICE=0
# b9840+ 把 server 实现拆到 .so, 需指明库搜索路径 (build.sh 默认装 /opt/llama.cpp)
Environment=LD_LIBRARY_PATH=/opt/llama.cpp
# 模型文件大 (22.8GB), 关闭 systemd 启动超时 (默认 90s 不够加载 35B)
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
