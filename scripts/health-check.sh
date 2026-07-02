#!/usr/bin/env bash
# scripts/health-check.sh — TitanVault 健康检查
#
# 检查项 (输出结构化, 供 ops.sh / hermes / cron 消费):
#   1. docker 容器状态 (运行/退出/重启循环)
#   2. llama.cpp 原生服务 (8082/8084)
#   3. 关键端口可达性 (postgres/redis/litellm/caddy)
#   4. 磁盘空间 (DATA_DIR / docker root)
#   5. 内存
#
# 退出码: 0=全健康, 1=有告警, 2=有严重故障
# 输出: 人类可读 + --json 机器可读
#
# 用法:
#   bash scripts/health-check.sh            # 人类可读
#   bash scripts/health-check.sh --json     # JSON (供 hermes/监控消费)
set -euo pipefail

OUTPUT_JSON=false
[ "${1:-}" = "--json" ] && OUTPUT_JSON=true

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
. "$REPO_DIR/scripts/_lib.sh"
[ -f "$REPO_DIR/.env" ] && { set -a; . "$REPO_DIR/.env"; set +a; }
DATA_DIR="${DATA_DIR:-/data}"
# compose project 名鲁棒性: docker compose ps 默认按 project 过滤容器。
# project 名 = COMPOSE_PROJECT_NAME 或 (无设置时) 目录名。
# 若 up 时用了特定 project 名, ps 也必须用同一个, 否则查不到容器。
# 这里不强制设置 (会与实际 up 的 project 冲突), 只在已设置时 export。
[ -n "${COMPOSE_PROJECT_NAME:-}" ] && export COMPOSE_PROJECT_NAME

# 收集结果 (name|status|detail), status: ok/warn/critical
RESULTS=()
add_result() { RESULTS+=("$1|$2|$3"); }

# ===== 1. 容器状态 =====
if command -v docker >/dev/null 2>&1; then
    # 实际运行的容器
    RUNNING=$(docker compose ps --format '{{.Service}} {{.Status}}' 2>/dev/null || echo "")
    if [ -z "$RUNNING" ]; then
        add_result "docker-compose" "critical" "无运行中的 compose 服务"
    else
        # 检查重启循环 (Restarting 状态)
        restarting=$(echo "$RUNNING" | grep -i "restart" || true)
        [ -n "$restarting" ] && add_result "containers-restart" "critical" "重启循环: $restarting"
        # 检查退出状态
        exited=$(docker compose ps -a --format '{{.Service}} {{.Status}}' 2>/dev/null | grep -i "exit" || true)
        [ -n "$exited" ] && add_result "containers-exited" "warn" "已退出: $exited"
        [ -z "$restarting" ] && [ -z "$exited" ] && add_result "containers" "ok" "$(echo "$RUNNING" | wc -l | tr -d ' ') 服务运行中"
    fi
else
    add_result "docker" "critical" "docker 未安装"
fi

