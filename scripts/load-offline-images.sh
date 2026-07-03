#!/usr/bin/env bash
# scripts/load-offline-images.sh
# 加载发行版预打包的离线镜像 (images/offline/*.tar.gz), 解决国内 docker hub 被墙、
# 镜像源对冷门镜像无缓存导致拉取失败的问题。
#
# 用法:
#   bash scripts/load-offline-images.sh              # 加载所有 tar.gz
#   bash scripts/load-offline-images.sh --check      # 只检查哪些镜像缺失, 不加载
#   bash scripts/load-offline-images.sh standard     # 只加载 standard 档包
#
# install.sh Phase3 在 docker compose pull 之前调用本脚本, 预先 load 离线镜像,
# 之后 compose up 发现镜像已存在就不再 pull (除非 --pull 强制)。
set -euo pipefail

OFFLINE_DIR="${OFFLINE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/images/offline}"
CHECK_ONLY=false
FILTER=""

usage() { echo "用法: $0 [--check] [standard|build-base|full|all]"; exit 0; }
for arg in "$@"; do
    case "$arg" in
        --check|-c) CHECK_ONLY=true ;;
        -h|--help) usage ;;
        standard|build-base|full|all) FILTER="$arg" ;;
        *) echo "未知参数: $arg"; usage ;;
    esac
done

[ -d "$OFFLINE_DIR" ] || mkdir -p "$OFFLINE_DIR"

# 自动下载缺失的离线包 (从 GitHub Release, 解决 git clone 不含大文件的问题)
# 仅在包不存在且非 --check 模式时尝试下载
GITHUB_RELEASE="${GITHUB_RELEASE:-https://github.com/kaka86mm/TitanVault/releases/download/v0.2.0}"
if [ "$CHECK_ONLY" = false ]; then
    for pkg in standard-offline-images.tar.gz build-base-offline-images.tar.gz; do
        if [ ! -f "$OFFLINE_DIR/$pkg" ]; then
            # 跳过标准档 (1.5GB 太大) 除非用户明确要求
            if [ "$pkg" = "standard-offline-images.tar.gz" ] && [ "${DOWNLOAD_STANDARD:-0}" != "1" ]; then
                echo "[offline] $pkg 未找到 (1.5GB, 不自动下载)。"
                echo "  手动下载: wget -P $OFFLINE_DIR $GITHUB_RELEASE/$pkg"
                continue
            fi
            echo "[offline] 下载 $pkg (从 GitHub Release)..."
            if curl -sfL --max-time 600 -o "$OFFLINE_DIR/$pkg" "$GITHUB_RELEASE/$pkg"; then
                echo "[offline]   ✅ $pkg 下载完成"
            else
                echo "[offline]   ⚠️ $pkg 下载失败, 跳过 (镜像源 fallback 兜底)"
                rm -f "$OFFLINE_DIR/$pkg"
            fi
        fi
    done
fi

# 统计: tar.gz 里有哪些镜像 (docker save 的 manifest), 对照本地已有, 报缺失
count_loaded=0; count_skipped=0; count_missing=0

for tarball in "$OFFLINE_DIR"/*.tar.gz; do
    [ -f "$tarball" ] || continue
    # 文件名 → 档位前缀 (standard-offline-images.tar.gz → standard; build-base-... → build-base)
    fname=$(basename "$tarball")
    base="${fname%%-offline-images.tar.gz}"
    [ -n "$FILTER" ] && [ "$FILTER" != "all" ] && [ "$base" != "$FILTER" ] && continue

    # 列出包内镜像名 (不解压, 读 manifest.json 的 RepoTags)
    # docker save 的 tar 里第一个 manifest.json 含 RepoTags。用 tar + python 提取。
    tags=$(tar xzf "$tarball" -O manifest.json 2>/dev/null \
        | python3 -c "import sys,json;[print(t) for r in json.load(sys.stdin) for t in r.get('RepoTags',[])]" 2>/dev/null || echo "")

    echo "📦 $(basename "$tarball") ($(du -h "$tarball" | cut -f1))"
    if [ -z "$tags" ]; then
        echo "   ⚠️ 无法读取包内镜像清单, 跳过"; continue
    fi

    # 检查每个镜像本地是否已有
    all_present=true
    while IFS= read -r img; do
        [ -z "$img" ] && continue
        if docker image inspect "$img" >/dev/null 2>&1; then
            echo "   ✅ 已存在 $img"
            count_skipped=$((count_skipped+1))
        else
            echo "   ❌ 缺失   $img"
            all_present=false
            count_missing=$((count_missing+1))
        fi
    done <<< "$tags"

    # --check 模式不加载
    if $CHECK_ONLY; then continue; fi
    # 全都有就不重复 load (省时间)
    if $all_present; then
        echo "   (全部已存在, 跳过加载)"
        continue
    fi

    echo "   加载中..."
    if docker load -i "$tarball" >/dev/null 2>&1; then
        echo "   ✅ 加载完成"
        count_loaded=$((count_loaded+1))
    else
        echo "   ⚠️ 加载失败 (docker load 出错)"
    fi
done

echo ""
echo "统计: 加载 $count_loaded 个包, 跳过 $count_skipped (已存在), 缺失 $count_missing"
[ "$count_missing" -gt 0 ] && $CHECK_ONLY && echo "提示: 运行 $0 (不带 --check) 加载离线镜像"
exit 0
