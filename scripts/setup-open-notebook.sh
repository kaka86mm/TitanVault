#!/usr/bin/env bash
# scripts/setup-open-notebook.sh — open-notebook 开箱即用配置
#
# open-notebook 启动后模型/默认配置是空的, 需手动在 UI 配。
# 本脚本通过 API 自动: 创建 4 类模型 (chat/embedding/STT/TTS) + 设默认 +
# 迁移 API key 到数据库, 全部指向本机服务 (LiteLLM/SenseVoice/Kokoro)。
#
# 在 install.sh Phase5 启动容器后调用 (幂等: 模型已存在则跳过)。
set -euo pipefail

API="${OPEN_NOTEBOOK_API:-http://localhost:5055}"
LLM_MODEL="${LLM_MODEL_NAME:-Qwen3.6-35B-A3B}"
EMBED_MODEL="${EMBED_MODEL_NAME:-Qwen3-Embedding-0.6B}"
ASR_MODEL="SenseVoiceSmall"
TTS_MODEL="kokoro"

log() { echo -e "\033[1;32m[notebook]\033[0m $*"; }

# 等待 API 就绪 (open-notebook 启动较慢: surrealdb 迁移 + supervisord 拉起 uvicorn)
# ⚠ 必须探测 /api/models (需要数据库就绪), 不能用 /api/models/providers
# (后者在端口监听但 migration 未完成时就返回 200, 导致后续创建模型 500)
log "等待 open-notebook API 就绪 (最多 180s)..."
_api_ready=false
for _ in $(seq 1 36); do
  if curl -sf --max-time 5 "$API/api/models" >/dev/null 2>&1; then _api_ready=true; break; fi
  sleep 5
done
$_api_ready || { echo "[notebook] API 180s 内未就绪, 跳过自动配置 (可后续手动跑本脚本)"; exit 0; }
# 多等 3 秒确保 migration 完全落地 (API 响应后偶尔还有写操作)
sleep 3

# 检查是否已配置 (幂等)
EXISTING=$(curl -sf --max-time 10 "$API/api/models" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    types = {m.get('type','') for m in d} if isinstance(d, list) else set()
    print(','.join(types))
except: print('')
" 2>/dev/null || echo "")

if echo "$EXISTING" | grep -q "speech_to_text"; then
  log "4 类模型已配置, 跳过"
  exit 0
fi

log "配置 open-notebook 模型 (4 类: chat/embedding/STT/TTS)..."

# 迁移环境变量 API key → 数据库 credential
log "迁移 API key 到数据库 (credential)..."
curl -sf --max-time 15 -X POST "$API/api/credentials/migrate-from-env" >/dev/null 2>&1 \
  && log "  ✓ API key 已迁移" \
  || log "  ⚠️ 迁移失败 (环境变量仍可用)"

# 获取/创建 credential, 配置分类型 endpoint
# open-notebook openai provider 支持独立 endpoint:
#   base_url (chat) + endpoint_embedding + endpoint_tts + endpoint_stt
CID=$(curl -sf --max-time 10 "$API/api/credentials/by-provider/openai" 2>/dev/null \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')" 2>/dev/null || echo "")
if [ -n "$CID" ]; then
    CRED_ENC=$(echo "$CID" | sed 's|/|%2F|g')
    log "配置 credential endpoint (chat→LiteLLM, TTS→Kokoro, STT→SenseVoice)..."
    curl -sf --max-time 15 -X PUT "$API/api/credentials/$CRED_ENC" \
      -H "Content-Type: application/json" \
      -d "{\"provider\":\"openai\",\"name\":\"LiteLLM+Kokoro+SenseVoice\",\"base_url\":\"http://litellm:4000/v1\",\"endpoint_tts\":\"http://kokoro-tts:8880/v1\",\"endpoint_stt\":\"http://sensevoice:9991/v1\"}" >/dev/null 2>&1 \
      && log "  ✓ endpoint 已配置" \
      || log "  ⚠️ endpoint 配置失败"
fi

# 创建 4 类模型
create_model() {
  local name="$1" type="$2"
  local cred="${3:-}"
  local body="{\"name\":\"$name\",\"provider\":\"openai\",\"type\":\"$type\""
  [ -n "$cred" ] && body="$body,\"credential\":\"$cred\""
  body="$body}"
  curl -sf --max-time 15 -X POST "$API/api/models" \
    -H "Content-Type: application/json" \
    -d "$body" >/dev/null 2>&1 \
    && log "  ✓ $type: $name" \
    || log "  ⚠️ 创建失败: $type/$name (可能已存在)"
}

create_model "$LLM_MODEL" "language" "$CID"
create_model "$EMBED_MODEL" "embedding" "$CID"
create_model "$ASR_MODEL" "speech_to_text" "$CID"
create_model "$TTS_MODEL" "text_to_speech" "$CID"

# 设默认模型 (全部 7 项)
log "设置默认模型..."
curl -sf --max-time 15 -X PUT "$API/api/models/defaults" \
  -H "Content-Type: application/json" \
  -d "{
    \"default_chat_model\":\"$LLM_MODEL\",
    \"default_transformation_model\":\"$LLM_MODEL\",
    \"default_embedding_model\":\"$EMBED_MODEL\",
    \"default_tools_model\":\"$LLM_MODEL\",
    \"large_context_model\":\"$LLM_MODEL\",
    \"default_speech_to_text_model\":\"$ASR_MODEL\",
    \"default_text_to_speech_model\":\"$TTS_MODEL\"
  }" >/dev/null 2>&1 \
  && log "  ✓ 默认模型已设置 (含 STT/TTS)" \
  || log "  ⚠️ 默认模型设置失败"

# 验证: 确认 4 类模型真的写进数据库 (创建可能因 migration 未完成静默失败)
VERIFY=$(curl -sf --max-time 10 "$API/api/models" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    types = {m.get('type','') for m in d} if isinstance(d, list) else set()
    print(','.join(sorted(types)))
except: print('')
" 2>/dev/null || echo "")

_missing=""
for t in language embedding speech_to_text text_to_speech; do
  echo "$VERIFY" | grep -q "$t" || _missing="$_missing $t"
done
if [ -n "$_missing" ]; then
  log "⚠️ 以下模型类型未生效:$_missing (API 可能还在初始化, 5s 后重试一次)"
  sleep 5
  for t in $_missing; do
    case "$t" in
      language) create_model "$LLM_MODEL" "language" "$CID" ;;
      embedding) create_model "$EMBED_MODEL" "embedding" "$CID" ;;
      speech_to_text) create_model "$ASR_MODEL" "speech_to_text" "$CID" ;;
      text_to_speech) create_model "$TTS_MODEL" "text_to_speech" "$CID" ;;
    esac
  done
  # 重设默认
  curl -sf --max-time 15 -X PUT "$API/api/models/defaults" \
    -H "Content-Type: application/json" \
    -d "{\"default_chat_model\":\"$LLM_MODEL\",\"default_transformation_model\":\"$LLM_MODEL\",\"default_embedding_model\":\"$EMBED_MODEL\",\"default_tools_model\":\"$LLM_MODEL\",\"large_context_model\":\"$LLM_MODEL\",\"default_speech_to_text_model\":\"$ASR_MODEL\",\"default_text_to_speech_model\":\"$TTS_MODEL\"}" >/dev/null 2>&1
fi

log "✅ open-notebook 配置完成 (4 类模型开箱即用)"
