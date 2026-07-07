# native/llama.cpp/llama-main.service.tpl
# 主力 LLM 推理服务 (ROCm 7.2 + MMQ patch)。
#
# install.sh Phase 5 用 envsubst 渲染: ${DEPLOY_USER} / ${MODEL_DIR} / ${LLM_MODEL_NAME}
# / ${LLM_QUANT} / ${LLM_CTX} / ${LLM_NGL} / ${LLM_MMPROJ} 来自 hardware/aimax-395.profile + .env。
#
# 端口 8082: litellm config.yaml.tpl 经 host-gateway:8082 访问此服务。
[Unit]
Description=llama.cpp Main Server (ROCm 7.2 + #21284 MMQ patch) - ${LLM_MODEL_NAME}
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
# ExecStart 参数 — 1.7 生产验证配置 (ROCm 7.2.4 + MMQ patch #21284):
#   --model        gguf 路径 (名=模型+量化)
#   -ngl 999       全部层卸载到 GPU (GTT 122G+ 足够 35B Q4 全 offload)
#   -c             上下文长度 (profile 定义)
#   --parallel 4   4 并发 slots (continuous batching 提升吞吐)
#   -cb             continuous batching (动态调度请求)
#   -fa on          Flash Attention
#   --cache-type-*  KV cache 量化 Q4 (省显存)
#   -b 4096         batch size (prompt 处理批大小)
#   --reasoning on  推理模式 (Qwen3 thinking)
#   --mmproj        多模态投影 (${MMPROJ_ARG} 为空则不传)
ExecStart=/opt/llama.cpp-rocm72/llama-server \
    --model ${MODEL_DIR}/llm/${LLM_MODEL_NAME}-${LLM_QUANT}.gguf \
    -ngl ${LLM_NGL} -c ${LLM_CTX} \
    --parallel 4 -cb -fa on \
    --cache-type-k q4_0 --cache-type-v q4_0 \
    -b 4096 -ub 4096 \
    --jinja --slots --top-k 20 \
    --reasoning on \
    --alias ${LLM_MODEL_NAME} \
    ${MMPROJ_ARG} \
    --host 0.0.0.0 --port 8082 --metrics
Restart=always
RestartSec=5
# ROCm 7.2 运行环境
Environment=LD_LIBRARY_PATH=/opt/rocm/lib:/opt/rocm/lib64:/opt/llama.cpp-rocm72
Environment=HSA_ENABLE_SDMA=0
Environment=HIP_VISIBLE_DEVICES=0
# 模型文件大 (22.8GB), 关闭 systemd 启动超时
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
