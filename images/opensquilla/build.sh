#!/usr/bin/env bash
# images/opensquilla/build.sh
# OpenSquilla 没有 pre-built 镜像, 从 GitHub 源码 build。
# SquillaRouter 的模型资产用 Git LFS 存储 (~76MB), clone 后需 lfs pull。
#
# 用法: bash images/opensquilla/build.sh [镜像名]
# 依赖: git, git-lfs, docker (install.sh Phase4 会确保 git-lfs 已装)
set -euo pipefail

IMAGE="${1:-opensquilla:local}"
WORKDIR="${WORKDIR:-/tmp/opensquilla-build}"
# OpenSquilla 仓库 (多源 fallback, github 直连国内常超时)
REPO_URL="${OPENSQUILLA_REPO:-https://github.com/opensquilla/opensquilla.git}"

echo "[opensquilla-build] 镜像: $IMAGE"

# --- 1. clone (多镜像源 fallback) ---
if [ -d "$WORKDIR/.git" ] && [ -f "$WORKDIR/Dockerfile" ]; then
    echo "[opensquilla-build] 已有源码 $WORKDIR, 跳过 clone"
else
    rm -rf "$WORKDIR"
    mkdir -p "$WORKDIR"
    cloned=no
    for mirror in \
        "$REPO_URL" \
        "https://gh-proxy.com/$REPO_URL" \
        "https://ghfast.top/$REPO_URL"; do
        echo "[opensquilla-build] 试 clone: $mirror"
        if git clone --depth 1 "$mirror" "$WORKDIR" 2>/dev/null; then
            cloned=yes; break
        fi
    done
    [ "$cloned" = yes ] || { echo "[opensquilla-build] ✗ 所有镜像源 clone 失败"; exit 1; }
fi

# --- 2. git lfs pull (SquillaRouter 模型, ~76MB) ---
cd "$WORKDIR"
if ! git lfs version >/dev/null 2>&1; then
    echo "[opensquilla-build] ✗ git-lfs 未安装 (apt install git-lfs)"; exit 1
fi
# 检查模型是否已是真实文件 (非 LFS pointer)
MODEL_BIN="src/opensquilla/squilla_router/models/v4.2_phase3_inference/lgbm_main.bin"
if [ -f "$MODEL_BIN" ] && [ "$(wc -c <"$MODEL_BIN")" -gt 1000 ]; then
    echo "[opensquilla-build] 模型资产已是真实文件, 跳过 lfs pull"
else
    echo "[opensquilla-build] git lfs pull (SquillaRouter 模型)..."
    git lfs pull
fi

# --- 3. docker build ---
echo "[opensquilla-build] docker build..."
docker build -t "$IMAGE" .
echo "[opensquilla-build] ✓ 完成: $IMAGE"
