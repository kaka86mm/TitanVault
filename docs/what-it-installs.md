# 包含哪些服务

## 三档 preset

| 层 (profile) | 服务 | minimal | standard | full |
|---|---|:---:|:---:|:---:|
| **infra** | postgres:17+pgvector, redis:7, qdrant | ✅ | ✅ | ✅ |
| **gateway** | caddy, titanvault (门户), litellm, token-usage-api, api-discover | ✅ | ✅ | ✅ |
| **ai-capability** | sensevoice (ASR), kokoro-tts, mineru-web (PDF), aham-voice-web, comfyui | ❌ | ✅ | ✅ |
| **network** | mihomo (代理), frp (穿透) | ❌ | ✅ | ✅ |
| **apps** | open-notebook, filebrowser, searxng, gitea | ❌ | ❌ | ✅ |
| **monitoring** | glances, uptime-kuma | ❌ | ❌ | ✅ |
| **agents** | open-design, next-ai-draw-io, hindsight | ❌ | ❌ | ✅ |

## 原生 systemd 服务 (非容器)

| 服务 | 端口 | 说明 |
|---|---|---|
| llama-main | 8082 | Qwen3.6-35B-A3B 主力推理 (ROCm 7.2 GPU + MMQ patch, 全 offload, 原生多模态) |
| llama-embed | 8084 | Qwen3-Embedding-0.6B 向量化 |
| llama-rerank | 8083 | Qwen3-Reranker-0.6B 重排序 |
| hermes-dashboard | 9119 | Hermes 运维 Agent Web UI (通用对话, default profile) |
| hermes-gateway | 8642 | Hermes 运维 Agent API (ops profile, 门户 AI 助手调用) |
| opensquilla | 18791 | OpenSquilla 写代码 Agent Gateway |
| chrome-cdp | 9222 | Google Chrome headless + CDP (browser-use 浏览器自动化后端) |

> 原生而非容器的原因: 这些服务需要完整宿主机能力 (GPU 直连 / docker CLI / systemctl / 文件系统 / 网络), 容器化收益为负。

## Docker 容器 (31 个)

### 基础设施 (infra)
- **postgres:17 + pgvector** — 共享数据库 (gitea / litellm / hindsight 各一个库)
- **redis:7** — 缓存 + 队列 (litellm / mineru-web 共用)
- **qdrant** — 向量库 (hindsight 记忆检索)

### 网关 (gateway)
- **caddy** — `:80` 统一入口, 按路径反代各服务 + 注入 API key
- **titanvault** — React 门户门面 (服务卡片 + AI 助手 + 用量面板)
- **litellm** — LLM 路由网关, 指向本机 llama.cpp, 提供 OpenAI 兼容 API (:4000)
- **token-usage-api** — LLM 用量统计聚合
- **api-discover** — API 指南页 (端点定义 + 调用示例 + 健康检查)

### AI 能力 (ai-capability)
- **sensevoice** — 原创 FunASR ASR (转写 + 情感 + 语音事件), CPU
- **kokoro-tts** — 文字转语音, CPU
- **mineru-web** — PDF 解析 Web 产品 (6 容器: frontend/backend/worker/redis/minio + mineru-api GPU)
- **mineru-api** — MinerU 推理后端 (ROCm GPU, gfx1151)
- **aham-voice-web** — 录音转写 + 说话人分离 + 会议纪要 (ROCm GPU)
- **comfyui** — Stable Diffusion 图像生成 (ROCm GPU)

### 应用 (apps, full only)
- **open-notebook** — 知识库 (4 类模型自动配置: language/embedding/STT/TTS)
- **open-notebook-surrealdb** — Open Notebook 数据库
- **filebrowser** — 文件管理 (浏览 `/data`)
- **searxng** — 元搜索
- **gitea** — 自托管 Git

### 监控 (monitoring, full only)
- **glances** — 系统资源监控 (:61208)
- **uptime-kuma** — 服务监控 (安装后自动灌入 18 项服务监控)

### Agent (agents, full only)
- **open-design** — 设计工具 (:7456)
- **next-ai-draw-io** — AI 流程图 (:4733)
- **hindsight** — Agent 长期记忆后端 (向量检索)

## 模型清单

| 模型 | 用途 | 大小 | 来源 |
|---|---|---|---|
| Qwen3.6-35B-A3B (UD-Q4_K_XL) | 主力 LLM (多模态) | 23G | modelscope / hf |
| mmproj-F16 | Qwen3.6 视觉投影层 | 1.2G | 随主模型 |
| Qwen3-Embedding-0.6B (Q8_0) | 文本向量 | 0.6G | modelscope / hf |
| Qwen3-Reranker-0.6B (f16) | 重排序 (HF→GGUF 转换) | 1.2G | modelscope / hf |
| SenseVoiceSmall | 语音识别 | 0.9G | modelscope |

> 模型不打包进发行版, 由 `scripts/download-models.sh` 按 MODEL_SOURCE (cn=modelscope / global=hf) 下载。
