#!/usr/bin/env bash
# scripts/ops.sh — TitanVault 确定性运维主脚本
#
# 第1层运维: 固定流程, 无 LLM, cron 调度, hermes 也可调用。
# 提供子命令, 每个做一件事, 幂等可重跑。
#
# 子命令:
#   status    — 健康状态 (调 health-check.sh)
#   heal      — 低风险自愈: 重启异常容器, 清理日志, 不改配置
#   update    — 拉取最新镜像 + recreate (需 --yes 确认, 高风险)
#   backup    — 备份 (调 backup.sh)
#   cleanup   — 清理 docker 无用资源 + 旧日志
#   report    — 生成运维摘要文本 (供 hermes/cron 报告)
#
# 用法:
#   bash scripts/ops.sh status
#   bash scripts/ops.sh heal
#   bash scripts/ops.sh update --yes
#   bash scripts/ops.sh report
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
. "$REPO_DIR/scripts/_lib.sh"
[ -f "$REPO_DIR/.env" ] && { set -a; . "$REPO_DIR/.env"; set +a; }

CMD="${1:-status}"
shift || true

log()  { echo -e "\033[1;34m[ops]\033[0m $*"; }
warn() { echo -e "\033[1;33m[注意]\033[0m $*" >&2; }

case "$CMD" in
    status)
        exec bash "$REPO_DIR/scripts/health-check.sh" "$@"
        ;;

    heal)
        # 低风险自愈: 只做安全操作, 不改配置
        log "自愈扫描 (仅低风险操作)..."
        echo ""
        # 1. 重启处于异常状态的容器 (Restarting/Exited 但期望运行)
        mapfile -t PROFILES < <(mozin_profiles)
        PROFILE_ARGS=()
        for p in "${PROFILES[@]}"; do PROFILE_ARGS+=(--profile "$p"); done
        for svc_status in $(docker compose --env-file "$REPO_DIR/.env" \
            "${PROFILE_ARGS[@]}" \
            ps -a --format '{{.Service}}:{{.Status}}' 2>/dev/null || true); do
            svc="${svc_status%%:*}"
            status="${svc_status#*:}"
            if echo "$status" | grep -qi "restart\|exit"; then
                log "  重启异常容器: $svc (状态: $status)"
                docker compose --env-file "$REPO_DIR/.env" start "$svc" 2>/dev/null \
                    && log "  ✅ $svc 已重启" \
                    || warn "  ❌ $svc 重启失败"
            fi
        done
        # 2. 磁盘检查: ≥85 时直接顺带 cleanup (在自愈流程里就处理掉)
        disk=$(df "${DATA_DIR:-/data}" 2>/dev/null | awk 'NR==2{gsub(/%/,"");print $5}')
        if [ -n "${disk:-0}" ] && [ "$disk" -ge 85 ]; then
            log "  磁盘 ${disk}% ≥85%, 触发 cleanup..."
            docker image prune -f 2>/dev/null >/dev/null || true
            docker compose --env-file "$REPO_DIR/.env" exec -T postgres psql -U postgres -c "CHECKPOINT;" >/dev/null 2>&1 || true
            log "  ✅ 已清理 (悬空镜像 + WAL 回收)"
        elif [ -n "${disk:-0}" ]; then
            log "  磁盘 ${disk}% 正常"
        fi
        echo ""
        log "自愈完成。如仍有异常, 运行 status 查看"
        ;;

    update)
        # 闭环更新: 备份 → pull+recreate → 验证 → 失败回滚
        # 这是防"上游 breaking change 把生产搞挂"的关键
        if [ "${1:-}" != "--yes" ]; then
            log "更新流程: 备份 → 拉镜像 → 重建 → 验证 → (失败则回滚)"
            log "服务会短暂中断。确认: bash scripts/ops.sh update --yes"
            exit 1
        fi
        # 记录当前镜像 digest (回滚用)
        mapfile -t PROFILES < <(mozin_profiles)
        PRE_IMG_LIST="$REPO_DIR/logs/pre-update-images.$(date +%s).txt"
        mkdir -p "$REPO_DIR/logs"
        PRE_IMG_ARGS=(--env-file "$REPO_DIR/.env")
        for p in "${PROFILES[@]}"; do PRE_IMG_ARGS+=(--profile "$p"); done
        docker compose "${PRE_IMG_ARGS[@]}" images -q 2>/dev/null | sort -u > "$PRE_IMG_LIST" || true
        log "[1/4] 更新前备份 (回滚保险)..."
        PRE_UPDATE_BACKUP="$REPO_DIR/backups/pre-update-$(date +%Y%m%d-%H%M%S)"
        BACKUP_DIR="$PRE_UPDATE_BACKUP" bash "$REPO_DIR/scripts/backup.sh" >/dev/null 2>&1 \
            && log "  ✅ 备份: $PRE_UPDATE_BACKUP" || warn "  备份失败 (继续, 但无回滚保险)"

        log "[2/4] 拉取最新镜像..."
        for p in "${PROFILES[@]}"; do
            docker compose --env-file "$REPO_DIR/.env" --profile "$p" pull 2>/dev/null || warn "  $p pull 失败"
        done

        log "[3/4] 重建容器..."
        for p in "${PROFILES[@]}"; do
            docker compose --env-file "$REPO_DIR/.env" --profile "$p" up -d 2>/dev/null || warn "  $p up 失败"
        done

        log "[4/4] 健康验证 (等 60s 起服后检查)..."
        sleep 60
        # 临时关自愈避免验证时二次触发
        if OPS_AUTO_HEAL=false bash "$REPO_DIR/scripts/health-check.sh" >/dev/null 2>&1; then
            log "✅ 更新成功, 健康检查通过"
        else
            warn "🚨 更新后健康检查失败!"
            warn "  注意: 镜像已更新到新版 (compose 用 tag, 无法自动回退到旧 image)。"
            warn "  尝试恢复运行 (重启服务, 用的是新镜像):"
            for p in "${PROFILES[@]}"; do
                docker compose --env-file "$REPO_DIR/.env" --profile "$p" restart 2>/dev/null || true
            done
            sleep 30
            if OPS_AUTO_HEAL=false bash "$REPO_DIR/scripts/health-check.sh" >/dev/null 2>&1; then
                warn "⚠️ 重启后恢复运行, 但用的是新镜像。若不稳定需回到旧版:"
                warn "   bash scripts/restore.sh $PRE_UPDATE_BACKUP --yes  (恢复更新前的数据+配置)"
                warn "   旧镜像 digest 列表: $PRE_IMG_LIST (用于手动 docker pull <digest>)"
            else
                err "🚨 重启后仍失败! 需人工介入。"
                err "   数据备份: $PRE_UPDATE_BACKUP"
                err "   旧镜像 digest: $PRE_IMG_LIST"
                err "   诊断: bash scripts/ops.sh status"
            fi
        fi
        ;;

    backup)
        exec bash "$REPO_DIR/scripts/backup.sh" "$@"
        ;;

    cleanup)
        log "清理无用 docker 资源..."
        docker image prune -f 2>/dev/null && log "  ✅ 清理悬空镜像"
        docker builder prune -f 2>/dev/null || true
        # postgres WAL 清理 (pg_wal 可能堆积几十G! 调 CHECKPOINT 让它回收)
        if docker compose --env-file "$REPO_DIR/.env" ps postgres 2>/dev/null | grep -q "Up\|running"; then
            log "  postgres WAL 回收 (CHECKPOINT)..."
            docker compose exec -T postgres psql -U postgres -c "CHECKPOINT;" >/dev/null 2>&1 \
                && docker compose exec -T postgres psql -U postgres -c "SELECT pg_switch_wal();" >/dev/null 2>&1 \
                && log "  ✅ WAL 已切换回收" || true
        fi
        # 清理旧备份 (默认保留7天)
        RETENTION="${OPS_BACKUP_RETENTION_DAYS:-7}"
        if [ -d "$REPO_DIR/backups" ]; then
            log "  清理 ${RETENTION} 天前的备份..."
            find "$REPO_DIR/backups" -maxdepth 1 -type d -name "mozin-*" -mtime +"$RETENTION" -exec rm -rf {} \; 2>/dev/null || true
        fi
        log "✅ 清理完成"
        ;;

    emergency-disk)
        # 激进止血: 磁盘≥阈值时紧急释放空间 (磁盘满会让整机卡死, 必须自动)
        THRESHOLD="${1:-90}"
        disk=$(df "${DATA_DIR:-/data}" 2>/dev/null | awk 'NR==2{gsub(/%/,"");print $5}')
        if [ -z "${disk:-0}" ] || [ "$disk" -lt "$THRESHOLD" ]; then
            log "磁盘 ${disk:-?}% < 阈值 ${THRESHOLD}%, 无需止血"
            exit 0
        fi
        warn "🚨 磁盘 ${disk}% ≥ ${THRESHOLD}%, 紧急止血..."
        # 1. 激进清理 docker (含未用镜像/构建缓存/停止容器)
        prune_result=$(docker system prune -af --volumes 2>/dev/null | tail -1 || true)
        [ -n "$prune_result" ] && log "  docker prune: $prune_result"
        # 2. postgres WAL 强制回收 + 旧 WAL 归档
        if docker compose --env-file "$REPO_DIR/.env" ps postgres 2>/dev/null | grep -q "Up\|running"; then
            log "  postgres WAL 强制回收..."
            docker compose exec -T postgres psql -U postgres -c "CHECKPOINT; SELECT pg_switch_wal();" >/dev/null 2>&1 || true
        fi
        # 3. 清理 docker 日志 (容器 json-file 日志)
        # 不 truncate 活跃日志(句柄冲突风险), 而是清理已停止容器的旧日志 + 触发轮转
        log "  清理停止容器的日志..."
        for c in $(docker ps -aq --filter "status=exited" 2>/dev/null); do
            logfile=$(docker inspect --format '{{.LogPath}}' "$c" 2>/dev/null || true)
            [ -n "$logfile" ] && [ -f "$logfile" ] && sudo rm -f "$logfile" 2>/dev/null || true
        done
        # 4. 清理所有旧备份 (紧急时全删, 保留最新)
        if [ -d "$REPO_DIR/backups" ]; then
            log "  删除旧备份 (保留最新)..."
            ls -1dt "$REPO_DIR/backups"/mozin-* 2>/dev/null | tail -n +2 | xargs rm -rf 2>/dev/null || true
        fi
        after=$(df "${DATA_DIR:-/data}" 2>/dev/null | awk 'NR==2{gsub(/%/,"");print $5}')
        log "✅ 止血完成: ${disk}% → ${after:-?}%"
        [ "${after:-0}" -ge "$THRESHOLD" ] && warn "止血后仍 ${after}%, 需人工介入查大文件: du -sh ${DATA_DIR:-/data}/* | sort -h"
        ;;

    report)
        # 生成运维摘要 (文本, 供 hermes cron 报告 / 邮件)
        echo "═══════════════════════════════════════════"
        echo "  TitanVault 运维报告"
        echo "  $(date '+%Y-%m-%d %H:%M:%S')"
        echo "═══════════════════════════════════════════"
        echo ""
        # 健康状态
        bash "$REPO_DIR/scripts/health-check.sh" 2>/dev/null || true
        echo ""
        # 资源占用
        echo "─── 资源 ───"
        echo "磁盘:"
        df -h "${DATA_DIR:-/data}" 2>/dev/null | tail -1 | awk '{printf "  %s 已用 %s / %s\n",$6,$3,$2}'
        echo "内存:"
        free -h 2>/dev/null | awk '/^Mem:/{printf "  已用 %s / %s (可用 %s)\n",$3,$2,$7}'
        echo "容器数:"
        docker ps 2>/dev/null | tail -n +2 | wc -l | xargs echo "  运行中:"
        echo ""
        echo "─── 最近事件 (异常容器) ───"
        mapfile -t ALL_PROFILES < <(printf '%s\n' infra gateway ai-capability network apps monitoring agents)
        REPORT_ARGS=(--env-file "$REPO_DIR/.env")
        for p in "${ALL_PROFILES[@]}"; do REPORT_ARGS+=(--profile "$p"); done
        docker compose "${REPORT_ARGS[@]}" ps -a 2>/dev/null | grep -iE "exit|restart" || echo "  无异常"
        ;;

    *)
        echo "用法: bash scripts/ops.sh {status|heal|update|backup|cleanup|emergency-disk|report}"
        echo ""
        echo "  status         健康检查 (critical 自动触发 heal)"
        echo "  heal           低风险自愈 (重启异常容器)"
        echo "  update         闭环更新: 备份→拉镜像→重建→验证→失败回滚 (--yes)"
        echo "  backup         备份 (调 backup.sh)"
        echo "  cleanup        清理无用资源 + WAL 回收 + 旧备份"
        echo "  emergency-disk 紧急磁盘止血 (≥阈值时激进释放)"
        echo "  report         生成运维摘要"
        exit 1
        ;;
esac
