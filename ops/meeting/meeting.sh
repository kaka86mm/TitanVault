#!/usr/bin/env bash
# ops/meeting/meeting.sh — 会议录音处理确定性脚本
#
# 封装 Aham Voice (:8765) 完整流水线: 登录 → 上传 → 轮询 → 导出纪要。
# 幂等: 同一文件重复上传会产生新 recording (Aham 无去重), 由调用方避免。
#
# 子命令:
#   login            — 登录拿 cookie (仅密码启用时需要), 存到 $COOKIE_JAR
#   transcribe <file> [--title T] [--speakers N] [--mode quick|full]
#                    — 上传并等待转写完成 (quick=仅ASR, full=ASR+纪要), 输出 recording_id
#   status <id>      — 查询 recording 状态 (asr/summary/emotion)
#   minutes <id> [-o out.md]
#                    — 导出会议纪要 markdown (先等 summary 就绪)
#   transcript <id> [-o out.md]
#                    — 导出纯转写 markdown
#   wait <id> [--for asr|summary|all] [--timeout 1800]
#                    — 阻塞等待指定阶段完成
#   quick <file> [--title T] [-o out.md]
#                    — 一键快速转写: 上传→等ASR→导出转写 (走 SenseVoice 路径, 见下)
#
# 快速模式 (quick): 用 SenseVoice (:9991) 直接转写, 不经 Aham。
#   优势: 快 (无说话人分离/纪要开销), 适合"我只要文字稿"。
#   限制: 无说话人分离、无纪要、无情绪。
# 完整模式 (full, 默认): 走 Aham Voice 全流水线。
#
# 用法示例:
#   bash ops/meeting/meeting.sh login
#   bash ops/meeting/meeting.sh transcribe meeting.m4a --title "周会" --speakers 4
#   bash ops/meeting/meeting.sh minutes rec_abc123 -o 周会纪要.md
#   bash ops/meeting/meeting.sh quick meeting.m4a -o 转写.md
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[ -f "$REPO_DIR/.env" ] && { set -a; . "$REPO_DIR/.env"; set +a; }

AHAM_URL="${AHAMVOICE_URL:-http://localhost:8765}"
AHAM_PASS="${AHAMVOICE_ACCESS_PASSWORD:-}"
SENSE_URL="${SENSEVOICE_URL:-http://localhost:9991}"
COOKIE_JAR="${COOKIE_JAR:-/tmp/aham_cookies.txt}"
DATA_DIR="${DATA_DIR:-/data}"
DEFAULT_TIMEOUT="${MEETING_TIMEOUT:-1800}"   # 30 min

log()  { echo -e "\033[1;34m[meeting]\033[0m $*"; }
warn() { echo -e "\033[1;33m[注意]\033[0m $*" >&2; }
err()  { echo -e "\033[1;31m[错误]\033[0m $*" >&2; }

# ah_req: 发认证请求 (带 cookie jar)。用法: ah_req METHOD PATH [curl额外参数...]
ah_req() {
    local method="$1"; shift
    local path="$1"; shift
    curl -sf --max-time 30 -X "$method" "$AHAM_URL$path" \
        -b "$COOKIE_JAR" -c "$COOKIE_JAR" "$@"
}

CMD="${1:-help}"; shift || true

case "$CMD" in
    login)
        if [ -z "$AHAM_PASS" ]; then
            log "AHAMVOICE_ACCESS_PASSWORD 为空 → Aham 处于无密码模式, 跳过登录"
            # 清空 cookie jar, 表示"无需认证"
            : > "$COOKIE_JAR"
            exit 0
        fi
        log "登录 Aham Voice..."
        curl -sf --max-time 10 -X POST "$AHAM_URL/api/auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"password\":\"$AHAM_PASS\"}" \
            -c "$COOKIE_JAR" >/dev/null
        log "✅ 登录成功, cookie 存于 $COOKIE_JAR"
        ;;

    transcribe)
        FILE=""; TITLE=""; SPEAKERS=""; MODE="full"
        while [ $# -gt 0 ]; do
            case "$1" in
                --title) TITLE="$2"; shift 2 ;;
                --speakers) SPEAKERS="$2"; shift 2 ;;
                --mode) MODE="$2"; shift 2 ;;
                --help|-h) echo "用法: transcribe <file> [--title T] [--speakers N] [--mode quick|full]"; exit 0 ;;
                *) FILE="$1"; shift ;;
            esac
        done
        [ -n "$FILE" ] || { err "缺少音频文件路径"; exit 2; }
        [ -f "$FILE" ] || { err "文件不存在: $FILE"; exit 2; }

        # 确保已登录 (幂等: login 自己判断是否需要)
        bash "$0" login

        if [ "$MODE" = "quick" ]; then
            # 快速模式委托给 quick 子命令 (SenseVoice 直转)
            exec bash "$0" quick "$FILE" ${TITLE:+--title "$TITLE"}
        fi

        # full 模式: 上传到 Aham, auto_process=true 自动触发 ASR + summary
        SIZE_MB=$(du -m "$FILE" | awk '{print $1}')
        log "上传到 Aham Voice: $FILE (${SIZE_MB}MB)"
        [ -n "$TITLE" ]      || TITLE="$(basename "$FILE" | sed 's/\.[^.]*$//')"
        [ -n "$SPEAKERS" ]   || SPEAKERS="4"

        RESP=$(curl -sf --max-time 120 -X POST "$AHAM_URL/api/recordings" \
            -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
            -F "file=@$FILE" \
            -F "title=$TITLE" \
            -F "auto_process=true" \
            -F "expected_speakers=$SPEAKERS")
        RID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
        [ -n "$RID" ] || { err "上传失败, 响应: $RESP"; exit 1; }
        log "✅ 已上传, recording_id=$RID"
        log "   Aham 后台自动处理 ASR + 纪要。用 status/wait/minutes 子命令查询和导出。"
        echo "$RID"
        ;;

    status)
        RID="${1:-}"; [ -n "$RID" ] || { err "缺少 recording_id"; exit 2; }
        bash "$0" login >/dev/null 2>&1 || true
        DETAIL=$(ah_req GET "/api/recordings/$RID")
        echo "$DETAIL" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f\"标题: {d.get('title','?')}\")
