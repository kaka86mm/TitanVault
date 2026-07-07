#!/usr/bin/env bash
# native/llama.cpp/build-rocm.sh
# 编译 llama.cpp with ROCm 7.2 后端 (AMD gfx1151 / Radeon 8060S)。
#
# ROCm 版比 Vulkan 快 ~30-50% (MMQ patch #21284 + native HIP kernel)。
# 产物安装到 /opt/llama.cpp-rocm72/, 与 Vulkan 版 /opt/llama.cpp/ 并存。
#
# 前置: ROCm 7.2 SDK 已安装 (rocm-core, rocm-llvm, rocm-libs)。
# install.sh Phase 2 装 ROCm, Phase 5 调此脚本编译。
#
# 用法:
#   sudo -E bash native/llama.cpp/build-rocm.sh
#   LLAMA_VERSION=b9840 sudo -E bash native/llama.cpp/build-rocm.sh
set -euo pipefail

LLAMA_VERSION="${LLAMA_VERSION:-b9840}"
INSTALL_DIR="${1:-/opt/llama.cpp-rocm72}"
BUILD_TMP="${BUILD_TMP:-/tmp/llama.cpp-rocm-build}"

log() { echo -e "\033[1;32m[llama-rocm-build]\033[0m $*"; }
err() { echo -e "\033[1;31m[错误]\033[0m $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || err "请用 sudo 运行"

# 检查 ROCm
[ -d /opt/rocm ] || err "ROCm 未安装在 /opt/rocm"
export PATH="/opt/rocm/bin:$PATH"

log "[1/6] 安装编译依赖..."
apt-get update -qq
apt-get install -y --no-install-recommends build-essential cmake git ninja-build

log "[2/6] 克隆 llama.cpp ${LLAMA_VERSION}..."
rm -rf "${BUILD_TMP}"
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
clone_llama || err "git clone llama.cpp 全部源失败"
cd "${BUILD_TMP}"

log "[3/6] 应用 MMQ patch #21284 (gfx1151 性能优化)..."
# patch 提升 gfx1151 的 MMQ (Matrix-Matrix Quantized) kernel 性能 ~30%
# 如果 patch 已合入上游或文件不存在则跳过
if [ -f /data/patches/llama-mmq-21284.patch ]; then
    git apply /data/patches/llama-mmq-21284.patch 2>/dev/null && log "  ✅ MMQ patch 已应用" || log "  ⚠️ MMQ patch 跳过 (可能已合入上游)"
else
    log "  ⚠️ MMQ patch 文件不存在, 跳过 (可能已合入上游 ${LLAMA_VERSION})"
fi

log "[4/6] CMake 配置 (ROCm HIP + gfx1151 target)..."
# GGML_HIP=ON          启用 ROCm/HIP 后端
# AMDGPU_TARGETS=gfx1151  指定 Strix Halo GPU 架构
# GGML_NATIVE=ON       CPU 原生指令集
cmake -B build -G Ninja \
    -DGGML_HIP=ON \
    -DAMDGPU_TARGETS=gfx1151 \
    -DGGML_NATIVE=ON \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_HIP_COMPILER=/opt/rocm/bin/clang++

log "[5/6] 编译 (ninja 并行, ~15-20 分钟)..."
cmake --build build --config Release

log "[6/6] 安装到 ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
cp -r build/bin/* "${INSTALL_DIR}/" 2>/dev/null || true
cp -r build/lib/* "${INSTALL_DIR}/" 2>/dev/null || true
cp convert_hf_to_gguf.py "${INSTALL_DIR}/" 2>/dev/null || true
cp -r gguf-py "${INSTALL_DIR}/" 2>/dev/null || true
cp -r conversion "${INSTALL_DIR}/" 2>/dev/null || true

log "✅ llama.cpp (ROCm) 安装完成: ${INSTALL_DIR}"
log "   ROCm 版用于 llama-main (35B 主力), Vulkan 版 (/opt/llama.cpp) 用于 embed/rerank/quest"
