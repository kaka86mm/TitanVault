#!/usr/bin/env bash
# native/hermes/install.sh — 安装 Hermes Agent 到宿主机原生 (非容器)
#
# 为什么原生而非 Docker: Hermes 是运维 agent, 需要完整宿主机能力
# (docker CLI, systemctl, 网络, 文件系统)。容器化需挂 docker.sock/host-gateway
# 等绕路手段, 且 docker compose 插件不兼容。原生部署天然拥有全部能力。
#
# 用法:
#   sudo bash native/hermes/install.sh            # 默认装到 /opt/hermes
#   HERMES_VERSION=0.17.0 bash native/hermes/install.sh
set -euo pipefail

INSTALL_DIR="${1:-/opt/hermes}"
HERMES_VERSION="${HERMES_VERSION:-0.17.0}"
VENV_DIR="${INSTALL_DIR}/.venv"

log() { echo -e "\033[1;32m[hermes-install]\033[0m $*"; }
err() { echo -e "\033[1;31m[错误]\033[0m $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || err "请用 sudo 运行: sudo -E bash native/hermes/install.sh"

# 幂等: 已装则跳过
if [ -x "${VENV_DIR}/bin/hermes" ]; then
    log "Hermes 已安装在 ${VENV_DIR}, 跳过"
    exit 0
fi

log "[1/4] 安装 Python 依赖 (python3-venv)..."
apt-get update -qq
# Python 3.13: hermes-agent 要求 >=3.11,<3.14。Ubuntu 26.04 自带 3.14, 24.04 自带 3.12。
# 需 deadsnakes PPA 装 3.13。
if ! command -v python3.13 >/dev/null 2>&1; then
    log "  添加 deadsnakes PPA (装 Python 3.13)..."
    apt-get install -y -qq software-properties-common >/dev/null 2>&1 || true
    add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
    apt-get update -qq
fi
apt-get install -y -qq python3.13 python3.13-venv python3.13-dev >/dev/null 2>&1 || true

log "[2/4] 创建 venv ${VENV_DIR}..."
python3.13 -m venv "${VENV_DIR}" 2>/dev/null || python3 -m venv "${VENV_DIR}"

log "[3/4] 安装 hermes-agent (国内 PyPI 镜像 fallback)..."
# 国内 PyPI 加速; 失败则回退官方源
for index_url in \
    "https://pypi.tuna.tsinghua.edu.cn/simple" \
    "https://mirrors.aliyun.com/pypi/simple" \
    "https://pypi.org/simple"; do
    log "  尝试 PyPI 源: ${index_url}"
    if "${VENV_DIR}/bin/pip" install --quiet --upgrade pip \
        && "${VENV_DIR}/bin/pip" install --quiet "hermes-agent==${HERMES_VERSION}" \
            -i "${index_url}" 2>&1; then
        log "  ✅ 安装成功"
        break
    fi
    log "  ⚠️ 该源失败, 尝试下一个"
done

# 验证安装
if ! "${VENV_DIR}/bin/hermes" --version >/dev/null 2>&1; then
    err "hermes-agent 安装失败。检查网络/PyPI 源, 或手动: ${VENV_DIR}/bin/pip install hermes-agent"
fi

log "[4/5] 安装 hindsight client 依赖 (长期记忆后端)..."
# hindsight-all 含记忆系统 (embedded PostgreSQL 等不装, 用外部 hindsight 容器)
# 只装 hindsight client 连接外部容器 (localhost:8888)
"${VENV_DIR}/bin/pip" install --quiet hindsight-client \
    -i "https://pypi.tuna.tsinghua.edu.cn/simple" 2>/dev/null \
    && log "  ✅ hindsight-client 已装" \
    || log "  ⚠️ hindsight-client 安装失败 (记忆后端将不可用)"

log "[5/5] 安装 browser-use 浏览器自动化 (数字员工能力)..."
# browser-use (browser-harness): Hermes 的 browser toolset 底层引擎。
# 经 CDP 连接宿主机 Chrome (chrome-cdp.service, :9222), 实现点击/填表/导航/截图。
# snap chromium 不兼容 CDP, 必须用 Google Chrome .deb 版。
log "  装 Google Chrome (.deb, 非 snap)..."
if ! command -v google-chrome-stable >/dev/null 2>&1; then
    wget -q "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb" -O /tmp/chrome.deb
    apt-get install -y -qq /tmp/chrome.deb >/dev/null 2>&1 && rm -f /tmp/chrome.deb \
        && log "  ✅ Google Chrome 已装" \
        || log "  ⚠️ Chrome 安装失败 (browser-use 将不可用)"
else
    log "  Google Chrome 已装, 跳过"
fi

log "  装 browser-use (browser-harness) 到 Hermes venv..."
if "${VENV_DIR}/bin/pip" install --quiet "browser-use>=0.13.0" \
    -i "https://pypi.tuna.tsinghua.edu.cn/simple" 2>/dev/null; then
    log "  ✅ browser-use 已装"
    # ⚠ browser-use 降级 openai/pydantic/rich, 恢复 Hermes 要求的版本 (兼容)
    "${VENV_DIR}/bin/pip" install --quiet \
        "openai==2.24.0" "pydantic==2.13.4" "rich==14.3.3" 2>/dev/null || true
    log "  ✅ 依赖版本已修正"
else
    log "  ⚠️ browser-use 安装失败 (浏览器自动化将不可用)"
fi

# agent-browser (Node.js): Hermes gateway 模式 (门户 AI 助手经 API 调用) 的浏览器后端。
# 与 Python browser-use (CLI 模式) 互补。Hermes 首次调用时 npx 自动下载, 但国内 npm 源慢,
# 这里预装到缓存避免首次超时。HOME 指向 hermes 数据目录 (npx 缓存在 ~/.npm/_npx)。
log "  预装 agent-browser (Node.js, gateway 模式浏览器后端)..."
HERMES_HOME="${DATA_DIR:-/data}/hermes"
if command -v npx >/dev/null 2>&1; then
    # 国内 npm 源加速
    npm config set registry "https://registry.npmmirror.com" 2>/dev/null || true
    HOME="$HERMES_HOME" timeout 120 npx --yes agent-browser@latest --version >/dev/null 2>&1 \
        && log "  ✅ agent-browser 已预装" \
        || log "  ⚠️ agent-browser 预装失败 (首次 gateway 调用会自动重试)"
else
    log "  ⚠️ 无 npx (Node.js), 跳过 agent-browser 预装"
fi

log "✅ Hermes Agent 安装完成: ${VENV_DIR}"
log "   版本: $("${VENV_DIR}/bin/hermes" --version 2>&1)"
log "   服务模板: native/hermes/hermes-*.service.tpl"
log "   下一步: install.sh Phase 5 用 envsubst 渲染模板并注册 systemd"