print(f\"时长: {d.get('duration_seconds',0):.0f}s\")
t = d.get('tasks',{})
print(f\"ASR 状态:    {t.get('asr_status','?')}\")
print(f\"纪要状态:    {t.get('summary_status','?')}\")
print(f\"情绪状态:    {t.get('emotion_status','?')}\")
segs = d.get('segments',[])
print(f\"分段数:      {len(segs)}\")
if segs:
    spks = set(s.get('speaker','?') for s in segs)
    print(f\"说话人:      {', '.join(sorted(spks))}\")
"
        ;;

    wait)
        RID=""; FOR="summary"; TIMEOUT="$DEFAULT_TIMEOUT"
        while [ $# -gt 0 ]; do
            case "$1" in
                --for) FOR="$2"; shift 2 ;;
                --timeout) TIMEOUT="$2"; shift 2 ;;
                *) RID="$1"; shift ;;
            esac
        done
        [ -n "$RID" ] || { err "缺少 recording_id"; exit 2; }
        bash "$0" login >/dev/null 2>&1 || true

        # --for 决定轮询哪个状态字段
        case "$FOR" in
            asr) FIELD="asr_status"; TARGET="done" ;;
            summary|minutes) FIELD="summary_status"; TARGET="done" ;;
            emotion) FIELD="emotion_status"; TARGET="done" ;;
            all) FIELD="__all__"; TARGET="done" ;;
            *) err "未知 --for 值: $FOR (可选: asr/summary/emotion/all)"; exit 2 ;;
        esac

        log "等待 $RID 的 [$FOR] 完成 (超时 ${TIMEOUT}s)..."
        ELAPSED=0; POLL_INTERVAL=10
        while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
            DETAIL=$(ah_req GET "/api/recordings/$RID" 2>/dev/null || echo "{}")
            if [ "$FIELD" = "__all__" ]; then
                ASR=$(echo "$DETAIL" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tasks',{}).get('asr_status',''))" 2>/dev/null)
                SUM=$(echo "$DETAIL" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tasks',{}).get('summary_status',''))" 2>/dev/null)
                if [ "$ASR" = "done" ] && [ "$SUM" = "done" ]; then
                    log "✅ ASR + 纪要均完成 (${ELAPSED}s)"
                    exit 0
                fi
            else
                ST=$(echo "$DETAIL" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('tasks',{}).get('$FIELD',''))" 2>/dev/null)
                case "$ST" in
                    done) log "✅ [$FOR] 完成 (${ELAPSED}s)"; exit 0 ;;
                    failed|error) err "[$FOR] 处理失败 (status=$ST)"; exit 1 ;;
                esac
            fi
            sleep "$POLL_INTERVAL"; ELAPSED=$((ELAPSED + POLL_INTERVAL))
            [ $((ELAPSED % 60)) -eq 0 ] && log "  仍在处理... (${ELAPSED}s elapsed)"
        done
        err "等待超时 (${TIMEOUT}s), [$FOR] 未完成"
        exit 1
        ;;

    minutes)
        RID=""; OUT=""
        while [ $# -gt 0 ]; do
            case "$1" in
                -o) OUT="$2"; shift 2 ;;
                *) RID="$1"; shift ;;
            esac
        done
        [ -n "$RID" ] || { err "缺少 recording_id"; exit 2; }
        bash "$0" login >/dev/null 2>&1 || true

        # 先确保 summary 就绪
        log "确保纪要已生成..."
        bash "$0" wait "$RID" --for summary --timeout "$DEFAULT_TIMEOUT" || {
            warn "纪要未就绪, 尝试主动触发..."
            ah_req POST "/api/recordings/$RID/summarize" >/dev/null 2>&1 || true
            bash "$0" wait "$RID" --for summary --timeout 600 || { err "纪要生成失败"; exit 1; }
        }

        MD=$(ah_req GET "/api/recordings/$RID/export/summary.md")
        if [ -n "$OUT" ]; then
            echo "$MD" > "$OUT"
            log "✅ 纪要已保存: $OUT ($(echo "$MD" | wc -l | tr -d ' ') 行)"
        else
            echo "$MD"
        fi
        ;;

    transcript)
        RID=""; OUT=""
        while [ $# -gt 0 ]; do
            case "$1" in
                -o) OUT="$2"; shift 2 ;;
                *) RID="$1"; shift ;;
            esac
        done
        [ -n "$RID" ] || { err "缺少 recording_id"; exit 2; }
        bash "$0" login >/dev/null 2>&1 || true
        bash "$0" wait "$RID" --for asr --timeout "$DEFAULT_TIMEOUT" || true

        MD=$(ah_req GET "/api/recordings/$RID/export/transcript.md")
        if [ -n "$OUT" ]; then
            echo "$MD" > "$OUT"
            log "✅ 转写已保存: $OUT ($(echo "$MD" | wc -l | tr -d ' ') 行)"
        else
            echo "$MD"
        fi
        ;;

    quick)
        # 快速转写: SenseVoice 直转, 无说话人分离, 纯文字稿
        FILE=""; TITLE=""; OUT=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --title) TITLE="$2"; shift 2 ;;
                -o) OUT="$2"; shift 2 ;;
                *) FILE="$1"; shift ;;
            esac
        done
        [ -n "$FILE" ] || { err "缺少音频文件路径"; exit 2; }
        [ -f "$FILE" ] || { err "文件不存在: $FILE"; exit 2; }

        [ -n "$TITLE" ] || TITLE="$(basename "$FILE" | sed 's/\.[^.]*$//')"
        log "[快速模式] SenseVoice 直转: $FILE"
        # SenseVoice: OpenAI 兼容 /v1/audio/transcriptions
        # 加 language=zh 提升中文识别 (不加可能输出 "Chinese letter" 占位符)
        RESULT=$(curl -sf --max-time 600 \
            -F "file=@$FILE" \
            -F "model=SenseVoiceSmall" \
            -F "language=zh" \
            "$SENSE_URL/v1/audio/transcriptions" 2>/dev/null || echo "")
        [ -n "$RESULT" ] || { err "SenseVoice 转写失败 (确认 :9991 在运行)"; exit 1; }

        # OpenAI 兼容响应: {"text": "..."}
        TEXT=$(echo "$RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin).get('text',''))" 2>/dev/null || echo "$RESULT")

        # 包装成简单 markdown
        MD="# $TITLE (快速转写)

