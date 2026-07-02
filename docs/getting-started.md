# 快速开始

TitanVault / TitanVault 是专为 AMD Ryzen AI Max+ 395 打造的开箱即用本地 AI 工作站。本文档带你从零完成安装。

## 硬件要求

| 项 | 要求 |
|---|---|
| CPU/APU | **AMD Ryzen AI Max+ 395** (Radeon 8060S / gfx1151) |
| 系统 | Ubuntu 24.04 / 26.04 LTS |
| 内存 | 64 GB+ (跑 35B 全 offload) |
| 磁盘 | 120 GB+ (模型 31G + 镜像 70G + 数据) |
| 网络 | 首次安装需联网 (拉镜像 + 下载模型) |

> 仅支持 395。其它 GPU (NVIDIA / Intel / 其它 AMD) 不在目标内, 安装器会在 Phase 0 拒绝。

## 一行安装

```bash
git clone https://github.com/<org>/TitanVault.git
cd TitanVault
bash install.sh
```

## 安装流程 (约 1 小时)

安装器分 6 个 Phase, 带断点续接 (中断/重启后自动从上次处继续):

| Phase | 做什么 | 耗时 | 需干预 |
|---|---|---|---|
| 0 | 硬件检测 (gfx1151 + Ubuntu) | 5s | 否 |
| 1 | 交互配置 (选档位/目录/模型源) + 生成密码 | 2min | **是** |
| 2 | GPU 驱动 (GRUB + Mesa + Vulkan), 重启一次 | ~15min | 重启 |
| 3 | Docker + 镜像 (build ROCm + pull 第三方 + 离线包) | ~30min | 否 |
| 4 | 模型下载 (35B + embed + rerank + ASR) | ~30min | 否 |
| 5 | 启动 (编译 llama.cpp + compose up + hermes/opensquilla/chrome) | ~10min | 否 |
| 6 | 完成, 打印访问地址 + 密码 | 即时 | **记录密码** |

### Phase 1 会问你

1. **安装档位** — `minimal` / `standard` (默认) / `full`, 详见 [what-it-installs.md](what-it-installs.md)
2. **数据目录** — 默认 `/data`
3. **模型下载源** — `cn` (modelscope, 国内快) / `global` (HuggingFace, 全球)
4. **代理/穿透** — mihomo 订阅 / frp 凭证 (均可留空跳过)

密码全部由安装器用 `openssl rand` 随机生成, 不需要你设。

## 安装完成后

打开浏览器访问 `http://你的机器IP`, 看到 TitanVault 门户, 所有服务卡片已就绪。

Phase 6 会**一次性**打印所有密码 (PostgreSQL / Redis / LiteLLM / Hermes), 请立即保存到密码管理器 —— 这些密码也存在 `.env` (权限 600)。

### 核心服务快速验证

```bash
# LLM 对话 (经 LiteLLM)
curl -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer <你的LiteLLM key>" \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3.6-35B-A3B","messages":[{"role":"user","content":"你好"}]}'

# 门户 AI 助手 (右下角, 经 Caddy 反代 Hermes)
# 直接在浏览器 http://你的IP 点右下角聊天气泡

# 浏览器自动化 (Hermes 调 browser-use)
hermes -p ops -z "用 browser-use 导航到 http://localhost:80/, 告诉我标题" --cli
```

## 常用命令

```bash
# 查看所有服务状态
docker compose $(for p in infra gateway ai-capability network apps monitoring agents; do echo "--profile $p"; done) ps

# 重启原生服务
sudo systemctl restart llama-main hermes-gateway opensquilla chrome-cdp

# 重启某层 Docker 服务
cd TitanVault
sudo docker compose --env-file .env --profile infra --profile gateway --profile ai-capability \
    --profile network --profile apps --profile monitoring --profile agents restart

# 重装 (断点续接)
bash install.sh --resume 5    # 从 Phase 5 继续 (最快)
bash install.sh --resume 3    # 从 Phase 3 继续 (重新拉镜像)

# 重下模型 (换源后)
MODEL_SOURCE=hf DATA_DIR=/data bash scripts/download-models.sh
```

## 下一步

- [包含哪些服务](what-it-installs.md) — 完整服务清单
- [运维手册](operations.md) — 日常运维
- [自定义配置](customize.md) — 调整模型/端口/密码
- [故障排查](troubleshooting.md) — 常见问题
