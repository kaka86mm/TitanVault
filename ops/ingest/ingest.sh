#!/usr/bin/env bash
# ops/ingest/ingest.sh — 知识入库确定性脚本
#
# 把任意 URL / 文件 / 文本存入 Open Notebook 知识库, 支持 RAG 问答。
# 自动: PDF 走 MinerU 解析 → 存 ON; URL 直接抓 → 存 ON; 文本直接存。
#
# 子命令:
#   url <URL> [--notebook ID] [--title T]
#                 抓取网页并存入 ON
#   file <path> [--notebook ID] [--title T]
#                 上传文件 (PDF/DOCX/TXT/MD/EPUB) 存入 ON
#   text <text|-> [--notebook ID] [--title T]
#                 存入纯文本 (- 表示从 stdin 读)
#   pdf <path> [--notebook ID] [--title T]
#                 PDF 专用: 先 MinerU 解析为 markdown, 再作为文本源存入 (带原始文件)
#   ask <question> [--notebook ID]
#                 对知识库做 RAG 问答
#   notebooks     列出所有 notebook
#   sources [--notebook ID]
#                 列出 source (可按 notebook 过滤)
#   probe         探测 ON 版本 + 端点前缀 (诊断用)
#
# 路径前缀自适应: Open Notebook 不同版本端点可能是 /api/sources 或 /sources。
# 本脚本运行时探测 openapi.json 自动确定, 不硬编码。
#
# 用法:
#   bash ops/ingest/ingest.sh url https://example.com/article --title "那篇文章"
#   bash ops/ingest/ingest.sh pdf report.pdf
#   bash ops/ingest/ingest.sh ask "这篇报告的核心结论是什么?"
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[ -f "$REPO_DIR/.env" ] && { set -a; . "$REPO_DIR/.env"; set +a; }

ON_URL="${OPEN_NOTEBOOK_URL:-http://localhost:5055}"
ON_PASS="${OPEN_NOTEBOOK_PASSWORD:-}"
MINERU_URL="${MINERU_API_URL:-http://localhost:18080}"

log()  { echo -e "\033[1;34m[ingest]\033[0m $*"; }
warn() { echo -e "\033[1;33m[注意]\033[0m $*" >&2; }
err()  { echo -e "\033[1;31m[错误]\033[0m $*" >&2; }

# on_base_path: 探测 ON 的 API 路径前缀。缓存到 /tmp 避免重复探测。
# 返回值 echo 出来 (用命令替换捕获)。例: "" 或 "/api"
on_base_path() {
    local cache="/tmp/ingest_on_prefix.cache"
    if [ -f "$cache" ] && [ "$(($(date +%s) - $(stat -c %Y "$cache" 2>/dev/null || stat -f %m "$cache" 2>/dev/null || echo 0)))" -lt 3600 ]; then
        cat "$cache"; return
    fi
    # 探测: /openapi.json 里有 /api/sources 还是 /sources
    local prefix=""
    if curl -sf --max-time 5 "$ON_URL/openapi.json" 2>/dev/null | grep -q '"/api/sources"'; then
        prefix="/api"
    elif curl -sf --max-time 5 "$ON_URL/openapi.json" 2>/dev/null | grep -q '"/sources"'; then
        prefix=""
    else
        # openapi 拿不到, 试探性请求
        if curl -sf --max-time 5 "$ON_URL/api/sources?limit=1" $(on_auth_header) >/dev/null 2>&1; then
            prefix="/api"
        elif curl -sf --max-time 5 "$ON_URL/sources?limit=1" $(on_auth_header) >/dev/null 2>&1; then
            prefix=""
        else
            warn "无法探测 ON 端点前缀, 默认用 /api"
            prefix="/api"
        fi
    fi
    echo "$prefix" | tee "$cache"
}

# on_auth_header: 输出 ON 的认证 header 参数 (供 curl)。空密码则输出空。
on_auth_header() {
    if [ -n "$ON_PASS" ]; then
        echo "-H" "Authorization: Bearer $ON_PASS"
    fi
}

