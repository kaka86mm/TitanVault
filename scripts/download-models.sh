#!/usr/bin/env bash
# scripts/download-models.sh
# 读 models/models.yaml, 按 MODEL_SOURCE (modelscope/hf) 下载全部模型到 DATA_DIR。
#
# install.sh Phase 4 调用。带进度 (modelscope/hf 自带), 失败一个不阻断其它。
#
# 用法:
#   MODEL_SOURCE=modelscope DATA_DIR=/data bash scripts/download-models.sh
set -euo pipefail

# 需要 yq 解析 yaml; install.sh Phase 3 已装。
command -v yq >/dev/null || { echo "[models] 需要 yq, 请先安装: pip install yq 或用下载脚本自带的 python 解析"; exit 1; }

MODEL_SOURCE="${MODEL_SOURCE:-modelscope}"
DATA_DIR="${DATA_DIR:-/data}"
# ⚠️ 必须 export: envsubst 渲染 models.yaml 的 ${DATA_DIR} 时在子进程, 只看 export 变量
export MODEL_SOURCE DATA_DIR
# 用脚本自身位置定位 models.yaml, 避免 CWD 依赖 (curl|bash 从任意目录跑)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_YML="${MODELS_YML:-${SCRIPT_DIR}/../models/models.yaml}"

log() { echo -e "\033[1;32m[models]\033[0m $*"; }

# 确保下载 SDK 已装。modelscope 模式: modelscope SDK (asr/embed/mineru) + huggingface_hub (llm MTP 仅 HF 有)。
# hf 模式: 只需 huggingface_hub。
# 注意 PEP 668: Ubuntu 24.04+/Python 3.12+ 的 pip 拒绝直接装系统 python, 要 --break-system-packages。
log "检查下载 SDK..."
PIP_INSTALL="pip3 install --break-system-packages"
ensure_sdk() {
    local pkg="$1"
    python3 -c "import ${pkg/-/_}" 2>/dev/null || $PIP_INSTALL "$pkg" >/dev/null 2>&1 || sudo $PIP_INSTALL "$pkg" >/dev/null 2>&1 || { echo "[models] ✗ $pkg 安装失败, 请手动: pip3 install --break-system-packages $pkg"; exit 1; }
}
case "$MODEL_SOURCE" in
    modelscope) ensure_sdk modelscope; ensure_sdk huggingface_hub ;;
    hf) ensure_sdk huggingface_hub ;;
esac

log "源: $MODEL_SOURCE | 数据目录: $DATA_DIR | 清单: $MODELS_YML"
log "下载以下模型:"

# 下载单个 repo, 失败不阻断。modelscope/hf 的 snapshot_download 会建 cache_dir/<org>/<repo>/ 嵌套结构。
download_repo() {
    local src="$1" dest="$2" source_type="${3:-$MODEL_SOURCE}" allow="${4:-}"
    # allow 用环境变量传给 python (MOZIN_ALLOW_PATTERNS), 避免 python3 -c 的引号转义地狱
    export MOZIN_ALLOW_PATTERNS="$allow"
    case "$source_type" in
        modelscope)
            python3 -c "
import os
from modelscope import snapshot_download
kw = {}
if os.environ.get('MOZIN_ALLOW_PATTERNS'):
    kw['allow_patterns'] = os.environ['MOZIN_ALLOW_PATTERNS'].split(',')
snapshot_download('$src', cache_dir='$dest', **kw)" 2>&1 ;;
        hf)
            # 国内 HF 加速: hf-mirror.com (MODEL_SOURCE=modelscope 时 llm 也走这里)
            export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
            python3 -c "
import os
from huggingface_hub import snapshot_download
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
kw = {'endpoint': os.environ['HF_ENDPOINT']}
if os.environ.get('MOZIN_ALLOW_PATTERNS'):
    kw['allow_patterns'] = os.environ['MOZIN_ALLOW_PATTERNS'].split(',')
snapshot_download('$src', cache_dir='$dest', **kw)" 2>&1 ;;
    esac
}

# 把 cache_dir 下深层的 gguf 文件软链到 dest 根目录, 让 llama.cpp systemd 模板的扁平路径能找到。
# (snapshot_download 会下载到 dest/<org>/<repo>/<file>.gguf, systemd 期望 dest/<file>.gguf)
link_gguf_to_dest_root() {
    local dest="$1"
    find "$dest" -name '*.gguf' -type f | while read -r gguf; do
        local base target
        base=$(basename "$gguf")
        target="$dest/$base"
        if [ "$gguf" != "$target" ] && [ ! -e "$target" ]; then
            ln -sf "$gguf" "$target"
            log "  软链: $base → ${gguf#$dest/}"
        fi
    done
}

