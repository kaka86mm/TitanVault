# native/llama.cpp/llama-embed.service.tpl
# Embedding 推理服务 (Vulkan GPU)。
#
# 与 llama-main 同机原生跑, 端口 8084。litellm config.yaml.tpl 经 host-gateway:8084 访问。
# embedding 模型小 (0.6B), 上下文短, 资源占用远小于主力 35B。
[Unit]
Description=llama.cpp Embedding Server (Vulkan) - ${EMBED_MODEL_NAME}
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
ExecStart=/opt/llama.cpp/llama-server \
    --model ${MODEL_DIR}/embedding/${EMBED_MODEL_NAME}-${EMBED_QUANT}.gguf \
    --alias ${EMBED_MODEL_NAME} \
    --host 0.0.0.0 --port 8084 \
    -ngl ${LLM_NGL} -c 8192 --embedding
Restart=always
RestartSec=5
Environment=GGML_VULKAN_DEVICE=0
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