# on_req: 发 ON 请求。用法: on_req METHOD PATH [curl参数...]
# 注意: 不用 -f (否则 4xx/5xx 时 curl 直接报错, 拿不到响应体用于诊断)
on_req() {
    local method="$1"; shift
    local path="$1"; shift
    local base; base=$(on_base_path)
    curl -s --max-time 30 -X "$method" "$ON_URL$base$path" \
        $(on_auth_header) "$@"
}

# ensure_notebook: 给定 notebook 名或 ID, 返回 ID。没有则用 "default"。
# (ON 的 notebook_id 是 notebook:xxx 格式)
resolve_notebook() {
    local nb="${1:-}"
    [ -z "$nb" ] && { echo ""; return; }
    # 已经是 notebook:xxx 格式, 直接返回
    case "$nb" in
        notebook:*) echo "$nb"; return ;;
    esac
    # 按名字查
    local base; base=$(on_base_path)
    local nid
    nid=$(curl -sf --max-time 10 "$ON_URL$base/notebooks" $(on_auth_header) 2>/dev/null \
        | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    items = data if isinstance(data, list) else data.get('items', [])
    for n in items:
        if n.get('name') == '$nb' or n.get('id') == '$nb':
            print(n.get('id', '')); break
except: pass
" 2>/dev/null || echo "")
    [ -z "$nid" ] && warn "notebook '$nb' 未找到, 将用默认 notebook"
    echo "$nid"
}

CMD="${1:-help}"; shift || true

