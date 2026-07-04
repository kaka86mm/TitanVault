# TitanVault 故障分诊表 (Triage)

> Hermes 排障时的"症状 → 可能原因 → 修复"快速查询表。
> 修复标记: 🔧=低风险可执行(ops.sh heal) | ⚠️=需理由重启 | 🚫=升级人工(改配置/更新)

## 健康检查项 → 故障对照

| health-check 异常 | 最可能原因 | 修复 |
|---|---|---|
| `containers-restart: critical` | 容器启动失败 (缺env/依赖未起/配置错) | 看日志定具体原因 (下方) |
| `containers-exited: warn` | 容器正常退出或崩溃 | 🔧 `ops.sh heal` 重启; 持续退出看日志 |
| `llama-main: critical (8082无响应)` | systemd 服务挂 / GPU 驱动问题 | ⚠️ `systemctl status llama-main` 后重启 |
| `caddy: warn (80不可达)` | caddy 容器未起 / 端口被占 | 🔧 heal; `ss -tlnp \| grep :80` 查占用 |
| `litellm: warn` | litellm 未起 / 连不上 postgres | 看 `docker logs litellm` |
| `disk: critical (≥95%)` | 日志/镜像/备份堆积 | 🔧 `ops.sh cleanup`; 仍满→升级人工查大文件 |
| `memory: warn` | 35B模型+多服务吃满 | 报告; 考虑减 preset 或加内存 |

## 容器重启循环 — 按服务定位

### dify-api / dify-worker 循环重启
```
docker logs dify-api 2>&1 | tail -30
```
常见原因:
- `POSTGRES_PASSWORD must be set` → 🚫 `.env` 缺密码 (升级: 提议补 .env)
- `connection refused postgres:5432` → postgres 没起 → 🔧 先 heal postgres
- `QDRANT_API_KEY` / `SECRET_KEY` 缺 → 🚫 env 缺失
- 数据库不存在 (`dify`/`dify_plugin` 库) → init 脚本没跑 (新库首次); 🚫 手动 CREATE

### dify-plugin_daemon 循环
- `DB_DATABASE: dify_plugin` 库不存在 → 🚫 init 脚本建库 (检查 POSTGRES_MULTIPLE_DATABASES)
- `SERVER_KEY` 不匹配 → 🚫 api 的 INNER_API_KEY_FOR_PLUGIN 要一致

### postgres 循环 / 起不来
- `data directory has wrong ownership` → 权限: `sudo chown -R 999:999 $DATA_DIR/postgres`
- `database files are incompatible` → 🚫 pg 版本变了 (pgvector/pg17), 需 pg_upgrade 或从备份恢复
- 磁盘满 → 🔧 cleanup

### redis 循环
- `Bad file format` → dump.rdb 损坏 → 停 redis, 删 `$DATA_DIR/redis/dump.rdb`, 重启 (丢内存数据)

### litellm 循环
- `database_url` 连不上 postgres → 先 heal postgres
- `config.yaml` 解析失败 → 🚫 渲染错误 (检查 envsubst 输出)

### qdrant 循环
- `API key mismatch` → 🚫 QDRANT__SERVICE__API_KEY 与 dify 的 QDRANT_API_KEY 不一致

## llama.cpp (原生) 问题

### 8082 无响应
```bash
sudo systemctl status llama-main
sudo journalctl -u llama-main --since "1 hour ago" | tail -40
```
- `inactive (dead)` → ⚠️ `sudo systemctl start llama-main`
- `failed` 看日志:
  - `failed to load model` → 模型路径错/文件缺 → 🚫 检查 `download-models.sh` 是否下完
  - `no Vulkan devices` → GPU 驱动问题 → 🚫 见 docs/troubleshooting.md GPU 段
  - `out of memory` → 内存/显存不足 → 报告, 考虑减小 `-c` 上下文或换小模型

### 推理极慢 (没走 GPU)
```bash
sudo journalctl -u llama-main | grep -i vulkan
# 应见 "ggml_vulkan: Found 1 Vulkan devices" 且 offload 层数 = -ngl
```
没走 GPU → 🚫 Vulkan 驱动/`GGML_VULKAN_DEVICE` 问题

## 网络 / 连通问题 (395 多子网)

### 服务间连不上 (bridge DNS)
- 检查双方都在 `mozin` 网络: `docker network inspect mozin | grep Name`
- caddy 反代目标用服务名 (`litellm:4000`), 不是 `127.0.0.1` (caddy 在 bridge)

### litellm 连不上 llama.cpp (host-gateway)
- llama.cpp 监听 `0.0.0.0:8082`?
- litellm 有 `extra_hosts: host-gateway`?
- 宿主防火墙挡 docker 网段? `sudo iptables -L -n | grep 172`

### mihomo 订阅后 docker 异常
- mihomo 的 tun 模式可能劫持 docker 流量 → 🚫 mihomo config 改 redir 而非 tun, 或排除 docker 网段

## 磁盘 / 资源

### 磁盘满
```bash
ops.sh cleanup                    # 🔧 清悬空镜像+旧备份
du -sh $DATA_DIR/* | sort -h      # 找最大目录
docker system df                  # docker 占用
```
常见元凶: postgres WAL 暴涨 / 日志没限制 (检查 logging 配置) / 备份堆积

### 内存不足 (OOM)
```bash
dmesg | grep -i "out of memory"   # 查 OOM kill 记录
```
35B 模型 + full preset 内存吃紧 → 报告, 建议降 preset 或加内存

## 升级人工 (🚫) 的标准格式

发现需升级的问题时, 报告:
```
问题: <一句话>
证据: <日志行/状态>
建议修复: <确切命令或 .env 改动>
风险: <影响什么>
```
不要直接执行, 等人工确认。
