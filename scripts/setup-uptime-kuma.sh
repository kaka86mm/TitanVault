#!/usr/bin/env bash
# scripts/setup-uptime-kuma.sh — 生成 uptime-kuma 监控配置清单
#
# ⚠️ uptime-kuma 后端用 socket.io, 没有简单 REST API, 无法脚本自动注册监控项。
#    本脚本生成结构化清单 (JSON + 人类可读), 用户在 UI 里照着快速添加,
#    或用支持 uptime-kuma socket.io 的工具 (如 uptime-kuma-api python 库) 批量导入。
#
# 用法:
#   bash scripts/setup-uptime-kuma.sh              # 打印监控清单 + 操作指引
#   bash scripts/setup-uptime-kuma.sh --json       # 输出 JSON (供工具导入)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$REPO_DIR/.env" ] && { set -a; . "$REPO_DIR/.env"; set +a; }

OUTPUT_JSON=false
[ "${1:-}" = "--json" ] && OUTPUT_JSON=true

HOST_IP="${HOST_IP:-127.0.0.1}"

# 监控项: name|type|target
# type: http=HTTP探活, port=TCP端口, keyword=HTTP关键字
MONITORS=(
    "Mozin门户(Caddy)|http|http://${HOST_IP}/"
    "LiteLLM健康|http|http://${HOST_IP}/llm/health/liveliness"
    "llama.cpp main|port|127.0.0.1:8082"
    "llama.cpp embed|port|127.0.0.1:8084"
    "Dify|http|http://${HOST_IP}:3000"
    "SenseVoice ASR|port|127.0.0.1:9991"
    "Kokoro TTS|port|127.0.0.1:8081"
    "MinerU Web|http|http://${HOST_IP}:8090"
    "MinerU API (GPU)|port|127.0.0.1:18080"
    "Aham Voice|port|127.0.0.1:8765"
    "Gitea|http|http://${HOST_IP}:3002"
    "uptime-kuma自身|http|http://${HOST_IP}:3001"
)

if $OUTPUT_JSON; then
    # JSON 供 uptime-kuma-api 等工具批量导入
    printf '{"monitors":['
    first=true
    for m in "${MONITORS[@]}"; do
        IFS='|' read -r name type target <<< "$m"
        $first || printf ','
        if [ "$type" = "port" ]; then
            host=$(echo "$target" | cut -d: -f1)
            port=$(echo "$target" | cut -d: -f2)
            printf '{"name":%s,"type":"port","hostname":%s,"port":%s}' \
                "$(printf '%s' "$name" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')" \
                "$(printf '%s' "$host" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')" \
                "$port"
        else
            printf '{"name":%s,"type":"http","url":%s}' \
                "$(printf '%s' "$name" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')" \
                "$(printf '%s' "$target" | python3 -c 'import sys,json;print(json.dumps(sys.stdin.read()))')"
        fi
        first=false
    done
    printf ']}\n'
    exit 0
fi

cat <<EOF
═══════════════════════════════════════════════════════
  uptime-kuma 监控配置清单
  (uptime-kuma 用 socket.io, 需在 UI 手动添加或用工具导入)
═══════════════════════════════════════════════════════

需添加的 ${#MONITORS[@]} 个监控项 (在 :3001 UI → Add New Monitor):

EOF
for m in "${MONITORS[@]}"; do
    IFS='|' read -r name type target <<< "$m"
    case "$type" in
        http)  printf "  %-22s [HTTP]  %s\n" "$name" "$target" ;;
        port)  printf "  %-22s [TCP]   %s\n" "$name" "$target" ;;
    esac
done

cat <<EOF

操作步骤:
  1. 浏览器打开 http://${HOST_IP}:3001, 完成首次设置 (建管理员账号)
  2. 照上面清单逐个 Add New Monitor (Monitor Type 选 HTTP(s) 或 TCP Port)
  3. ⚠️ 关键: Settings → Notifications → 添加告警通道 (Telegram/邮件/Webhook)
     并给每个 Monitor 绑定通知 (否则故障不推送!)
  4. (可选) Status Pages → 建公开状态页

批量导入 (避免手动逐个加):
  pip install uptime-kuma-api
  # 用本脚本的 JSON 输出驱动导入工具:
  bash $0 --json > /tmp/kuma-monitors.json
  # 然后写个小 python 脚本读 JSON 经 socket.io 批量 add

⚠️ 完成通知通道绑定前, 故障不会推送到你! 这步必须做。
EOF
