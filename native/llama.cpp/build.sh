#!/usr/bin/env bash
# native/llama.cpp/build.sh
# 编译 llama.cpp with Vulkan 后端 (AMD gfx1151 / Radeon 8060S)。
#
# 为什么原生而非 Docker: llama-server 直连 /dev/dri 走 Vulkan, 容器化收益为负
# (见设计文档 §1)。这是发行版唯一原生编译的组件。
#
# 用法:
#   bash native/llama.cpp/build.sh [安装目录]    # 默认 /opt/llama.cpp
#   LLAMA_VERSION=b9831 bash native/llama.cpp/build.sh   # 指定版本
set -euo pipefail

# 默认值可被环境覆盖; install.sh Phase 5 会注入 hardware/aimax-395.profile 的值
LLAMA_VERSION="${LLAMA_VERSION:-b9840}"   # 最新 stable (含 Vulkan FA 修复 + DFlash/eagle3 spec 支持)
INSTALL_DIR="${1:-/opt/llama.cpp}"
BUILD_TMP="${BUILD_TMP:-/tmp/llama.cpp-build}"

log() { echo -e "\033[1;32m[llama-build]\033[0m $*"; }
err() { echo -e "\033[1;31m[错误]\033[0m $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || err "请用 sudo 运行: sudo -E bash native/llama.cpp/build.sh"

log "[1/5] 安装编译依赖 (Vulkan + ninja 加速)..."
apt-get update
apt-get install -y --no-install-recommends \
    build-essential cmake git ninja-build \
    libvulkan-dev libshaderc-dev glslang-tools spirv-tools

log "[2/5] 克隆 llama.cpp ${LLAMA_VERSION}..."
rm -rf "${BUILD_TMP}"
# 国内 github 直连不通, 多源 fallback: github → ghproxy代理 → gitee镜像 → codeload zip
clone_llama() {
    for url in \
        "https://github.com/ggml-org/llama.cpp" \
        "https://ghfast.top/https://github.com/ggml-org/llama.cpp" \
        "https://gh-proxy.com/https://github.com/ggml-org/llama.cpp" \
        "https://gitee.com/mirrors/llama.cpp"; do
        log "  尝试: ${url}"
        if git clone --depth 1 --branch "${LLAMA_VERSION}" "$url" "${BUILD_TMP}" 2>/dev/null; then
            log "  ✅ 克隆成功"; return 0
        fi
        rm -rf "${BUILD_TMP}" 2>/dev/null
    done
    return 1
}
clone_llama || err "git clone llama.cpp 全部源失败。国内需配代理或 ghproxy, 见 docs/troubleshooting.md"
cd "${BUILD_TMP}"

log "[3/5] CMake 配置 (Vulkan + native 指令集优化)..."
# GGML_VULKAN=ON      启用 Vulkan 后端 (gfx1151 走此路径)
# GGML_NATIVE=ON      启用 CPU 原生指令集 (AVX 等, 提升 CPU fallback)
# CMAKE_BUILD_TYPE=Release  去断言/调试符号
cmake -B build -G Ninja \
    -DGGML_VULKAN=ON \
    -DGGML_NATIVE=ON \
    -DCMAKE_BUILD_TYPE=Release

log "[4/5] 编译 (ninja 并行, ~10-15 分钟)..."
cmake --build build --config Release

log "[5/5] 安装到 ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
# llama.cpp 的产物在 build/bin/ (server / bench 等)
cp -r build/bin/* "${INSTALL_DIR}/"
# convert_hf_to_gguf.py: reranker 模型转换需要 (HF 原版 → GGUF)
cp convert_hf_to_gguf.py "${INSTALL_DIR}/" 2>/dev/null || true
# gguf-py 依赖 (convert_hf_to_gguf.py import gguf)
cp -r gguf-py "${INSTALL_DIR}/" 2>/dev/null || true
# conversion 包: b9840+ 重构后 convert_hf_to_gguf.py import conversion (各模型转换器)
# 不复制会 ModuleNotFoundError: No module named 'conversion'
cp -r conversion "${INSTALL_DIR}/" 2>/dev/null || true

log "✅ llama.cpp 安装完成: ${INSTALL_DIR}"
log "   服务模板: native/llama.cpp/llama-main.service.tpl / llama-embed.service.tpl"
log "   下一步: install.sh Phase 5 用 envsubst 渲染模板并注册 systemd"
