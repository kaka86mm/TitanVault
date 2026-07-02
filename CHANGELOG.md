# Changelog

本项目的所有重要变更记录。格式参考 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased]

### Added
- **浏览器自动化（数字员工）**：Hermes + browser-use + Chrome CDP，支持点击/填表/导航/截图/视觉识别
  - Chrome headless 作为 systemd 服务（:9222），browser-use 装入 Hermes venv
  - Qwen3.6 多模态视觉驱动页面操作，登录态持久化
- **kuma 自动初始化**：安装后自动创建 admin 用户 + 灌入 18 项服务监控
- **Hermes default profile 配置**：通用对话 agent 自动配模型
- **opensquilla 自动 onboard**：安装后自动配 provider 指向 LiteLLM

### Changed
- llama-main 启用 `--mmproj`（Qwen3.6 原生多模态视觉能力，之前未开启）
- Docker 镜像源升级为 4 源 fallback（docker.1ms.run → 1panel.live → xuanyuan.me → daocloud）
- build.sh 复制 conversion 包（修复 reranker GGUF 转换 ModuleNotFoundError）
- setup-open-notebook.sh 就绪检测改用 `/api/models` + 180s + 验证补救

### Fixed
- **重装 postgres 密码残留**：旧 data 目录密码与新随机密码不匹配导致 litellm/hindsight/gitea 全挂；改为检测指纹不匹配或检测文件缺失时清理
- **重装 surrealdb 旧 root 用户**：rocksdb 数据残留旧密码，open-notebook 认证失败
- **opensquilla 权限冲突**：容器 uid 10001 残留文件导致原生服务 PermissionError
- **Hermes ops profile config 旧 key**：`profile create --clone` 复制旧 config，gateway 401
- **compose 重装不重建容器**：凭据变更后旧容器保留旧 env，加凭据指纹检测 + force-recreate
- **chrome-cdp SingletonLock**：非正常退出后锁文件残留导致 systemd restart 循环

### Removed
- **MCPJungle**：无 agent 消费的孤立 MCP 注册中心，从 compose/Caddy/门户/postgres/文档全清除

## [0.1.0] - 2026-06-29

### Added
- 首个可用版本
- 6 Phase 安装器（硬件检测 → 配置 → GPU 驱动 → Docker → 模型 → 启动）
- 7 层 compose profile（infra/gateway/ai-capability/network/apps/monitoring/agents）
- 三档预设（minimal/standard/full）
- LLM 推理：Qwen3.6-35B-A3B（llama.cpp Vulkan）+ Embedding + Reranker
- 语音：SenseVoice ASR + Kokoro TTS + Aham Voice 会议纪要
- 文档：MinerU PDF 解析（ROCm GPU）
- 图像：ComfyUI Stable Diffusion（ROCm GPU）
- Agent：Hermes 运维 + OpenSquilla 写代码（原生 systemd）
- 应用：Open Notebook / Gitea / Filebrowser / SearXNG
- 监控：Uptime Kuma + Glances
- 门户：TitanVault React 门面（替代 homepage）
- 预打包离线镜像（国内 docker hub 被墙兜底）
