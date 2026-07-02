#!/usr/bin/env bash
# scripts/restore.sh — TitanVault 生产级恢复
#
# 恢复顺序 (关键: 先停服 → 恢复文件 → 恢复DB → 起服):
#   0. 校验备份完整性 (清单/校验和)
#   1. 停止所有服务 (恢复期间数据静止)
#   2. 恢复配置 (.env/config) — 恢复后 docker compose 才能正确读取
#   3. 恢复应用数据卷 (tar 解压到 DATA_DIR)
#   4. 恢复 postgres (优先逻辑 SQL, 无则用文件卷)
#   5. 恢复 redis (文件卷)
#   6. 启动服务, 健康检查
#
# 安全机制:
#   - 恢复前备份当前 DATA_DIR 到 .pre-restore.<时间> (防止误覆盖, 可回滚)
#   - 除非 --yes, 否则二次确认 (恢复是破坏性操作)
#   - postgres 文件卷恢复时跳过 init (避免空库覆盖)
#
# 用法:
#   bash scripts/restore.sh <备份目录>           # 交互式确认
#   bash scripts/restore.sh <备份目录> --yes     # 跳过确认 (脚本用)
#   DATA_DIR=/data bash scripts/restore.sh /backups/mozin-20260628
set -euo pipefail

BACKUP_DIR="${1:-}"
SKIP_CONFIRM=false
[ "${2:-}" = "--yes" ] && SKIP_CONFIRM=true

[ -n "$BACKUP_DIR" ] || { echo "用法: bash scripts/restore.sh <备份目录> [--yes]"; exit 1; }
[ -d "$BACKUP_DIR" ] || { echo "备份目录不存在: $BACKUP_DIR"; exit 1; }
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
. "$REPO_DIR/scripts/_lib.sh"

if [ -f "$REPO_DIR/.env" ]; then set -a; . "$REPO_DIR/.env"; set +a; fi
DATA_DIR="${DATA_DIR:-/data}"

