# 服务管理 (Docker 容器 + 原生 systemd)

本工作站混合部署: llama.cpp 和 Hermes 是原生 systemd 服务, 其余是 Docker 容器。

## 原生 systemd 服务 (llama.cpp + Hermes)

```bash
# 查看 Hermes 服务状态
systemctl status hermes-dashboard
systemctl status hermes-gateway

# 重启 Hermes
sudo systemctl restart hermes-dashboard hermes-gateway

# 查看日志 (实时)
journalctl -u hermes-gateway -f --tail 50
journalctl -u hermes-dashboard -f --tail 50

# 查看 llama.cpp 服务
systemctl status llama-main llama-embed llama-rerank
sudo systemctl restart llama-main
journalctl -u llama-main -f
```

## Docker 容器服务

```bash
cd ~/TitanVault

# 查看所有容器服务状态
docker compose --profile gateway --profile agents ps

# 启动某 profile 的服务
docker compose --profile gateway up -d

# 重启单个容器服务
docker compose restart titanvault
docker compose restart litellm
docker compose restart hindsight

# 查看日志 (实时跟踪)
docker compose logs -f titanvault --tail 50
docker compose logs -f hindsight --tail 100

# 进入容器
docker compose exec caddy sh
docker compose exec litellm sh

# 重新构建镜像 (改了源码后)
docker compose build titanvault
docker compose up -d titanvault --force-recreate
```

## 常见问题

### 服务无法启动
```bash
# 1. 查看具体错误
docker compose logs <service> --tail 50

# 2. 检查端口冲突
docker ps --format '{{.Names}} {{.Ports}}' | grep <port>

# 3. 检查 .env 变量是否齐全
grep -c '=' ~/TitanVault/.env
```

### 容器不断重启 (restart loop)
```bash
# 查看重启原因
docker inspect <container> | grep -A5 RestartCount
docker logs <container> --tail 20

# 常见原因: 配置错误、依赖服务未就绪、端口冲突
```

### 磁盘空间不足
```bash
# 查看 Docker 占用
docker system df

# 清理无用的镜像/容器/卷 (谨慎!)
docker system prune -a --volumes

# 查看日志文件大小
du -sh ~/TitanVault/data/*/  | sort -rh | head
```
