#!/usr/bin/env bash
# native/opensquilla/install.sh — 安装 OpenSquilla 到宿主机原生 (非容器)
#
# 为什么原生而非 Docker: OpenSquilla 用于写代码/改项目源码, 需要访问宿主机
# 文件系统、git、build 工具。容器化访问不了宿主机项目目录。
#
# 注意: PyPI 上 opensquilla 只有 0.3.0 (旧), 最新 v0.4.1 需从 GitHub 源码装。
#
# 用法:
#   sudo bash native/opensquilla/install.sh          # 默认装到 /opt/opensquilla
set -euo pipefail

INSTALL_DIR="${1:-/opt/opensquilla}"
VENV_DIR="${INSTALL_DIR}/.venv"
OSQ_VERSION="${OSQ_VERSION:-0.4.1}"
DATA_DIR="${OPENSQUILLA_DATA:-/data/opensquilla}"

log() { echo -e "\033[1;32m[opensquilla-install]\033[0m $*"; }
err() { echo -e "\033[1;31m[错误]\033[0m $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || err "请用 sudo 运行: sudo -E bash native/opensquilla/install.sh"

# 幂等
if [ -x "${VENV_DIR}/bin/opensquilla" ]; then
    log "OpenSquilla 已安装在 ${VENV_DIR}, 跳过"
    exit 0
fi

log "[1/5] 安装系统依赖 (Python 3.13 + git)..."
apt-get update -qq
# Python 3.13: Ubuntu 26.04 自带 3.14, Ubuntu 24.04 自带 3.12, 都需 deadsnakes PPA 装 3.13
if ! command -v python3.13 >/dev/null 2>&1; then
    log "  添加 deadsnakes PPA (装 Python 3.13)..."
    apt-get install -y -qq software-properties-common >/dev/null 2>&1 || true
    add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
    apt-get update -qq
fi
apt-get install -y -qq python3.13 python3.13-venv python3.13-dev git >/dev/null 2>&1 || true

log "[2/5] 下载 OpenSquilla v${OSQ_VERSION} 源码..."
# PyPI 版本旧 (0.3.0), 从 GitHub tarball 装 v0.4.1
# 国内 github 直连不通, 多源 fallback (与 llama.cpp build.sh 一致)
TMP_DIR="/tmp/opensquilla-${OSQ_VERSION}"
rm -rf "$TMP_DIR"
for url in \
    "https://codeload.github.com/opensquilla/opensquilla/tar.gz/refs/tags/v${OSQ_VERSION}" \
    "https://ghfast.top/https://github.com/opensquilla/opensquilla/archive/refs/tags/v${OSQ_VERSION}.tar.gz" \
    "https://gh-proxy.com/https://github.com/opensquilla/opensquilla/archive/refs/tags/v${OSQ_VERSION}.tar.gz" \
    "https://github.moeyy.xyz/https://github.com/opensquilla/opensquilla/archive/refs/tags/v${OSQ_VERSION}.tar.gz" \
    "https://gitee.com/mirrors/opensquilla/archive/refs/tags/v${OSQ_VERSION}.tar.gz"; do
    log "  尝试: ${url}"
    if curl -sL --max-time 120 -o /tmp/opensquilla-src.tar.gz "$url" \
        && tar xzf /tmp/opensquilla-src.tar.gz -C /tmp 2>/dev/null; then
        log "  ✅ 下载成功"
        break
    fi
done
[ -d "$TMP_DIR" ] || err "下载 OpenSquilla v${OSQ_VERSION} 失败 (国内需配代理或 ghproxy)"

log "[3/5] 创建 venv ${VENV_DIR}..."
python3.13 -m venv "${VENV_DIR}" 2>/dev/null || python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip

log "[4/5] 源码安装 opensquilla (国内 PyPI 镜像加速依赖)..."
cd "$TMP_DIR"
"${VENV_DIR}/bin/pip" install . -i https://pypi.tuna.tsinghua.edu.cn/simple 2>&1 | tail -3

# 验证
"${VENV_DIR}/bin/pip" show opensquilla 2>&1 | grep -q "Version: ${OSQ_VERSION}" \
    || err "opensquilla 安装版本不对 (期望 ${OSQ_VERSION})"

log "[5/5] 初始化数据目录..."
mkdir -p "${DATA_DIR}"

# 清理
rm -f /tmp/opensquilla-src.tar.gz
rm -rf "$TMP_DIR"

log "✅ OpenSquilla v${OSQ_VERSION} 安装完成: ${VENV_DIR}"
log "   服务模板: native/opensquilla/opensquilla.service.tpl"
