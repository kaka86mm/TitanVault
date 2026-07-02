#!/usr/bin/env bash
# scripts/setup-kuma.sh — uptime-kuma 自动初始化 (创建 admin + 灌入发行版服务监控)
#
# kuma 首次启动数据库是空的, 需通过 UI 手动 setup。本脚本直接 sqlite3 操作,
# 创建 admin 用户 + 灌入 18 个服务监控, 开箱即用。
# 幂等: 用户/监控已存在则跳过。
set -euo pipefail

CONTAINER="${KUMA_CONTAINER:-mozin-workstation-uptime-kuma-1}"
DB="/app/data/kuma.db"
KUMA_USER="${KUMA_USER:-admin}"
KUMA_PASS="${KUMA_PASS:-titanvault2026}"

log() { echo -e "\033[1;32m[kuma]\033[0m $*"; }

# 等 kuma 容器就绪 (数据库表已建)
log "等待 kuma 就绪..."
for _ in $(seq 1 30); do
    if docker exec "$CONTAINER" sqlite3 "$DB" "SELECT count(*) FROM user;" >/dev/null 2>&1; then break; fi
    sleep 5
done
docker exec "$CONTAINER" sqlite3 "$DB" "SELECT count(*) FROM user;" >/dev/null 2>&1 \
    || { echo "[kuma] kuma 数据库未就绪, 跳过初始化"; exit 0; }

# 1. 创建 admin 用户 (如果还没有)
USER_COUNT=$(docker exec "$CONTAINER" sqlite3 "$DB" "SELECT count(*) FROM user;" 2>/dev/null)
if [ "$USER_COUNT" = "0" ]; then
    log "创建 admin 用户..."
    # bcrypt hash (用容器内的 node 或 python 生成)
    HASH=$(python3 -c "import bcrypt; print(bcrypt.hashpw(b'$KUMA_PASS', bcrypt.gensalt(10)).decode())" 2>/dev/null \
        || docker exec "$CONTAINER" node -e "const b=require('bcryptjs'); console.log(b.hashSync('$KUMA_PASS',10))" 2>/dev/null \
        || echo '$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy')
    docker exec "$CONTAINER" sqlite3 "$DB" \
        "INSERT INTO user (username, password, active) VALUES ('$KUMA_USER', '$HASH', 1);" 2>/dev/null
    log "  ✅ admin 用户创建 (密码: $KUMA_PASS)"
else
    log "admin 用户已存在, 跳过"
fi

# 2. 灌入服务监控 (幂等)
log "灌入服务监控..."
MONITORS="
llama-main|http://127.0.0.1:8082/v1/models
llama-embed|http://127.0.0.1:8084/v1/models
llama-rerank|http://127.0.0.1:8083/v1/models
litellm|http://127.0.0.1:4000/health/liveness
titanvault|http://127.0.0.1:80/
hindsight|http://127.0.0.1:8888/health
gitea|http://127.0.0.1:3002/
open-notebook|http://127.0.0.1:8088/
sensevoice|http://127.0.0.1:9991/docs
kokoro-tts|http://127.0.0.1:8081/docs
comfyui|http://127.0.0.1:8188/
mineru-api|http://127.0.0.1:18080/docs
aham-voice|http://127.0.0.1:8765/
hermes-dash|http://127.0.0.1:9119/
hermes-gw|http://127.0.0.1:8642/health
opensquilla|http://127.0.0.1:18791/control/
chrome-cdp|http://127.0.0.1:9222/json/version
caddy|http://127.0.0.1/api-guide/
"

ADDED=0
while IFS='|' read -r name url; do
    [ -z "$name" ] && continue
    EXISTS=$(docker exec "$CONTAINER" sqlite3 "$DB" "SELECT count(*) FROM monitor WHERE name='$name';" 2>/dev/null)
    if [ "$EXISTS" = "0" ]; then
        docker exec "$CONTAINER" sqlite3 "$DB" \
            "INSERT INTO monitor (name, type, url, interval, retry_interval, maxretries, active, accepted_statuscodes_json, user_id) VALUES ('$name', 'http', '$url', 60, 60, 2, 1, '[\"200-299\",\"301\",\"302\",\"307\",\"308\"]', 1);" 2>/dev/null
        ADDED=$((ADDED+1))
    fi
done <<< "$MONITORS"

TOTAL=$(docker exec "$CONTAINER" sqlite3 "$DB" "SELECT count(*) FROM monitor;" 2>/dev/null)
log "✅ 监控灌入完成 (新增 $ADDED, 总计 $TOTAL)"

# 重启 kuma 让它加载新监控
[ "$ADDED" -gt 0 ] 2>/dev/null && docker restart "$CONTAINER" >/dev/null 2>&1 && log "  kuma 已重启加载监控"
