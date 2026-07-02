# 网关与网络 (Caddy)

Caddy 是统一入口 (:80), 配置: `~/TitanVault/config/caddy/Caddyfile`

## 路由类型

1. **API 代理** (`handle_path`): 剥前缀反代到容器
   - `/llm/*` → litellm:4000 (注入 LITELLM_MASTER_KEY)
   - `/hermes/*` → host-gateway:8642 (注入 HERMES_API_SERVER_KEY)
   - `/glances/*` → host-gateway:61208
   - `/usage/*` → token-usage-api:8090

2. **UI 跳转** (`redir /go/xxx`): 直接跳端口, 因为子服务用绝对路径资源
   - `/go/litellm` → :4000/ui/
   - `/go/gitea` → :3002
   - 等等

3. **静态托管**: API 指南 `/api-guide/*`, TitanVault SPA 兜底

## 常见问题

### 502 Bad Gateway
```bash
# 后端服务没起来
docker ps | grep <service>

# Caddy 日志
docker logs $(docker ps -q --filter name=caddy) --tail 30

# 手动测后端
curl http://localhost:<port>/
```

### 修改 Caddyfile 后重载
```bash
# Caddy 支持热重载 (不重启)
docker exec $(docker ps -q --filter name=caddy) caddy reload --config /etc/caddy/Caddyfile

# 或重启容器
docker compose restart caddy
```

### host-gateway 不通
- `extra_hosts: host-gateway:host-gateway` 必须在 compose 里配置
- 用于反代宿主机原生服务 (llama.cpp 不在 Docker 里时)