case "$CMD" in
    probe)
        log "探测 Open Notebook @ $ON_URL"
        echo "认证: ${ON_PASS:+密码模式}${ON_PASS:-无密码}"
        PROBE_BASE=$(on_base_path)
        echo "端点前缀: '${PROBE_BASE}' (即路径为 $ON_URL${PROBE_BASE}/sources)"
        echo ""
        log "健康检查..."
        if curl -sf --max-time 5 "$ON_URL/health" $(on_auth_header) >/dev/null 2>&1; then
            echo "  ✅ /health OK"
        else
            echo "  ❌ /health 不通"
        fi
        log "notebooks 可读性..."
        if on_req GET "/notebooks" >/dev/null 2>&1; then
            echo "  ✅ notebooks 可访问"
        else
            echo "  ❌ notebooks 不可读 (检查认证/前缀)"
        fi
        log "MinerU @ $MINERU_URL..."
        if curl -sf --max-time 5 "$MINERU_URL/health" >/dev/null 2>&1; then
            echo "  ✅ MinerU 可用 (PDF 解析就绪)"
        else
            echo "  ⚠️ MinerU 不可用 (PDF 将直接上传 ON, 可能解析不全)"
        fi
        ;;

    notebooks)
        on_req GET "/notebooks" | python3 -m json.tool 2>/dev/null || on_req GET "/notebooks"
        ;;

    sources)
        NB=""; while [ $# -gt 0 ]; do case "$1" in --notebook) NB="$2"; shift 2;; *) shift;; esac; done
        NB_ID=$(resolve_notebook "$NB")
        if [ -n "$NB_ID" ]; then
            on_req GET "/sources?notebook_id=$NB_ID"
        else
            on_req GET "/sources"
        fi | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    items = data if isinstance(data, list) else data.get('items', [])
    for s in items[:30]:
        sid = s.get('id','?')
        stype = s.get('type','?')
        title = (s.get('title') or s.get('name') or '?')[:40]
        # 状态字段: 不同 ON 版本字段名不同
        status = s.get('processing_status') or s.get('status') or s.get('state') or '?'
        print(f'  {sid:30} {stype:10} {status:12} {title}')
    print(f'... 共 {len(items)} 个')
except Exception as e:
    print(f'[解析失败, 原始输出]: {e}')
    sys.stdin.seek(0); print(sys.stdin.read()[:500])
" 2>/dev/null
        ;;

    url)
        URL=""; NB=""; TITLE=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --notebook) NB="$2"; shift 2 ;;
                --title) TITLE="$2"; shift 2 ;;
                *) URL="$1"; shift ;;
            esac
        done
        [ -n "$URL" ] || { err "缺少 URL"; exit 2; }
        NB_ID=$(resolve_notebook "$NB")
        log "抓取并存入 ON: $URL"

        # ON 的 link 类型 source: 直接给 URL, ON 自己抓取处理
        # 字段名: type=link, url=<URL> (不是 assets), embed=true
        ARGS=(-X POST)
        ARGS+=(-F "type=link")
        ARGS+=(-F "url=$URL")
        ARGS+=(-F "embed=true")
        ARGS+=(-F "async_processing=true")
        [ -n "$NB_ID" ]   && ARGS+=(-F "notebook_id=$NB_ID")
        [ -n "$TITLE" ]   && ARGS+=(-F "title=$TITLE")

        RESP=$(on_req POST "/sources" "${ARGS[@]}" 2>&1) || { err "存入失败: $RESP"; exit 1; }
        SID=$(echo "$RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('id',''))" 2>/dev/null || echo "")
        if [ -n "$SID" ]; then
            log "✅ 已入库: $SID"
            log "   ON 后台异步处理 (抓取+embedding)。用 'sources' 子命令查状态。"
            echo "$SID"
        else
            echo "$RESP"
        fi
        ;;

    text)
        INPUT=""; NB=""; TITLE=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --notebook) NB="$2"; shift 2 ;;
                --title) TITLE="$2"; shift 2 ;;
                *) INPUT="$1"; shift ;;
            esac
        done
        [ -n "$INPUT" ] || { err "缺少文本 (或用 - 从 stdin 读)"; exit 2; }
        if [ "$INPUT" = "-" ]; then
            INPUT=$(cat)
        fi
        NB_ID=$(resolve_notebook "$NB")
        [ -n "$TITLE" ] || TITLE="文本片段 $(date '+%m-%d %H:%M')"
        log "存入文本 (${#INPUT} 字符)"

        # text 类型: 字段名是 content (从 openapi.json 确认), embed=true
        printf '%s' "$INPUT" | on_req POST "/sources" \
            -F "type=text" \
            -F "content=@-" \
            -F "embed=true" \
            -F "async_processing=true" \
            $([ -n "$NB_ID" ] && echo "-F notebook_id=$NB_ID") \
            -F "title=$TITLE" > /tmp/ingest_resp.txt 2>&1 || {
            err "存入失败"; cat /tmp/ingest_resp.txt; exit 1
        }
        RESP=$(cat /tmp/ingest_resp.txt)
        SID=$(echo "$RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('id',''))" 2>/dev/null || echo "")
        [ -n "$SID" ] && log "✅ 已入库: $SID" || echo "$RESP"
        echo "$SID"
        ;;

    file)
        FILE=""; NB=""; TITLE=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --notebook) NB="$2"; shift 2 ;;
                --title) TITLE="$2"; shift 2 ;;
                *) FILE="$1"; shift ;;
            esac
        done
        [ -n "$FILE" ] || { err "缺少文件路径"; exit 2; }
        [ -f "$FILE" ] || { err "文件不存在: $FILE"; exit 2; }
        NB_ID=$(resolve_notebook "$NB")
        [ -n "$TITLE" ] || TITLE="$(basename "$FILE")"

        # PDF 专用路径: 走 MinerU 解析后存为文本 (带原文)
        EXT="${FILE##*.}"
        case "$(echo "$EXT" | tr '[:upper:]' '[:lower:]')" in
            pdf)
                log "检测到 PDF, 走专用路径 (MinerU 解析)..."
                exec bash "$0" pdf "$FILE" ${NB:+--notebook "$NB"} --title "$TITLE"
                ;;
        esac

        log "上传文件到 ON: $FILE"
        ARGS=(-F "type=upload" -F "file=@$FILE")
        [ -n "$NB_ID" ] && ARGS+=(-F "notebook_id=$NB_ID")
        ARGS+=(-F "title=$TITLE")

        RESP=$(on_req POST "/sources" "${ARGS[@]}" 2>&1) || { err "上传失败: $RESP"; exit 1; }
        SID=$(echo "$RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('id',''))" 2>/dev/null || echo "")
        [ -n "$SID" ] && log "✅ 已入库: $SID" || echo "$RESP"
        echo "$SID"
        ;;

    pdf)
        FILE=""; NB=""; TITLE=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --notebook) NB="$2"; shift 2 ;;
                --title) TITLE="$2"; shift 2 ;;
                *) FILE="$1"; shift ;;
            esac
        done
        [ -n "$FILE" ] || { err "缺少 PDF 路径"; exit 2; }
        [ -f "$FILE" ] || { err "文件不存在: $FILE"; exit 2; }
        NB_ID=$(resolve_notebook "$NB")
        [ -n "$TITLE" ] || TITLE="$(basename "$FILE" .pdf)"

        # 检查 MinerU 可用性
        if ! curl -sf --max-time 5 "$MINERU_URL/health" >/dev/null 2>&1; then
            warn "MinerU ($MINERU_URL) 不可用, PDF 将直接上传 ON (ON 内置解析可能丢失表格/公式)"
            RESP=$(on_req POST "/sources" -F "type=upload" -F "file=@$FILE" \
                $([ -n "$NB_ID" ] && echo "-F notebook_id=$NB_ID") -F "title=$TITLE" 2>&1) || { err "上传失败: $RESP"; exit 1; }
            SID=$(echo "$RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('id',''))" 2>/dev/null || echo "")
            [ -n "$SID" ] && log "✅ (无 MinerU) 已入库: $SID"
            echo "$SID"; exit 0
        fi

        # MinerU 解析
        log "MinerU 解析 PDF: $FILE (这一步较慢, 请等待...)"
        MD_CONTENT=$(curl -sf --max-time 600 -X POST "$MINERU_URL/file_parse" \
            -F "file=@$FILE" 2>/dev/null \
            | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    # mineru-api 返回 md 字段或 pages 列表
    if 'md' in d:
        print(d['md'])
    elif 'pages' in d:
        print('\n\n'.join(p.get('md','') for p in d['pages']))
    else:
        print(json.dumps(d, ensure_ascii=False))
except Exception as e:
    sys.stdin.seek(0); print(sys.stdin.read())
" 2>/dev/null || echo "")
        [ -n "$MD_CONTENT" ] || { err "MinerU 解析失败或返回空"; exit 1; }

        log "  ✅ MinerU 解析完成 ($(echo "$MD_CONTENT" | wc -l | tr -d ' ') 行 markdown)"
        log "  存入 ON (作为文本源, 同时上传原 PDF 备份)..."

        # 先存解析后的 markdown 为文本源 (这样 RAG 检索质量高)
        printf '%s' "$MD_CONTENT" | on_req POST "/sources" \
            -F "type=text" \
            -F "content=@-" \
            -F "embed=true" \
            -F "async_processing=true" \
            $([ -n "$NB_ID" ] && echo "-F notebook_id=$NB_ID") \
            -F "title=$TITLE (MinerU解析)" > /tmp/ingest_pdf_resp.txt 2>&1 || {
            err "文本源存入失败"; cat /tmp/ingest_pdf_resp.txt; exit 1
        }
        SID=$(cat /tmp/ingest_pdf_resp.txt | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('id',''))" 2>/dev/null || echo "")

        # 再上传原 PDF 作为备份 source (不强制 embedding, 供下载)
        on_req POST "/sources" \
            -F "type=upload" \
            -F "file=@$FILE" \
            -F "embed=false" \
            $([ -n "$NB_ID" ] && echo "-F notebook_id=$NB_ID") \
            -F "title=$TITLE (原PDF)" >/dev/null 2>&1 || warn "原 PDF 备份上传失败 (非致命)"

        [ -n "$SID" ] && log "✅ PDF 已入库: $SID (MinerU解析文本 + 原PDF备份)"
        echo "$SID"
        ;;

    ask)
        Q=""; NB=""
        while [ $# -gt 0 ]; do
            case "$1" in
                --notebook) NB="$2"; shift 2 ;;
                *) Q="$1"; shift ;;
            esac
        done
        [ -n "$Q" ] || { err "缺少问题"; exit 2; }
        NB_ID=$(resolve_notebook "$NB")
        log "RAG 问答: $Q"

        # 拿默认 chat 模型 ID (ask/simple 需要 strategy/answer/final_answer 三个模型)
        CHAT_MODEL=$(on_req GET "/models/defaults" 2>/dev/null \
            | python3 -c "import sys,json;print(json.load(sys.stdin).get('default_chat_model',''))" 2>/dev/null || echo "")
        [ -n "$CHAT_MODEL" ] || { err "无法获取 ON 默认模型 (检查 /api/models/defaults)"; exit 1; }

        # ask/simple 端点: POST /api/search/ask/simple, 返回 JSON (非 SSE)
        ASK_BASE=$(on_base_path)
        # 构造 JSON payload (用 python 避免转义地狱)
        PAYLOAD=$(python3 -c "
import json,sys
q='''$Q'''
d={'question':q,'strategy_model':'$CHAT_MODEL','answer_model':'$CHAT_MODEL','final_answer_model':'$CHAT_MODEL'}
${NB_ID:+d['notebook_id']='$NB_ID'}
print(json.dumps(d,ensure_ascii=False))
" 2>/dev/null || echo "{\"question\":\"$Q\",\"strategy_model\":\"$CHAT_MODEL\",\"answer_model\":\"$CHAT_MODEL\",\"final_answer_model\":\"$CHAT_MODEL\"}")

        RESP=$(curl -s --max-time 120 -X POST "$ON_URL$ASK_BASE/search/ask/simple" \
            $(on_auth_header) \
            -H "Content-Type: application/json" \
            -d "$PAYLOAD" 2>/dev/null)
        ANSWER=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('answer',''))" 2>/dev/null || echo "")
        if [ -n "$ANSWER" ]; then
            echo "$ANSWER"
        else
            echo "[无回答] ON 响应: $RESP" | head -c 300
        fi
        ;;

    help|--help|-h)
        cat <<'EOF'