# ===== 2. llama.cpp 原生服务 (含性能: 延迟/队列, 不只存活) =====
if curl -sf http://127.0.0.1:8082/v1/models >/dev/null 2>&1; then
    add_result "llama-main" "ok" "8082 响应"
    # 性能探测: /slots 看队列堆积 (llama-server 内置)
    slots=$(curl -sf http://127.0.0.1:8082/slots 2>/dev/null || echo "")
    if [ -n "$slots" ]; then
        busy=$(echo "$slots" | python3 -c "import sys,json;d=json.load(sys.stdin);print(sum(1 for s in d if s.get('is_processing')))" 2>/dev/null || echo "?")
        total=$(echo "$slots" | python3 -c "import sys,json;print(len(json.load(sys.stdin)))" 2>/dev/null || echo "?")
        # 队列全满 (busy==total) 说明过载
        if [ "$busy" = "$total" ] && [ "$total" != "?" ] && [ "$total" -ge 2 ]; then
            add_result "llama-queue" "warn" "所有 slot 满载 ($busy/$total), 推理可能排队"
        else
            add_result "llama-queue" "ok" "slot 使用 $busy/$total"
        fi
    fi
else
    add_result "llama-main" "critical" "8082 无响应 (systemd: systemctl status llama-main)"
fi
# 推理延迟探测 (用真实模型名, 发最小请求测响应时间)
if curl -sf http://127.0.0.1:8082/v1/models >/dev/null 2>&1; then
    # 从 /v1/models 拿真实 model id (避免用假名导致 404 误报)
    model_id=$(curl -sf http://127.0.0.1:8082/v1/models 2>/dev/null \
        | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['data'][0]['id'])" 2>/dev/null || echo "")
    if [ -n "$model_id" ]; then
        latency=$(curl -sf -o /dev/null -w "%{time_total}" \
            -X POST http://127.0.0.1:8082/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"$model_id\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}" \
            --max-time 60 2>/dev/null || echo "99")
        latency_ms=$(echo "$latency" | awk '{printf "%.0f", $1*1000}')
        if [ "$latency_ms" -ge 30000 ] 2>/dev/null; then
            add_result "llama-latency" "warn" "推理延迟 ${latency_ms}ms (异常慢)"
        elif [ "$latency_ms" -lt 90000 ] 2>/dev/null; then
            add_result "llama-latency" "ok" "推理延迟 ${latency_ms}ms"
        fi
    fi
fi
if curl -sf http://127.0.0.1:8084/v1/models >/dev/null 2>&1; then
    add_result "llama-embed" "ok" "8084 响应"
else
    add_result "llama-embed" "warn" "8084 无响应"
fi
# GPU 利用率 (AMD gfx1151, 经 sysfs)
for card in /sys/class/drm/card*/device/gpu_busy_percent; do
    [ -f "$card" ] && {
        gpu_busy=$(cat "$card" 2>/dev/null || echo "?")
        [ "$gpu_busy" != "?" ] && add_result "gpu-util" "ok" "GPU busy ${gpu_busy}%"
    }
done

# ===== 3. 关键端口 (经 host 网络或发布端口) =====
check_port() {
    local name=$1 host=$2 port=$3
    if timeout 3 bash -c "echo > /dev/tcp/$host/$port" 2>/dev/null; then
        add_result "$name" "ok" "$host:$port 可达"
    else
        add_result "$name" "warn" "$host:$port 不可达"
    fi
}
check_port caddy 127.0.0.1 80
check_port litellm "${LITELLM_BIND:-127.0.0.1}" 4000
# aham-voice-web (ai-capability 档起启用, 端口探活即可; 未启用时此行为 warn, 正常)
check_port aham-voice 127.0.0.1 8765

# ===== 4. 磁盘空间 =====
disk_usage=$(df "$DATA_DIR" 2>/dev/null | awk 'NR==2{print $5}' | tr -dc '0-9')
if [ -n "$disk_usage" ]; then
    if [ "$disk_usage" -ge 95 ]; then
        add_result "disk" "critical" "$DATA_DIR ${disk_usage}% 满 (自动止血: ops.sh emergency-disk)"
        # critical 磁盘立即触发止血 (不等通用 heal, 磁盘满必须抢时间)
        # 设 DISK_HEALED 标记: 末尾的通用 heal 不再重复处理磁盘
        if [ "${OPS_AUTO_HEAL:-true}" = "true" ] && [ -z "${HEAL_IN_PROGRESS:-}" ]; then
            HEAL_IN_PROGRESS=1 DISK_HEALED=1 bash "$REPO_DIR/scripts/ops.sh" emergency-disk 95 2>&1 | sed 's/^/    /' || true
        fi
    elif [ "$disk_usage" -ge 85 ]; then
        add_result "disk" "warn" "$DATA_DIR ${disk_usage}% 满"
    else
        add_result "disk" "ok" "$DATA_DIR ${disk_usage}%"
    fi
fi
# docker root 磁盘
docker_root=$(docker info 2>/dev/null | grep "Docker Root Dir" | awk '{print $NF}' || echo "")
[ -n "$docker_root" ] && [ "$docker_root" != "$DATA_DIR" ] && {
    dusage=$(df "$docker_root" 2>/dev/null | awk 'NR==2{print $5}' | tr -dc '0-9')
    [ -n "$dusage" ] && [ "$dusage" -ge 90 ] && add_result "docker-disk" "warn" "docker root ${dusage}%"
}

# ===== 5. 内存 =====
mem_avail=$(free -m 2>/dev/null | awk '/^Mem:/{print $7}')
if [ -n "$mem_avail" ] && [ "$mem_avail" -lt 2048 ]; then
    add_result "memory" "warn" "可用内存 ${mem_avail}MB 偏低"
fi

# ===== 汇总退出码 =====
overall="ok"
for r in "${RESULTS[@]}"; do
    status=$(echo "$r" | cut -d'|' -f2)
    [ "$status" = "critical" ] && overall="critical"
    [ "$status" = "warn" ] && [ "$overall" = "ok" ] && overall="warn"
done

# ===== 输出 =====
if $OUTPUT_JSON; then
    # 机器可读 JSON (供 hermes/监控)
    printf '{"overall":"%s","checks":[' "$overall"
    first=true
    for r in "${RESULTS[@]}"; do
        IFS='|' read -r name status detail <<< "$r"
        $first || printf ','
        printf '{"name":"%s","status":"%s","detail":%s}' "$name" "$status" "$(printf '%s' "$detail" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '""')"
        first=false
    done
    printf ']}\n'
else
    # 人类可读
    echo "═══ TitanVault 健康状态: $overall ═══"
    for r in "${RESULTS[@]}"; do
        IFS='|' read -r name status detail <<< "$r"
        case $status in
            ok) icon="✅" ;;
            warn) icon="⚠️ " ;;
            critical) icon="❌" ;;
        esac
        printf "  %s %-20s %s\n" "$icon" "$name" "$detail"
    done