# 遍历每类模型
for kind in $(yq -r '.models | keys[]' "$MODELS_YML"); do
    name=$(yq -r ".models.${kind}.name" "$MODELS_YML")
    dest=$(yq -r ".models.${kind}.dest" "$MODELS_YML" | envsubst)
    # llm (MTP 版) 仅 HF 有, modelscope 无 → 强制走 HF (hf-mirror 加速)
    # 其余模型按 MODEL_SOURCE 选
    if [ "$kind" = "llm" ]; then
        src=$(yq -r ".models.${kind}.sources.hf" "$MODELS_YML")
        effective_source="hf"
        # 只下目标量化文件 (避免下整个仓库几百GB)。从 models.yaml 读 filename。
        llm_file=$(yq -r ".models.${kind}.filename" "$MODELS_YML")
        mmproj_file=$(yq -r ".models.${kind}.extras[0].filename" "$MODELS_YML" 2>/dev/null)
        LLM_ALLOW="$llm_file"
        [ "$mmproj_file" != "null" ] && [ -n "$mmproj_file" ] && LLM_ALLOW="$LLM_ALLOW,$mmproj_file"
        log "→ [$kind] $name (MTP 版仅 HF, 走 hf-mirror) 从 $src → $dest (仅 $LLM_ALLOW)"
    else
        src=$(yq -r ".models.${kind}.sources.${MODEL_SOURCE}" "$MODELS_YML")
        effective_source="$MODEL_SOURCE"
        LLM_ALLOW=""
    fi
    [ "$src" = "null" ] && { log "⚠️  $kind 无源, 跳过"; continue; }

    mkdir -p "$dest"
    [ "$kind" != "llm" ] && log "→ [$kind] $name 从 $src → $dest"

    download_repo "$src" "$dest" "$effective_source" "${LLM_ALLOW:-}" || { log "⚠️  $kind 下载失败, 继续其它模型"; continue; }

    # gguf 类 (llm/embed): 软链到 dest 根, 让 systemd 扁平路径能找到
    case "$kind" in
        llm|embed) link_gguf_to_dest_root "$dest" ;;
    esac

    # rerank: HF 原版需 convert_hf_to_gguf.py 转 GGUF (Qwen3-Reranker 无 GGUF 发布)
    # ⚠️ convert_hf_to_gguf.py 在 Phase 5 build.sh 安装到 /opt/llama.cpp/。
    #    Phase 4 下载模型时 llama.cpp 可能还没编译 → 转换会跳过 (warn)。
    #    Phase 5 build 完成后会重试转换 (见 install.sh phase5 rerank 模型检查段)。
    needs_convert=$(yq -r ".models.${kind}.needs_convert // false" "$MODELS_YML")
    if [ "$needs_convert" = "true" ]; then
        outfile=$(yq -r ".models.${kind}.filename" "$MODELS_YML")
        outpath="$dest/$outfile"
        if [ -f "$outpath" ]; then
            log "  $outfile 已存在, 跳过转换"
        else
            log "  转换 HF → GGUF: $outfile"
            # 找 convert 脚本 (/opt/llama.cpp 优先, build.sh 安装位置)
            convert_script=""
            for cs in /opt/llama.cpp/convert_hf_to_gguf.py /tmp/llama.cpp-build/convert_hf_to_gguf.py; do
                [ -f "$cs" ] && convert_script="$cs" && break
            done
            if [ -n "$convert_script" ]; then
                # HF 原版下载在 dest 下子目录, 找 config.json 定位模型目录
                model_dir=$(find "$dest" -name "config.json" -exec dirname {} \; 2>/dev/null | head -1)
                if [ -n "$model_dir" ]; then
                    # convert 脚本需 gguf-py (import gguf) + conversion 包 (b9840+ import conversion)
                    # _cs_dir 同时含 gguf-py/ 和 conversion/, 放 PYTHONPATH 第一位即可两者都找到
                    local _cs_dir=$(dirname "$convert_script")
                    PYTHONPATH="${_cs_dir}:${_cs_dir}/gguf-py" python3 "$convert_script" "$model_dir" --outtype f16 --outfile "$outpath" 2>&1 | tail -2 \
                        && log "  ✓ 转换完成: $outfile" \
                        || log "  ⚠️ 转换失败, rerank 服务将无法启动"
                else
                    log "  ⚠️ 未找到模型目录 (config.json), 跳过转换"
                fi
            else
                log "  ⚠️ 未找到 convert_hf_to_gguf.py (Phase 5 编译 llama.cpp 后会重试)"
            fi
        fi
    fi

    # extras (VAD/mmproj 等)。llm 的 mmproj 已在主下载 allow_patterns 里下了, 跳过避免重复。
    if [ "$kind" != "llm" ]; then
        extras_n=$(yq -r ".models.${kind}.extras | length" "$MODELS_YML")
        if [ "$extras_n" != "0" ] && [ "$extras_n" != "null" ]; then
            for i in $(seq 0 $((extras_n-1))); do
                ename=$(yq -r ".models.${kind}.extras[$i].name" "$MODELS_YML")
                esrc=$(yq -r ".models.${kind}.extras[$i].${MODEL_SOURCE}" "$MODELS_YML")
                log "  → extra: $ename 从 $esrc"
                download_repo "$esrc" "$dest" "$MODEL_SOURCE" || log "⚠️  $ename 失败"
            done
        fi
    fi
done

log "✅ 模型下载完成 (gguf 已软链到扁平路径, 供 llama.cpp systemd 加载)"