ingest.sh — 知识入库 (Open Notebook + MinerU)

子命令:
  url <URL> [--notebook ID] [--title T]      抓取网页存入 ON
  file <path> [--notebook ID] [--title T]    上传文件 (PDF 自动走 MinerU)
  text <text|-> [--notebook ID] [--title T]  存入文本 (- 从 stdin)
  pdf <path> [--notebook ID] [--title T]     PDF 专用 (MinerU 解析 + 原文备份)
  ask <question> [--notebook ID]             RAG 问答
  notebooks                                  列出 notebook
  sources [--notebook ID]                    列出 source
  probe                                      探测 ON 版本 + 端点 + MinerU

环境变量 (从 .env 读):
  OPEN_NOTEBOOK_URL          默认 http://localhost:5055
  OPEN_NOTEBOOK_PASSWORD     空=无密码 (本机默认)
  MINERU_API_URL             默认 http://localhost:18080 (PDF 解析)

PDF 处理逻辑:
  MinerU 可用 → MinerU 解析为 markdown 存为文本源 (RAG质量高) + 原PDF备份
  MinerU 不可用 → 直接上传 ON (ON 内置解析, 可能丢表格/公式)
EOF
        ;;

    *)
        err "未知子命令: $CMD (用 help 查看用法)"
        exit 2
        ;;
esac
