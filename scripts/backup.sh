#!/usr/bin/env bash
# scripts/backup.sh — TitanVault 生产级备份
#
# 设计原则: 数据在三类地方, 分别用正确方式备份:
#   1. 数据库 (postgres/redis) — 用专用逻辑备份工具 (pg_dumpall/redis SAVE), 保证事务一致
#   2. 应用数据/文件卷 (gitea/qdrant/...) — tar 打包 DATA_DIR
#   3. 配置 (.env/config/state.json) — 直接拷贝
#
# 模型文件 (models/ ~几十GB) 默认排除 (可重下), 用 --include-models 单独全量备。
#
# 用法:
#   bash scripts/backup.sh                        # 在线热备份 → backups/
#   bash scripts/backup.sh --stop                 # 停服后备份 (绝对一致, 推荐)
#   bash scripts/backup.sh /mnt/usb/bak           # 备份到指定目录
#   bash scripts/backup.sh --include-models       # 连模型一起备 (大)
#   bash scripts/backup.sh --stop /mnt/usb/bak
set -euo pipefail

# ===== 解析参数 (flag 和路径混合) =====
STOP=false
INCLUDE_MODELS=false
BACKUP_TARGET=""
for arg in "$@"; do
    case "$arg" in
        --stop) STOP=true ;;
        --include-models) INCLUDE_MODELS=true ;;
        --help|-h) sed -n '2,20p' "$0"; exit 0 ;;
        *) BACKUP_TARGET="$arg" ;;
    esac
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
. "$REPO_DIR/scripts/_lib.sh"   # mozin_compose_cmd 等

# 从 .env 读配置 (若存在)
if [ -f "$REPO_DIR/.env" ]; then set -a; . "$REPO_DIR/.env"; set +a; fi

DATA_DIR="${DATA_DIR:-/data}"
BACKUP_DIR="${BACKUP_DIR:-$REPO_DIR/backups}"
[ -n "$BACKUP_TARGET" ] && BACKUP_DIR="$BACKUP_TARGET"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_PATH="${BACKUP_DIR}/mozin-${TIMESTAMP}"

log()  { echo -e "\033[1;32m[backup]\033[0m $*"; }
warn() { echo -e "\033[1;33m[注意]\033[0m $*" >&2; }
err()  { echo -e "\033[1;31m[错误]\033[0m $*" >&2; exit 1; }

[ -d "$DATA_DIR" ] || err "数据目录不存在: $DATA_DIR"
command -v docker >/dev/null 2>&1 || err "需要 docker"
mkdir -p "$BACKUP_PATH"

# compose 是否在运行 (决定能否用容器内工具做逻辑备份)
COMPOSE_UP=false
docker compose ps --format '{{.Name}}' 2>/dev/null | grep -q . && COMPOSE_UP=true

log "备份 → $BACKUP_PATH"
log "数据源: $DATA_DIR | 停服: $STOP | 含模型: $INCLUDE_MODELS | 服务运行: $COMPOSE_UP"
echo ""

# ===== 可选: 停服 (文件卷绝对一致) =====
if [ "$STOP" = true ] && [ "$COMPOSE_UP" = true ]; then
    log "停止服务 (保证文件卷一致性)..."
    # 用 mapfile 读 compose 命令参数 (避开命令替换 word-splitting 警告)
    mapfile -t STOP_ARGS < <(mozin_compose_cmd stop)
    "${STOP_ARGS[@]}" 2>/dev/null || true
    log "服务已停止"
fi

# ===== 1. postgres 逻辑备份 (必须在线时做, 停服前/未停服时) =====
log "[1/4] postgres 逻辑备份 (pg_dumpall, 事务一致)..."
PGSQL="$BACKUP_PATH/postgres-all.sql"
if [ "$STOP" = false ] && [ "$COMPOSE_UP" = true ] && docker compose ps postgres 2>/dev/null | grep -q "Up\|running"; then
    # 在线备份: pg_dumpall --clean --if-exists 输出含 DROP, 恢复时幂等 (可覆盖已有库)
    docker compose exec -T postgres pg_dumpall -U postgres --clean --if-exists > "$PGSQL" 2>/dev/null \
        || err "pg_dumpall 失败"
    [ -s "$PGSQL" ] || err "postgres 备份为空 (pg_dumpall 异常)"
    log "  ✅ postgres-all.sql ($(du -h "$PGSQL" | cut -f1), 含DROP可幂等恢复)"
elif [ "$STOP" = true ] && [ "$COMPOSE_UP" = true ]; then
    # 停服模式下: 应该在停服前先 dump。这里若已停, 文件卷 tar 会兜底 (但不如逻辑备份可移植)
    warn "已停服, postgres 用文件卷备份 (恢复时需同版本 pgvector 镜像); 如需可移植 SQL, 用 --stop 前先在线 dump"
elif [ -d "$DATA_DIR/postgres" ] && [ "$COMPOSE_UP" = false ]; then
    warn "postgres 容器未运行, 仅文件卷备份 (无逻辑 SQL); 启服后 pg_dumpall 更可靠"
else
    log "  跳过 postgres"
fi

