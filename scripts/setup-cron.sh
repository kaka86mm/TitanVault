#!/usr/bin/env bash
# scripts/setup-cron.sh — 安装运维定时任务到 crontab
#
# 默认调度 (可用环境变量覆盖):
#   每天凌晨 3:00  备份     (OPS_BACKUP_CRON, 默认 "0 3 * * *")
#   每天凌晨 4:00  自愈+清理 (OPS_HEAL_CRON,  默认 "0 4 * * *")
#   每周日 5:00    镜像更新 (OPS_UPDATE_CRON,默认 "0 5 * * 0", 需 --yes 才真更新)
#   每小时         健康检查 (OPS_CHECK_CRON, 默认 "0 * * * *", 仅记日志, 不告警)
#
# 用法:
#   bash scripts/setup-cron.sh           # 安装默认调度
#   bash scripts/setup-cron.sh --remove  # 移除本脚本的调度
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$REPO_DIR/.env" ] && { set -a; . "$REPO_DIR/.env"; set +a; }

OPS_BACKUP_CRON="${OPS_BACKUP_CRON:-0 3 * * *}"
OPS_HEAL_CRON="${OPS_HEAL_CRON:-0 4 * * *}"
OPS_UPDATE_CRON="${OPS_UPDATE_CRON:-0 5 * * 0}"
OPS_CHECK_CRON="${OPS_CHECK_CRON:-0 * * * *}"
MARKER="# mozin-ops"

PATH_PREFIX="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# 移除旧的本脚本调度 (按 marker)
remove_mozin_cron() {
    crontab -l 2>/dev/null | grep -v "$MARKER" | crontab - || true
}

if [ "${1:-}" = "--remove" ]; then
    remove_mozin_cron
    echo "✅ 已移除 mozin 运维定时任务"
    exit 0
fi

echo "安装运维定时任务:"
echo "  $OPS_CHECK_CRON  每小时健康检查 → logs/health.log"
echo "  $OPS_BACKUP_CRON  每天备份"
echo "  $OPS_HEAL_CRON   每天自愈+清理"
echo "  $OPS_UPDATE_CRON 每周镜像更新检查 (--yes 才真更新)"
echo ""

remove_mozin_cron
mkdir -p "$REPO_DIR/logs"

(crontab -l 2>/dev/null | grep -v "$MARKER"
 echo "$OPS_CHECK_CRON $PATH_PREFIX $REPO_DIR/scripts/ops.sh status >> $REPO_DIR/logs/health.log 2>&1 $MARKER"
 echo "$OPS_BACKUP_CRON $PATH_PREFIX $REPO_DIR/scripts/ops.sh backup >> $REPO_DIR/logs/backup.log 2>&1 $MARKER"
 echo "$OPS_HEAL_CRON $PATH_PREFIX $REPO_DIR/scripts/ops.sh heal >> $REPO_DIR/logs/heal.log 2>&1 $MARKER"
 echo "$OPS_HEAL_CRON $PATH_PREFIX $REPO_DIR/scripts/ops.sh cleanup >> $REPO_DIR/logs/cleanup.log 2>&1 $MARKER"
 echo "$OPS_UPDATE_CRON $PATH_PREFIX $REPO_DIR/scripts/ops.sh update --yes >> $REPO_DIR/logs/update.log 2>&1 $MARKER"
) | crontab -

echo "✅ 已安装 (crontab -l 查看)"
echo "   日志: $REPO_DIR/logs/"
echo "   移除: bash scripts/setup-cron.sh --remove"
echo ""
warn_note() { echo -e "\033[1;33m[注意]\033[0m $*"; }
warn_note "镜像更新 (update --yes) 会自动重建容器, 服务短暂中断。"
warn_note "如不想自动更新, 设 OPS_UPDATE_CRON 为空或手动移除该行。"