fi

# ===== 检查→自愈联动: critical 时自动触发 heal (可关) =====
# 默认开启 (OPS_AUTO_HEAL=true); hermes/cron 调用时 critical 自动止血, 不只记录
# 注意: 磁盘 critical 已在上面单独触发 emergency-disk (DISK_HEALED),
#       这里只处理"其它 critical" (容器/llama 等), 避免重复。
remaining_critical=false
for r in "${RESULTS[@]}"; do
    name=$(echo "$r" | cut -d'|' -f1)
    status=$(echo "$r" | cut -d'|' -f2)
    # 跳过已单独处理的 disk
    [ "$name" = "disk" ] && [ "${DISK_HEALED:-}" = "1" ] && continue
    [ "$status" = "critical" ] && remaining_critical=true
done
if [ "$remaining_critical" = true ] && [ "${OPS_AUTO_HEAL:-true}" = "true" ] && [ -z "${HEAL_IN_PROGRESS:-}" ]; then
    echo ""
    echo "🚨 检测到 critical 故障, 触发自愈 (ops.sh heal)..."
    echo "   (关闭自动自愈: OPS_AUTO_HEAL=false)"
    # 设 HEAL_IN_PROGRESS 防止 heal 内的 health-check 递归
    HEAL_IN_PROGRESS=1 bash "$REPO_DIR/scripts/ops.sh" heal 2>&1 | sed 's/^/  /' || true
    echo ""
    echo "自愈后复检..."
    # 复检一次 (本脚本不自愈, 只看结果)
    OPS_AUTO_HEAL=false bash "$REPO_DIR/scripts/health-check.sh" "${OUTPUT_JSON:+--json}" || true
    exit $?
fi

case $overall in
    ok) exit 0 ;; warn) exit 1 ;; critical) exit 2 ;;
esac
