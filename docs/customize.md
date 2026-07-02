# 自定义

安装后如何调整 TitanVault。所有改动后用 `docker compose ... up -d` 生效。

## 切换 preset

preset 决定启用的服务层。编辑 `.env`:

```bash
PRESET=full   # 改成 minimal / standard / full
```

然后按新 preset 的 profile 启动 (preset 文件在 `presets/<preset>.env`, 列出哪些 `INCLUDE_*=true`):

```bash
# 例如切到 full, 启用全部 7 层
docker compose \
    --profile infra --profile gateway --profile ai-capability \
    --profile network --profile apps --profile monitoring --profile agents \
    up -d
```

或直接编辑 `presets/full.env` 的 `INCLUDE_*` 开关, 自定义组合。

## 改模型下载源

`.env` 里:

```bash
MODEL_SOURCE=modelscope   # 国内 (魔搭, 快)
MODEL_SOURCE=hf           # 全球 (HuggingFace)
```

改后重下模型:

```bash
MODEL_SOURCE=hf DATA_DIR=/data bash scripts/download-models.sh
```

`MODEL_SOURCE` 是全局变量, sensevoice / mineru / 下载脚本都读它, 一处控制全局。

## 换模型

主力 LLM 默认 Qwen3.6-35B-A3B (Q4_K_M)。换模型改两处:

1. `hardware/aimax-395.profile`:
   ```bash
   LLM_MODEL_NAME=你的模型名
   LLM_QUANT=量化方案
   ```
2. `models/models.yaml` 的 `llm` 段, 加上新模型的下载源。
3. 重下模型 + 重启:
   ```bash
   bash scripts/download-models.sh
   # 重新渲染 systemd (用新模型名) 并重启
   source .env && source hardware/aimax-395.profile
   envsubst < native/llama.cpp/llama-main.service.tpl | sudo tee /etc/systemd/system/llama-main.service
   sudo systemctl daemon-reload && sudo systemctl restart llama-main
   # litellm config 也要重渲染 (模型名变了)
   envsubst < config/litellm/config.yaml.tpl > config/litellm/config.yaml
   docker compose --profile gateway restart litellm
   ```

## 加自定义服务

在 `compose/` 新建 `.yml`, 加 `profiles:` 标记:

```yaml
# compose/my-app.yml
services:
  my-app:
    image: my-app:latest
    profiles: [apps]          # 挂到现有 profile, 或新建一个
    restart: unless-stopped
    networks: [mozin]
networks:
  mozin:
    driver: bridge
```

然后 `docker compose -f compose/my-app.yml --profile apps up -d`。

要让它进 preset 自动启用, 把对应 profile 加进 `presets/<preset>.env`。

## 改 Caddy 路由

编辑 `config/caddy/Caddyfile` (install.sh 已从 `.tpl` 渲染), 加 location 块:

```
handle_path /myapp/* {
    reverse_proxy 127.0.0.1:你的端口
}
```

`docker compose --profile gateway restart caddy` 生效。

## 配置代理 / 内网穿透

`.env` 填订阅/凭证后重新渲染:

```bash
# mihomo 订阅
MIHOMO_SUBSCRIBE_URL=https://你的订阅链接
# frp 穿透
FRP_SERVER_ADDR=your.frp.server
FRP_TOKEN=your-token

# 重新渲染配置
source .env
envsubst < config/mihomo/config.yaml.tpl > config/mihomo/config.yaml
envsubst < config/frp/frpc.toml.tpl > config/frp/frpc.toml
docker compose --profile network restart
```

留空 = 直连模式 (mihomo 走 DIRECT, frp 不连接), 不影响其它服务。

## 数据备份与恢复

**用专用脚本, 不要手动 tar** (数据库需要一致性保证):

```bash
# 备份 (在线热备, postgres 用 pg_dumpall 保证事务一致)
bash scripts/backup.sh

# 停服后绝对一致备份 (最稳)
bash scripts/backup.sh --stop

# 恢复 (交互确认, 自动回滚保护)
bash scripts/restore.sh backups/mozin-<时间戳>
```

详见 [架构审计文档](architecture-audit.md#备份与恢复) 的备份章节。
**务必定期验证备份可恢复** (测试机跑 restore.sh)。
