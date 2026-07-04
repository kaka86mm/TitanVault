# native/llama.cpp/llama-rerank.service.tpl
# Reranker 推理服务 (Vulkan GPU) - Qwen3-Reranker-0.6B (cross-encoder)。
#
# 与 llama-embed 同机原生跑, 端口 8083。用于 hindsight 记忆召回重排。
# litellm config.yaml.tpl 经 caddy /rerank/* 重写后 host-gateway:8083 访问。
# rerank 模型小 (0.6B), 资源占用与 embed 相当。
# --pooling rank --reranking: cross-encoder 模式, 暴露 /v1/rerank 接口。
[Unit]
Description=llama.cpp Reranker Server (Vulkan) - Qwen3-Reranker-0.6B
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
ExecStart=/opt/llama.cpp/llama-server \
    --model ${MODEL_DIR}/reranker/Qwen3-Reranker-0.6B-f16.gguf \
    --alias Qwen3-Reranker-0.6B \
    --host 0.0.0.0 --port 8083 \
    -ngl 999 -c 8192 --pooling rank --reranking
Restart=always
RestartSec=5
Environment=GGML_VULKAN_DEVICE=0
Environment=LD_LIBRARY_PATH=/opt/llama.cpp
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
