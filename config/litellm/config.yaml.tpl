# config/litellm/config.yaml.tpl
# LiteLLM 路由配置 — 指向本机原生 llama.cpp (Vulkan GPU 推理)
#
# api_base 用 host-gateway: litellm 容器在 bridge 网络, 经 host-gateway 访问
# 宿主机上 systemd 跑的 llama-server (端口 8082 主力 / 8084 embedding)。
#
# install.sh render_configs 用 envsubst 渲染 ${LLM_MODEL_NAME}/${EMBED_MODEL_NAME}
# (来自 hardware/aimax-395.profile)。model 名跟 llama.cpp 的 --alias 一致。
# litellm model_name 用小写短名 (OpenAI 客户端 / Dify / Hermes 等配这个)。
model_list:
  # 主力 LLM: Qwen3.6-35B-A3B (llama.cpp + Vulkan, self-MTP 投机解码)
  # 4 并发 × 每并发 256K 上下文; max_output_tokens 提示客户端单次最大输出 32K
  - model_name: ${LLM_MODEL_NAME}
    litellm_params:
      model: openai/${LLM_MODEL_NAME}
      api_base: http://host-gateway:8082/v1
      api_key: not-needed
      max_output_tokens: ${LLM_MAX_OUTPUT_TOKENS}
  # Embedding: Qwen3-Embedding-0.6B (llama.cpp + Vulkan)
  - model_name: ${EMBED_MODEL_NAME}
    litellm_params:
      model: openai/${EMBED_MODEL_NAME}
      api_base: http://host-gateway:8084/v1
      api_key: not-needed

  # Reranker: Qwen3-Reranker-0.6B (llama.cpp --pooling rank)
  # llama.cpp 暴露 /v1/rerank; litellm cohere provider 发 /v2/rerank → caddy 重写
  # api_base 指向 caddy (经 /rerank/* 路由, caddy rewrite /v2→/v1 转给 host-gateway:8083)
  - model_name: Qwen3-Reranker-0.6B
    litellm_params:
      model: cohere/Qwen3-Reranker-0.6B
      api_base: http://caddy/rerank
      api_key: not-needed

litellm_settings:
  drop_params: true
  request_timeout: 600
  num_budgets: 1

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