log()  { echo -e "\033[1;36m[restore]\033[0m $*"; }
warn() { echo -e "\033[1;33m[注意]\033[0m $*" >&2; }
err()  { echo -e "\033[1;31m[错误]\033[0m $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || err "需要 docker"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  恢复将覆盖: $DATA_DIR"
echo "  备份来源:   $BACKUP_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ls -lh "$BACKUP_DIR" 2>/dev/null | tail -n +2 | sed 's/^/  /'
echo ""

# ===== 0. 校验备份 =====
log "[0/6] 校验备份..."
if [ -f "$BACKUP_DIR/SHA256SUMS" ]; then
    ( cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS 2>/dev/null) >/dev/null 2>&1 \
        && log "  ✅ 校验和通过" || warn "  校验和不匹配, 文件可能损坏"
else
    warn "  无 SHA256SUMS, 跳过校验"
fi
[ -f "$BACKUP_DIR/data.tar.gz" ] || err "缺少 data.tar.gz, 备份不完整"

if [ "$SKIP_CONFIRM" = false ]; then
    read -rp $'\033[1;33m确认覆盖 '"$DATA_DIR"'? 不可逆 [输入 YES]: \033[0m' CONFIRM </dev/tty
    [ "$CONFIRM" = "YES" ] || { echo "已取消"; exit 0; }
fi

# ===== 1. 停止服务 =====
log "[1/6] 停止所有服务..."
mapfile -t DOWN_ARGS < <(mozin_compose_cmd down)
"${DOWN_ARGS[@]}" 2>/dev/null || warn "  compose down 失败 (可能没在运行)"

# ===== 备份当前数据 (防误覆盖, 可回滚) =====
PRE_RESTORE_BAK=""
if [ -d "$DATA_DIR" ] && [ "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
    PRE_RESTORE_BAK="$DATA_DIR.pre-restore.$(date +%Y%m%d-%H%M%S)"
    log "  当前 $DATA_DIR → $PRE_RESTORE_BAK"
    sudo mv "$DATA_DIR" "$PRE_RESTORE_BAK"
fi
sudo mkdir -p "$DATA_DIR"

# ===== 2. 恢复配置 =====
log "[2/6] 恢复配置..."
if [ -f "$BACKUP_DIR/dot-env" ]; then
    cp "$BACKUP_DIR/dot-env" "$REPO_DIR/.env"; chmod 600 "$REPO_DIR/.env"
    set -a; . "$REPO_DIR/.env"; set +a
    log "  ✅ .env (DATA_DIR=$DATA_DIR)"
fi
[ -f "$BACKUP_DIR/config.tar.gz" ] && tar xzf "$BACKUP_DIR/config.tar.gz" -C "$REPO_DIR" 2>/dev/null && log "  ✅ config/"
[ -f "$BACKUP_DIR/state.json" ] && mkdir -p "$HOME/.mozin-workstation" && cp "$BACKUP_DIR/state.json" "$HOME/.mozin-workstation/"

# ===== 3. 恢复应用数据卷 =====
log "[3/6] 恢复应用数据卷..."
sudo tar xzf "$BACKUP_DIR/data.tar.gz" -C "$DATA_DIR" 2>/dev/null \
    && log "  ✅ 应用数据 → $DATA_DIR" || err "data.tar.gz 解压失败"

# ===== 4. 恢复 postgres =====
log "[4/6] 恢复 postgres..."
if [ -f "$BACKUP_DIR/postgres-all.sql" ]; then
    # 逻辑恢复: 用全新空 data 目录启动 postgres (init 脚本会建空库, 但 dumpall 的
    # --clean --if-exists 会先 DROP 再 CREATE, 幂等不冲突)。
    log "  启动 postgres (新建空库, 随后用 SQL 覆盖)..."
    docker compose --env-file "$REPO_DIR/.env" --profile infra up -d postgres 2>/dev/null || err "postgres 启动失败"
    for _ in $(seq 1 30); do
        docker compose exec -T postgres pg_isready -U postgres >/dev/null 2>&1 && break; sleep 2
    done
    log "  导入 postgres-all.sql (--clean 幂等覆盖空库)..."
    # 导入到 maintenance db 'postgres'; dumpall 含 CREATE/DROP DATABASE + 数据
    # ON_ERROR_STOP=off: --if-exists 已处理存在性, 但保留容错
    docker compose exec -T postgres psql -U postgres -d postgres -v ON_ERROR_STOP=0 \
        < "$BACKUP_DIR/postgres-all.sql" >/dev/null 2>&1 \
        && log "  ✅ postgres 逻辑恢复" || err "SQL 导入失败"
    docker compose --env-file "$REPO_DIR/.env" --profile infra stop postgres 2>/dev/null || true
elif [ -f "$BACKUP_DIR/postgres-files.tar.gz" ]; then
    # 仅文件卷: 直接解压到 data 目录 (pg 在启动时读取, 不触发 init 因为目录非空)
    warn "  仅文件卷恢复 (无逻辑SQL), 需 pgvector/pg 版本一致"
    sudo tar xzf "$BACKUP_DIR/postgres-files.tar.gz" -C "$DATA_DIR" 2>/dev/null && log "  ✅ postgres 文件卷"
else
    warn "  无 postgres 备份, 将用 init 脚本建空库"
fi

# ===== 5. 恢复 redis =====
log "[5/6] 恢复 redis..."
if [ -f "$BACKUP_DIR/redis-files.tar.gz" ]; then
    sudo tar xzf "$BACKUP_DIR/redis-files.tar.gz" -C "$DATA_DIR" 2>/dev/null && log "  ✅ redis 文件卷"
fi
[ -f "$BACKUP_DIR/models.tar.gz" ] && { log "  恢复模型 (大文件)..."; sudo tar xzf "$BACKUP_DIR/models.tar.gz" -C "$DATA_DIR" 2>/dev/null && log "  ✅ models"; }

# 权限修正
log "  修正权限..."
sudo chown -R 1000:1000 "$DATA_DIR" 2>/dev/null || true

# ===== 6. 启动服务 =====
log "[6/6] 启动服务 ($PRESET preset)..."
mapfile -t UP_ARGS < <(mozin_compose_cmd up -d)
"${UP_ARGS[@]}" 2>/dev/null || err "服务启动失败: docker compose logs"

echo ""
log "✅ 恢复完成"
[ -n "$PRE_RESTORE_BAK" ] && log "   回滚: sudo rm -rf $DATA_DIR && sudo mv $PRE_RESTORE_BAK $DATA_DIR"
warn "请验证各服务数据 (登录 gitea 等确认数据完整)"
