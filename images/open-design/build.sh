#!/usr/bin/env bash
# images/open-design/build.sh
# Open Design 的 ghcr.io/nexu-io/od:latest 镜像实际未发布 (401 unauthorized),
# 从 GitHub 源码 build。多阶段 build (node:24-alpine + pnpm + Next.js), 较慢 (~5-10 分钟)。
#
# 用法: bash images/open-design/build.sh [镜像名]
set -euo pipefail

IMAGE="${1:-open-design:local}"
WORKDIR="${WORKDIR:-/tmp/open-design-build}"
REPO_URL="${OPEN_DESIGN_REPO:-https://github.com/nexu-io/open-design.git}"

echo "[open-design-build] 镜像: $IMAGE"

# --- 1. clone (多镜像源 fallback) ---
if [ -d "$WORKDIR/.git" ] && [ -f "$WORKDIR/deploy/Dockerfile" ]; then
    echo "[open-design-build] 已有源码 $WORKDIR, 跳过 clone"
else
    rm -rf "$WORKDIR"
    cloned=no
    for mirror in \
        "$REPO_URL" \
        "https://gh-proxy.com/$REPO_URL" \
        "https://ghfast.top/$REPO_URL"; do
        echo "[open-design-build] 试 clone: $mirror"
        if git clone --depth 1 "$mirror" "$WORKDIR" 2>/dev/null; then
            cloned=yes; break
        fi
    done
    [ "$cloned" = yes ] || { echo "[open-design-build] ✗ 所有镜像源 clone 失败"; exit 1; }
fi

# --- 2. docker build (context=仓库根, dockerfile=deploy/Dockerfile) ---
echo "[open-design-build] docker build (多阶段 pnpm + Next.js, 约 5-10 分钟)..."
docker build -t "$IMAGE" -f "$WORKDIR/deploy/Dockerfile" "$WORKDIR"
echo "[open-design-build] ✓ 完成: $IMAGE"