# ===== 2. redis 落盘 (在线时触发 BGSAVE 保证内存数据) =====
log "[2/4] redis 数据落盘..."
if [ "$STOP" = false ] && [ "$COMPOSE_UP" = true ] && docker compose ps redis 2>/dev/null | grep -q "Up\|running"; then
    log "  触发 BGSAVE, 等待落盘完成..."
    docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD:-}" --no-auth-warning BGSAVE >/dev/null 2>&1 || true
    # 轮询 LASTSAVE 时间戳停止增长 = 落盘完成
    prev_ts=0
    for _ in $(seq 1 30); do
        new_ts=$(docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD:-}" --no-auth-warning LASTSAVE 2>/dev/null | tr -dc '0-9')
        [ "${new_ts:-0}" = "$prev_ts" ] && [ "$prev_ts" != "0" ] && break
        prev_ts="${new_ts:-0}"; sleep 1
    done
    log "  ✅ redis 已落盘"
else
    warn "redis 未运行或已停服, 使用现有 dump.rdb (可能非最新内存数据)"
fi

# ===== 3. 应用数据卷 tar (排除模型/postgres/redis目录) =====
log "[3/4] 应用数据卷打包..."
TAR_FILE="$BACKUP_PATH/data.tar.gz"
# 排除: models (大, 可重下), postgres/redis (已用专用方式, 避免重复+热不一致)
# ⚠ GNU tar 的 --exclude='./redis' 会匹配任意层级的 'redis' 路径组件 (不仅是顶层),
#    故 mineru-web 的 redis 数据卷特意命名为 task-queue (而非 redis) 避免被误排。
EXCLUDES=(--exclude='./models' --exclude='./postgres' --exclude='./redis')
[ "$INCLUDE_MODELS" = false ] && EXCLUDES+=("--exclude='./models')")
log "  打包 $DATA_DIR (排除 models/postgres/redis)..."
tar czf "$TAR_FILE" -C "$DATA_DIR" "${EXCLUDES[@]}" . 2>/dev/null || err "tar 打包失败"
log "  ✅ data.tar.gz ($(du -h "$TAR_FILE" | cut -f1))"

# postgres/redis 文件单独打包 (停服时绝对一致; 在线时作文件卷兜底)
if [ -d "$DATA_DIR/postgres" ]; then
    tar czf "$BACKUP_PATH/postgres-files.tar.gz" -C "$DATA_DIR" postgres 2>/dev/null && \
        log "  ✅ postgres-files.tar.gz ($(du -h "$BACKUP_PATH/postgres-files.tar.gz" | cut -f1))"
fi
if [ -d "$DATA_DIR/redis" ]; then
    tar czf "$BACKUP_PATH/redis-files.tar.gz" -C "$DATA_DIR" redis 2>/dev/null && \
        log "  ✅ redis-files.tar.gz ($(du -h "$BACKUP_PATH/redis-files.tar.gz" | cut -f1))"
fi

# 模型单独打包 (可选, 大)
if [ "$INCLUDE_MODELS" = true ] && [ -d "$DATA_DIR/models" ]; then
    log "  打包模型 (大文件, 耗时)..."
    tar czf "$BACKUP_PATH/models.tar.gz" -C "$DATA_DIR" models 2>/dev/null && \
        log "  ✅ models.tar.gz ($(du -h "$BACKUP_PATH/models.tar.gz" | cut -f1))"
fi

# ===== 4. 配置备份 =====
log "[4/4] 配置备份..."
[ -f "$REPO_DIR/.env" ] && cp "$REPO_DIR/.env" "$BACKUP_PATH/dot-env"
[ -d "$REPO_DIR/config" ] && tar czf "$BACKUP_PATH/config.tar.gz" -C "$REPO_DIR" config 2>/dev/null
[ -f "$HOME/.mozin-workstation/state.json" ] && cp "$HOME/.mozin-workstation/state.json" "$BACKUP_PATH/state.json" 2>/dev/null || true
log "  ✅ .env + config/ + state.json"

# ===== 恢复服务 =====
if [ "$STOP" = true ] && [ "$COMPOSE_UP" = true ]; then
    log "恢复服务运行..."
    mapfile -t START_ARGS < <(mozin_compose_cmd start)
    "${START_ARGS[@]}" 2>/dev/null || true
fi

# ===== 清单 + 校验和 =====
cat > "$BACKUP_PATH/MANIFEST.txt" <<EOF
TitanVault 备份
时间: $(date -Iseconds)
数据目录: $DATA_DIR
停服模式: $STOP  含模型: $INCLUDE_MODELS
来源: $REPO_DIR

内容:
$(ls -1 "$BACKUP_PATH" | sed 's/^/  - /')

恢复: bash scripts/restore.sh $BACKUP_PATH
EOF
( cd "$BACKUP_PATH" && (sha256sum * 2>/dev/null || shasum -a 256 *) > SHA256SUMS 2>/dev/null ) || true

TOTAL=$(du -sh "$BACKUP_PATH" | cut -f1)
echo ""
log "✅ 备份完成: $BACKUP_PATH ($TOTAL)"
log "   清单: MANIFEST.txt | 校验: SHA256SUMS"
log "   恢复: bash scripts/restore.sh $BACKUP_PATH"
warn "建议定期验证恢复 (测试机跑 restore.sh), 未验证的备份等于没备份"
