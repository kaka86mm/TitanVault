# config/hermes/config.yaml.tpl
# Hermes Agent v0.17 配置 — 指向发行版 LiteLLM (本机 llama.cpp), 非 OpenAI 云端。
# install.sh render_configs 用 envsubst 渲染 ${LLM_MODEL_NAME}/${LITELLM_MASTER_KEY}/
# ${HERMES_DASHBOARD_PASS_HASH} 后放到 ${DATA_DIR}/hermes/config.yaml。
#
# Hermes 原生部署 (非容器): 直接用 localhost:端口 访问各服务 (容器发布的宿主机端口)。
# dashboard.basic_auth: v0.17 非 loopback 绑定 (0.0.0.0) 必须配 auth provider,
# 否则 dashboard 服务拒绝启动。password_hash 由 install.sh 用本地 hermes python 生成
# (scrypt 格式), 明文密码 = HERMES_API_SERVER_KEY。

model:
  default: ${LLM_MODEL_NAME}
  provider: custom
  base_url: http://localhost:4000/v1
  api_key: ${LITELLM_MASTER_KEY}
  # custom provider 无法自动探测 context_length, 手动设 (否则默认 4k 截断)。
  # 值 = 每并发 slot 的上下文 (hardware profile LLM_CTX_PER_SLOT), 非 llama.cpp 总 ctx。
  context_length: ${LLM_CTX_PER_SLOT}

embedding:
  provider: custom
  base_url: http://localhost:4000/v1
  api_key: ${LITELLM_MASTER_KEY}

dashboard:
  basic_auth:
    username: admin
    password_hash: ${HERMES_DASHBOARD_PASS_HASH}

# Gateway api_server platform: OpenAI 兼容 API (:8642)。
# TitanVault 门户的 AI 助手通过此 channel 跟 Hermes 对话 (用 Hermes 的知识库/工具/记忆)。
# 注意: Hermes 源码 (api_server.py:779) 读 extra.key 而非 api_key, 两个字段都给。
# cors_origins=* : TitanVault 同域调用, 内网环境允许 (否则浏览器 Origin 校验 403)。
platforms:
  api_server:
    enabled: true
    api_key: ${HERMES_API_SERVER_KEY}
    extra:
      host: "0.0.0.0"
      port: 8642
      key: ${HERMES_API_SERVER_KEY}
      cors_origins:
        - "*"

# Approvals: 命令执行审批模式。
# manual = 每条命令需 dashboard 人工批准 (api_server 无人值守会卡住)
# smart   = 辅助 LLM 自动批准低风险命令
# "off"   = 全自动执行 (个人工作站单用户场景; 危险命令 rm -rf / 等仍被硬编码拦截)
# 注意: YAML bare off 会被解析成 bool, 必须加引号写 "off"
approvals:
  mode: "off"

# Memory: 长期记忆后端 (hindsight 容器, localhost:8888)。
# hindsight 容器用 infra postgres + pgvector 存储, embedding/reranker 走 litellm。
# config.json 在 hindsight-config.json.tpl (install.sh 渲染)。
memory:
  provider: hindsight

# STT/TTS: 指向本机 SenseVoice (ASR) + Kokoro (TTS), 非 OpenAI 云端。
# 原生 Hermes 用 localhost + 容器发布的宿主机端口访问。
# Kokoro voice: zf_* = 中文女声, zm_* = 中文男声, af_* = 英文女声, am_* = 英文男声。
# 完整列表 GET http://localhost:8081/v1/audio/voices (67个, 含日/韩/法/意/葡)。
# 主场景中文 → 默认 zf_xiaoxiao。英文场景用 af_sky。
tts:
  provider: openai
  openai:
    base_url: http://localhost:8081/v1
    model: kokoro
    voice: zf_xiaoxiao
stt:
  provider: openai
  openai:
    base_url: http://localhost:9991/v1
    model: sensevoice
