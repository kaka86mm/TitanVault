#!/usr/bin/env bash
# scripts/_lib.sh — 共享函数库 (backup/restore/install 复用)
# 被 source: source "$(dirname "$0")/_lib.sh"
# 不要直接执行本文件。

REPO_DIR_LIB="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# mozin_profiles: 输出指定 preset 启用的 compose --profile 参数 (空格分隔)
# 用法: mapfile -t PROFS < <(mozin_profiles standard) 或 args=($(mozin_profiles))
# 不用命令替换 $(mozin_profiles) 以避开 shellcheck SC2046; 用数组读取。
mozin_profiles() {
    local preset="${1:-${PRESET:-standard}}"
    local envfile="$REPO_DIR_LIB/presets/${preset}.env"
    [ -f "$envfile" ] || envfile="$REPO_DIR_LIB/presets/standard.env"
    # source preset (INCLUDE_* 开关)
    set -a; . "$envfile"; set +a
    [ "$INCLUDE_INFRA" = true ] && echo "infra"
    [ "$INCLUDE_GATEWAY" = true ] && echo "gateway"
    [ "$INCLUDE_AI_CAPABILITY" = true ] && echo "ai-capability"
    [ "$INCLUDE_NETWORK" = true ] && echo "network"
    [ "$INCLUDE_APPS" = true ] && echo "apps"
    [ "$INCLUDE_MONITORING" = true ] && echo "monitoring"
    [ "$INCLUDE_AGENTS" = true ] && echo "agents"
}

# mozin_compose_cmd: 输出 docker compose 基础命令 + profile 参数 (一行一个 token, 供 mapfile)
# 用法: mapfile -t CMD < <(mozin_compose_cmd up -d)
mozin_compose_cmd() {
    local preset="${PRESET:-standard}"
    local action_args=("$@")
    printf '%s\n' docker compose --env-file "$REPO_DIR_LIB/.env"
    while IFS= read -r p; do
        printf '%s\n' --profile "$p"
    done < <(mozin_profiles "$preset")
    printf '%s\n' "${action_args[@]}"
}