> 转写引擎: SenseVoice (无说话人分离)
> 时间: $(date '+%Y-%m-%d %H:%M')

---

$TEXT
"
        if [ -n "$OUT" ]; then
            echo "$MD" > "$OUT"
            log "✅ 转写已保存: $OUT"
        else
            echo "$MD"
        fi
        ;;

    help|--help|-h)
        cat <<'EOF'
meeting.sh — 会议录音处理 (Aham Voice + SenseVoice)

子命令:
  login                         登录 Aham (无密码模式自动跳过)
  transcribe <file> [opts]      上传到 Aham 全流水线, 输出 recording_id
    --title T                    会议标题 (默认=文件名)
    --speakers N                 预期说话人数 (默认4)
    --mode quick|full            quick=SenseVoice直转, full=Aham全流程 (默认)
  quick <file> [-o out.md]      一键快速转写 (SenseVoice, 无分离/纪要)
  status <id>                   查询 recording 状态
  wait <id> [--for X]           等待阶段完成 (asr/summary/emotion/all)
    --timeout S                  超时秒数 (默认1800)
  minutes <id> [-o out.md]      导出会议纪要 (等待 summary 就绪)
  transcript <id> [-o out.md]   导出纯转写

环境变量 (从 .env 读):
  AHAMVOICE_URL                 默认 http://localhost:8765
  AHAMVOICE_ACCESS_PASSWORD     空则无密码模式
  SENSEVOICE_URL                默认 http://localhost:9991
EOF
        ;;

    *)
        err "未知子命令: $CMD (用 help 查看用法)"
        exit 2
        ;;
esac
