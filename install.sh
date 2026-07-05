#!/usr/bin/env bash
# install.sh — TitanVault 一行安装器
#
# 用法:
#   curl -fsSL https://mozin.station/install | bash     # 全新安装
#   bash install.sh --resume [PHASE]                     # 断点续接 (重启后自动)
#
# 6 Phase 流程 (见设计文档 §4):
#   Phase 0: 硬件检测 (必须 gfx1151 + Ubuntu)
#   Phase 1: 交互式配置 + 生成 .env (密码自动随机)
#   Phase 2: GPU 驱动 (GRUB + Mesa + Vulkan, 需重启一次)
#   Phase 3: Docker + 镜像 (build mineru-rocm + pull 第三方)
#   Phase 4: 模型下载 (init, 断点续传)
#   Phase 5: 启动 (编译 llama.cpp + compose up + systemd)
#   Phase 6: 完成 + 引导
#
# 断点续接: 每完成一个 Phase 写 state.json; crontab @reboot 在 Phase 2 重启后自动续。
set -euo pipefail

# ===== 全局 =====
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${HOME}/.mozin-workstation"
STATE_FILE="${STATE_DIR}/state.json"
CONFIG_DIR="${REPO_DIR}/config"
mkdir -p "$STATE_DIR"

log() { echo -e "\033[1;32m[mozin]\033[0m $*"; }
warn() { echo -e "\033[1;33m[注意]\033[0m $*" >&2; }
err() { echo -e "\033[1;31m[错误]\033[0m $*" >&2; exit 1; }

need_root_check() {
    # 大部分 Phase 需要 sudo, 但不在脚本顶层要求, 而是各命令内 sudo (避免 pipe 丢权限)
    [ "$(id -u)" -eq 0 ] && warn "以 root 运行, 生成的 .env 会属 root, 建议用普通用户 + sudo"
    return 0
}

# state.json: {"phase": N}
write_state() { echo "{\"phase\": $1}" > "$STATE_FILE"; }
read_state() { [ -f "$STATE_FILE" ] && python3 -c "import json;print(json.load(open('$STATE_FILE')).get('phase',0))" 2>/dev/null || echo 0; }

# 配置 docker registry-mirror (国内拉镜像加速)。
# Phase 1 选 cn 时自动配一组国内镜像源; 选 global 或已有配置则跳过 (不覆盖用户设置)。
# DOCKER_MIRRORS env 可覆盖源列表 (非交互部署用)。
# 国内 docker hub 直连必慢/必限流, 这是开箱即用的硬需求。
configure_docker_mirror() {
    local daemon_json="/etc/docker/daemon.json"
    # 已有 registry-mirrors 配置 → 不覆盖 (用户/运维已配过)
    if [ -f "$daemon_json" ] && grep -q "registry-mirrors" "$daemon_json" 2>/dev/null; then
        log "docker registry-mirror 已配置, 跳过"
        return 0
    fi
    # global 用户不配 (走 docker hub 直连)
    [ "${MODEL_SOURCE:-}" = "hf" ] && { log "global 模式, 不配国内镜像源"; return 0; }

    # 默认国内镜像源 (多源 fallback, 单源易限流/部分缓存)
    # 选源依据: 公开免费 + 实测覆盖主流镜像 (2026-06 dongyubin/DockerHub 亲测可用)
    # 顺序: 1ms.run (速度最快) → 1panel.live → xuanyuan.me → daocloud (兜底, 部分镜像 403)
    local mirrors="${DOCKER_MIRRORS:-https://docker.1ms.run,https://docker.1panel.live,https://docker.xuanyuan.me,https://docker.m.daocloud.io}"

    log "配置 docker registry-mirror (国内加速)..."
    # 用 python 生成合法 JSON (保留既有配置如 log-driver, 避免手拼出错)
    sudo python3 - "$daemon_json" "$mirrors" <<'PYEOF' || { warn "写入 daemon.json 失败, 跳过镜像加速"; return 0; }
import json, sys
daemon_json, mirrors_str = sys.argv[1], sys.argv[2]
cfg = {"registry-mirrors": mirrors_str.split(",")}
try:
    old = json.load(open(daemon_json))
    if isinstance(old, dict):
        old.update(cfg)
        cfg = old
except Exception:
    pass
json.dump(cfg, open(daemon_json, "w"), indent=2)
print("  镜像源:", " ".join(cfg["registry-mirrors"]))
PYEOF
    sudo systemctl restart docker 2>/dev/null || sudo service docker restart 2>/dev/null || warn "docker 重启失败, 镜像源下次重启生效"
    # 重启后等 daemon 回来
    for _ in $(seq 1 15); do sudo docker info >/dev/null 2>&1 && break; sleep 2; done
    log "  ✅ docker registry-mirror 配置完成"
}

# 读 .env (Phase 1 之后才有) —— export 变量, 供 envsubst 渲染模板用。
# 用独立代码块而非单行 &&/|| 链: 避免 set -a 泄漏 + 错误被吞。
load_env() {
    [ -f "$REPO_DIR/.env" ] || return 0
    set -a
    . "$REPO_DIR/.env"
    set +a
}

# source hardware profile 并 export (envsubst 在管道子进程里只看 export 变量)
load_hardware() {
    local hw="$REPO_DIR/hardware/${HARDWARE_PROFILE:-aimax-395}.profile"
    [ -f "$hw" ] || hw="$REPO_DIR/hardware/aimax-395.profile"
    set -a
    . "$hw"
    set +a
    # 生成 mmproj 参数: Qwen3.6 是原生多模态 VLM, profile 定义 LLM_MMPROJ 文件名。
    # 模型目录下有该文件 → --mmproj <path>; 无则空 (纯文本模型降级)。
    # 不传 mmproj 会导致 llama.cpp 拒绝图片输入 ("image input is not supported")。
    local _mmp="${MODEL_DIR:-/data}/models/llm/${LLM_MMPROJ:-}"
    if [ -n "${LLM_MMPROJ:-}" ] && [ -f "$_mmp" ]; then
        export MMPROJ_ARG="--mmproj ${_mmp}"
    else
        export MMPROJ_ARG=""
    fi
}

# ============================================================================
# Phase 0: 硬件检测
# ============================================================================
phase0_detect() {
    log "Phase 0: 硬件检测..."

    # GPU: 必须是 gfx1151 (Radeon 8060S)
    if [ ! -e /dev/dri/renderD128 ]; then
        err "未检测到 AMD GPU (/dev/dri/renderD128)。TitanVault 仅支持 Ryzen AI Max+ 395。"
    fi

    if command -v rocminfo >/dev/null 2>&1; then
        # 注意: rocminfo | grep 在 pipefail 下会因 SIGPIPE (grep 早退, rocminfo 写关闭管道)
        # 返回 141 误判。先存输出再 grep, 规避管道问题。
        _rocminfo_out="$(rocminfo 2>/dev/null || true)"
        if ! echo "$_rocminfo_out" | grep -q "gfx1151"; then
            err "未检测到 gfx1151 (Radeon 8060S)。当前仅支持 Ryzen AI Max+ 395。检测到的 GPU 不是目标硬件。"
        fi
        unset _rocminfo_out
        log "✅ 检测到 gfx1151 (Radeon 8060S)"
    else
        warn "rocminfo 未安装, 无法精确验证 gfx1151; 将在 Phase 2 装 Vulkan 后复核。"
    fi

    # OS: 仅 Ubuntu
    if ! grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
        err "仅支持 Ubuntu (推荐 24.04)。检测到: $(. /etc/os-release 2>/dev/null; echo "${NAME:-unknown}")"
    fi
    log "✅ Ubuntu $(. /etc/os-release; echo "$VERSION_ID")"

    # 内存 (35B 模型 + 系统建议 64GB)
    mem_gb=$(free -g | awk '/^Mem:/{print $2}')
    [ "${mem_gb:-0}" -lt 32 ] && warn "内存 ${mem_gb}GB 偏小, 建议 64GB+ 跑 35B 模型"

    write_state 0
}

# ============================================================================
# Phase 1: 交互式配置 + .env 生成
# ============================================================================
phase1_configure() {
    log "Phase 1: 交互式配置..."

    # ⚠️ 所有 read 必须 </dev/tty: curl|bash 模式下脚本 stdin 是管道 (脚本字节),
    # 直接 read 会立即读到 EOF → 静默用默认值, 交互完全不生效。
    # </dev/tty 强制从终端读, 保证 curl|bash 也能正常交互。

    # preset
    read -rp "选择安装档位 [minimal/standard/full] (默认 standard): " PRESET </dev/tty
    PRESET=${PRESET:-standard}
    case "$PRESET" in minimal|standard|full) ;; *) err "未知 preset: $PRESET" ;; esac

    # 数据目录
    read -rp "数据目录 (默认 /data): " DATA_DIR </dev/tty
    DATA_DIR=${DATA_DIR:-/data}

    # 部署用户
    DEPLOY_USER="${SUDO_USER:-$USER}"
    read -rp "部署用户 (systemd 以此跑 llama.cpp, 默认 $DEPLOY_USER): " INPUT_USER </dev/tty
    [ -n "$INPUT_USER" ] && DEPLOY_USER="$INPUT_USER"

    # 模型源
    read -rp "模型下载源 [cn=modelscope (国内快) / global=hf (全球)] (默认 cn): " REGION </dev/tty
    case "${REGION:-cn}" in cn) MODEL_SOURCE=modelscope ;; global) MODEL_SOURCE=hf ;; *) MODEL_SOURCE=modelscope ;; esac

    # 代理 / 穿透 (可跳过)
    read -rp "mihomo 订阅链接 (留空跳过代理): " MIHOMO_SUBSCRIBE_URL </dev/tty
    read -rp "frp 服务器地址 (留空跳过内网穿透): " FRP_SERVER_ADDR </dev/tty
    read -rp "frp token (留空跳过): " FRP_TOKEN </dev/tty

    # 宿主机 IP (open-notebook 回调用)
    # 395 多子网环境 hostname -I 返回多个 IP, 让用户选对外的那个
    ALL_IPS=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^$')
    HOST_IP=$(echo "$ALL_IPS" | head -1)
    if [ "$(echo "$ALL_IPS" | wc -l)" -gt 1 ]; then
        warn "检测到多个网卡 IP (多子网环境):"
        echo "$ALL_IPS" | nl
        read -rp "选择对外暴露的 IP 序号 (回车=第1个 $HOST_IP): " IP_IDX </dev/tty
        if [ -n "$IP_IDX" ]; then
            HOST_IP=$(echo "$ALL_IPS" | sed -n "${IP_IDX}p")
            [ -n "$HOST_IP" ] || HOST_IP=$(echo "$ALL_IPS" | head -1)
        fi
    else
        read -rp "宿主机对外 IP (Notebook 回调, 默认 ${HOST_IP:-未检测到}): " INPUT_IP </dev/tty
        [ -n "$INPUT_IP" ] && HOST_IP="$INPUT_IP"
    fi
    log "使用对外 IP: $HOST_IP"

    # 生成随机密码 (安装器用 openssl rand, 不问用户)
    log "生成随机密码..."
    POSTGRES_PASSWORD=$(openssl rand -hex 16)
    REDIS_PASSWORD=$(openssl rand -hex 16)
    LITELLM_MASTER_KEY="sk-$(openssl rand -hex 16)"
    QDRANT_API_KEY=$(openssl rand -hex 16)
    HERMES_API_SERVER_KEY=$(openssl rand -hex 16)
    OPEN_NOTEBOOK_SURREAL_PASSWORD=$(openssl rand -hex 16)
    OPEN_NOTEBOOK_ENCRYPTION_KEY=$(openssl rand -hex 32)
    MIHOMO_API_SECRET=$(openssl rand -hex 16)

    # 写 .env: 以 .env.example 为基底, 追加生成的值。
    # ⚠ .env.example 含空占位 (如 POSTGRES_PASSWORD=), cp 后必须删掉这些空行,
    # 否则追加的值会和空占位重复 (两行同名变量, source/env 行为不一致)。
    cp "$CONFIG_DIR/.env.example" "$REPO_DIR/.env"
    sed -i '/^[A-Z_]*=$/d' "$REPO_DIR/.env"   # 删空值占位行
    {
        echo ""
        echo "# ===== 安装器自动生成 ($(date -Iseconds), 勿手改) ====="
        echo "DEPLOY_USER=\"$DEPLOY_USER\""
        echo "DATA_DIR=\"$DATA_DIR\""
        echo "MODEL_SOURCE=$MODEL_SOURCE"
        echo "PRESET=$PRESET"
        echo "HOST_IP=\"$HOST_IP\""
        echo "POSTGRES_PASSWORD=$POSTGRES_PASSWORD"
        echo "REDIS_PASSWORD=$REDIS_PASSWORD"
        echo "LITELLM_MASTER_KEY=$LITELLM_MASTER_KEY"
        echo "QDRANT_API_KEY=$QDRANT_API_KEY"
        echo "HERMES_API_SERVER_KEY=$HERMES_API_SERVER_KEY"
        echo "OPEN_NOTEBOOK_SURREAL_PASSWORD=$OPEN_NOTEBOOK_SURREAL_PASSWORD"
        echo "OPEN_NOTEBOOK_ENCRYPTION_KEY=$OPEN_NOTEBOOK_ENCRYPTION_KEY"
        echo "MIHOMO_API_SECRET=$MIHOMO_API_SECRET"
        echo "MIHOMO_SUBSCRIBE_URL=\"$MIHOMO_SUBSCRIBE_URL\""
        echo "FRP_SERVER_ADDR=\"$FRP_SERVER_ADDR\""
        echo "FRP_TOKEN=\"$FRP_TOKEN\""
    } >> "$REPO_DIR/.env"
    chmod 600 "$REPO_DIR/.env"
    log "✅ 配置写入 $REPO_DIR/.env (权限 600)"

    # 渲染带模板变量的 config (litellm/caddy/mihomo/frp)
    render_configs

    write_state 1
}

# 渲染 config/*.tpl → 实际 config 文件 (compose 直接挂载渲染产物)。
# 必须先 load_env + load_hardware: envsubst 只替换 ${VAR} (不支持 :-default),
# 且只看 export 变量, 故所有依赖变量都要已 export。
render_configs() {
    load_env
    load_hardware
    command -v envsubst >/dev/null 2>&1 || sudo apt-get install -y gettext

    # litellm: tpl → config.yaml (compose 挂载 config.yaml, 非 .tpl)
    envsubst < "$CONFIG_DIR/litellm/config.yaml.tpl" > "$CONFIG_DIR/litellm/config.yaml"

    # caddy: Caddyfile 用 {$VAR} 语法 (Caddy 运行时从环境变量读), 不用 envsubst。
    # 直接拷贝 tpl → Caddyfile (caddy 容器从 environment 注入变量)。
    cp "$CONFIG_DIR/caddy/Caddyfile.tpl" "$CONFIG_DIR/caddy/Caddyfile"

    # mihomo/frp 模板用 ${VAR} 占位 (envsubst 渲染)
    for tpl in "$CONFIG_DIR"/mihomo/config.yaml.tpl "$CONFIG_DIR"/frp/frpc.toml.tpl; do
        out="${tpl%.tpl}"
        envsubst < "$tpl" > "$out"
    done

    # TitanVault (门户门面): build 时静态编译, 无需运行时配置渲染。
    # 服务卡片/图标/数据都在 images/titanvault-homepage/src/data.js (build 进产物)。
    # 旧的 gethomepage 配置 (services-*.yaml/icons/) 已不再使用, 保留在 config/homepage/
    # 仅供参考, 不再拷贝到 DATA_DIR。

    # searxng: settings.yml 拷到 DATA_DIR/searxng (容器挂载整个目录)
    # 不存在时才拷 (保留用户改过的); searxng 启动会补全其它运行时文件
    local sx_dir="${DATA_DIR:-/data}/searxng"
    sudo mkdir -p "$sx_dir"
    if [ ! -f "$sx_dir/settings.yml" ]; then
        sudo cp "$CONFIG_DIR/searxng/settings.yml" "$sx_dir/settings.yml"
    fi

    # hermes: config.yaml 渲染到 DATA_DIR/hermes (原生部署, HOME=此目录)
    # 指向 litellm + dashboard basic auth。不存在时才渲染 (保留用户改过的)。
    # dashboard.password_hash: 用本地 hermes python 生成 scrypt hash,
    # 明文 = HERMES_API_SERVER_KEY。hermes v0.17 非 loopback 绑定必须配 auth。
    local hermes_dir="${DATA_DIR:-/data}/hermes"
    sudo mkdir -p "$hermes_dir"
    if [ ! -f "$hermes_dir/config.yaml" ]; then
        log "生成 hermes config.yaml (含 dashboard auth hash)..."
        # 用本地 hermes python 生成 scrypt password hash (原生部署, 不依赖 docker run)
        local pass_hash
        if [ -x /opt/hermes/.venv/bin/python ]; then
            pass_hash=$(/opt/hermes/.venv/bin/python -c \
                "from plugins.dashboard_auth.basic import hash_password; print(hash_password('${HERMES_API_SERVER_KEY}'))" \
                2>/dev/null) || pass_hash="${HERMES_API_SERVER_KEY}"
        else
            # hermes 尚未安装 (首次渲染在 Phase 4, 安装在 Phase 5), 用明文兜底
            pass_hash="${HERMES_API_SERVER_KEY}"
        fi
        export HERMES_DASHBOARD_PASS_HASH="$pass_hash"
        envsubst < "$CONFIG_DIR/hermes/config.yaml.tpl" | sudo tee "$hermes_dir/config.yaml" >/dev/null
    fi
    sudo chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "$hermes_dir"

    # hermes: 拷贝 TitanVault 运维知识库到 skills/ops
    # 让 Hermes agent 能回答本机运维问题 (硬件/Docker/LLM/网络)
    # 每次安装都覆盖 (知识库随版本更新, 用户自定义 skill 不在此目录)
    if [ -d "$CONFIG_DIR/hermes/skills/ops" ]; then
        log "部署 Hermes 运维知识库 (skills/ops)..."
        sudo mkdir -p "$hermes_dir/skills/ops"
        sudo cp -r "$CONFIG_DIR/hermes/skills/ops/"* "$hermes_dir/skills/ops/" 2>/dev/null
        sudo chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "$hermes_dir/skills"
    fi

    # hermes: 配置 hindsight 长期记忆后端 (外部 hindsight 容器 + postgres + pgvector)。
    # hindsight 容器 (compose/agents.yml) 用 infra postgres 存储, embedding/reranker 走 litellm。
    # hermes 原生通过 localhost:8888 连 hindsight 容器 (local_external 模式)。
    # 不存在时才渲染 (保留用户改过的; 如改了 bank_id 等)。
    sudo mkdir -p "$hermes_dir/hindsight"
    if [ ! -f "$hermes_dir/hindsight/config.json" ]; then
        log "配置 Hermes hindsight 记忆后端 (连接外部 hindsight 容器)..."
        envsubst < "$CONFIG_DIR/hermes/hindsight-config.json.tpl" | sudo tee "$hermes_dir/hindsight/config.json" >/dev/null
    fi
    sudo chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "$hermes_dir/hindsight"

    # opensquilla: 数据目录初始化 (容器 uid 10001)。provider 配置在容器启动后
    # 用 onboard 命令写入 config.toml (Phase5 start_services 里做)。
    local osq_dir="${DATA_DIR:-/data}/opensquilla"
    sudo mkdir -p "$osq_dir"
    sudo chown -R 10001:10001 "$osq_dir"

    # open-design: 数据目录初始化 (容器 uid 1001, read_only 容器需可写卷)。
    local od_dir="${DATA_DIR:-/data}/open-design"
    sudo mkdir -p "$od_dir"
    sudo chown -R 1001:1001 "$od_dir"
}

# ============================================================================
# Phase 2: GPU 驱动 (GRUB + Mesa + Vulkan, 需重启一次)
# ============================================================================
phase2_gpu() {
    log "Phase 2: GPU 驱动 (Vulkan)..."

    # 断点续接: 若 Vulkan 已就绪则跳过
    if command -v vulkaninfo >/dev/null 2>&1 && vulkaninfo --summary 2>/dev/null | grep -qi "radv\|amd"; then
        log "✅ Vulkan 已就绪, 跳过驱动安装"
        write_state 2
        return
    fi

    load_env
    . "$REPO_DIR/hardware/aimax-395.profile"

    # Swap: 配置 100G (大模型推理需要大 swap, 默认 8G 不够)
    # 直接替换 /swap.img 为 100G, 确保 swap 总量达标
    local swap_total_kb=$(awk '/SwapTotal/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
    if [ "${swap_total_kb:-0}" -lt 94371840 ]; then  # 不足 90G 则重建
        log "配置 swap 100G (当前 $(awk '/SwapTotal/{printf "%.0fG", $2/1048576}' /proc/meminfo 2>/dev/null || echo "?"))..."
        # 关闭并删除旧 swap 文件
        for sf in /swap.img /swap2.img; do
            swapon --show=name 2>/dev/null | grep -q "$sf" && sudo swapoff "$sf"
            [ -f "$sf" ] && sudo rm -f "$sf"
        done
        # 创建 100G swap
        sudo fallocate -l 100G /swap.img || sudo dd if=/dev/zero of=/swap.img bs=1G count=100
        sudo chmod 600 /swap.img
        sudo mkswap /swap.img
        sudo swapon /swap.img
        # fstab 持久化 (清理旧条目, 确保只有一条)
        sudo sed -i '/swap/d' /etc/fstab
        echo "/swap.img none swap sw 0 0" | sudo tee -a /etc/fstab
        log "  ✅ swap 已配置为 100G ($(awk '/SwapTotal/{printf "%.0fG", $2/1048576}' /proc/meminfo))"
    fi


    # GRUB 内核参数
    if ! grep -q "amdgpu.gtt_size" /etc/default/grub 2>/dev/null; then
        log "写入 GRUB 内核参数: $GRUB_PARAMS"
        sudo sed -i "s|GRUB_CMDLINE_LINUX_DEFAULT=\"|GRUB_CMDLINE_LINUX_DEFAULT=\"${GRUB_PARAMS} |" /etc/default/grub
        sudo update-grub
    fi

    # Mesa PPA + Vulkan 驱动
    log "安装 Mesa (kisak PPA) + Vulkan 驱动..."
    sudo add-apt-repository -y ppa:kisak/kisak-mesa
    sudo apt-get update
    sudo apt-get install -y mesa-vulkan-drivers vulkan-tools

    # 注册重启后续接 (crontab @reboot)
    # @reboot 默认 PATH 极简 (/usr/bin:/bin), 续接脚本要 curl/apt 等, 故显式设 PATH/SHELL。
    CRON_LINE="@reboot ${SUDO_USER:+sudo -u ${SUDO_USER} }env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin bash ${REPO_DIR}/install.sh --resume 3"
    (sudo crontab -l 2>/dev/null | grep -v "install.sh --resume"; echo "$CRON_LINE") | sudo crontab -

    write_state 2
    log "✅ GPU 驱动已安装。系统将在 60 秒后重启, 重启后自动继续 Phase 3。"
    log "   (若未自动重启, 请手动 sudo reboot, 续接命令已写入 crontab)"
    sleep 60
    sudo reboot
}

# ============================================================================
# Phase 3: Docker + 镜像
# ============================================================================
phase3_docker() {
    log "Phase 3: Docker + 镜像..."

    # Docker 引擎
    if ! command -v docker >/dev/null 2>&1; then
        log "安装 Docker..."
        curl -fsSL https://get.docker.com | sudo sh
        sudo usermod -aG docker "${SUDO_USER:-$USER}"
    fi
    # 等 docker daemon 就绪 (crontab @reboot 续接时 daemon 可能还没起)
    log "等待 Docker daemon 就绪..."
    local dock_ready=false
    for _ in $(seq 1 30); do
        if sudo docker info >/dev/null 2>&1; then dock_ready=true; break; fi
        sleep 2
    done
    [ "$dock_ready" = true ] || err "Docker daemon 60s 内未就绪, 请启动后重跑: sudo systemctl start docker && bash install.sh --resume 3"
    # 当前 shell 可能还没刷新 docker 组, 用 sg 或 newgrp 兜底
    sudo docker version >/dev/null 2>&1 || warn "docker 组未生效 (用 sudo 绕过), 建议重新登录刷新组"

    # 移除 crontab 续接标记 (Phase 2 写的)
    sudo crontab -l 2>/dev/null | grep -v "install.sh --resume" | sudo crontab - || true

    load_env

    # 配置 docker registry-mirror (国内拉镜像加速, 直连 docker hub 必慢/必失败)
    # 在 load_env 之后: 依赖 MODEL_SOURCE (cn 才配, global 跳过)
    configure_docker_mirror

    # 先加载离线镜像包 (国内 docker hub 被墙, 镜像源对冷门/base镜像无缓存。
    # 预打包 images/offline/*.tar.gz: standard-*(运行时冷门) + build-base-*(build用的python base)。
    # load 后 build 不用拉 base, compose up 发现镜像已存在不再 pull)

    # build TitanVault (门户门面, 所有 preset 都需要; React + Vite 静态编译)
    if ! sudo docker image inspect mozin/titanvault:latest >/dev/null 2>&1; then
        log "构建 TitanVault 门户镜像 (React + Vite, 约 1 分钟)..."
        sudo docker build -t mozin/titanvault:latest "$REPO_DIR/images/titanvault-homepage/" \
            || warn "TitanVault 构建失败。门户将不可用, 见 images/titanvault-homepage/"
    else
        log "TitanVault 镜像已就位, 跳过构建"
    fi
    if ls "$REPO_DIR/images/offline/"*.tar.gz >/dev/null 2>&1; then
        log "加载离线镜像包 (images/offline/)..."
        bash "$REPO_DIR/scripts/load-offline-images.sh" all 2>&1 | sed 's/^/  /' || warn "离线镜像加载部分失败 (不阻塞, 后续 pull 兜底)"
    else
        log "无离线镜像包, 直接从镜像源拉取"
    fi

    # build ROCm 镜像 (mineru-api + aham-voice-web, 基镜像官方 rocm/pytorch)
    # 官方 base 可 docker pull, 不再依赖本地 cortibox-rocm-base (历史遗留, 已废弃)。
    # 见 images/mineru-rocm/BUILD.md 和 images/aham-voice-web/BUILD.md。
    if [ "$PRESET" = "full" ] || [ "$PRESET" = "standard" ]; then
        ROCM_BASE="rocm/pytorch:rocm7.2.3_ubuntu22.04_py3.10_pytorch_release_2.9.1"
        # base 已被上面的 load 离线包加载? 否则 pull (13GB, 国内可能慢)
        if ! sudo docker image inspect "$ROCM_BASE" >/dev/null 2>&1; then
            log "拉取 ROCm 基镜像 ($ROCM_BASE, 约 13GB, 国内可能较慢)..."
            if ! sudo docker pull "$ROCM_BASE" 2>&1 | grep -vE "^$" | tail -3; then
                warn "ROCm 基镜像拉取失败。检查网络/代理, 或配置 docker registry-mirror。
   跳过 ROCm 镜像构建 (mineru + aham), 其余服务不受影响。
   网络恢复后手动构建: 见 images/mineru-rocm/BUILD.md"
                ROCM_SKIP=1
            fi
        else
            log "ROCm 基镜像已就位 (离线包), 跳过拉取"
        fi
        if [ "${ROCM_SKIP:-0}" != "1" ]; then
            log "构建 mineru-rocm 镜像 (约 20 分钟)..."
            sudo docker build -t mineru-rocm:latest -f "$REPO_DIR/images/mineru-rocm/Dockerfile.rocm" \
                "$REPO_DIR/images/mineru-rocm/" || warn "mineru-rocm 构建失败, 见 images/mineru-rocm/BUILD.md"
            log "构建 aham-voice-web 镜像 (ROCm 版)..."
            sudo docker build -t aham-voice-web:rocm -f "$REPO_DIR/images/aham-voice-web/Dockerfile.rocm" \
                "$REPO_DIR/images/aham-voice-web/" || warn "aham-voice-web 构建失败, 见 images/aham-voice-web/BUILD.md"
            log "构建 comfyui-rocm 镜像 (ROCm 版 Stable Diffusion)..."
            sudo docker build -t comfyui-rocm:latest -f "$REPO_DIR/images/comfyui-rocm/Dockerfile.rocm" \
                "$REPO_DIR/images/comfyui-rocm/" || warn "comfyui-rocm 构建失败, 见 images/comfyui-rocm/Dockerfile.rocm"
        fi
    fi

    # opensquilla: 原生部署 (Phase 5 装 venv), 不再 build Docker 镜像。
    # open-design: ghcr 镜像未发布 (401), 从源码 build (多阶段 pnpm + Next.js)
    if [ "$PRESET" = "full" ]; then
        if ! sudo docker image inspect open-design:local >/dev/null 2>&1; then
            log "构建 open-design 镜像 (从 GitHub 源码, 多阶段 pnpm + Next.js, 约 5-10 分钟)..."
            sudo -E bash "$REPO_DIR/images/open-design/build.sh" open-design:local \
                || warn "open-design 构建失败 (网络/npm)。见 images/open-design/build.sh, 可后续手动构建。"
        else
            log "open-design 镜像已就位, 跳过构建"
        fi
    fi

    # 拉取第三方镜像 (按 preset 选的 profile; 已 load 的会跳过)
    log "拉取第三方镜像 (按 $PRESET preset, 缺失项)..."
    for p in $(preset_to_profiles "$PRESET"); do
        sudo docker compose --env-file "$REPO_DIR/.env" --profile "$p" pull 2>/dev/null || true
    done

    write_state 3
}

# preset 名 → compose profile 列表 (读 presets/<preset>.env 的 INCLUDE_*, 下划线转连字符)
preset_to_profiles() {
    local preset="$1"
    local envfile="$REPO_DIR/presets/${preset}.env"
    [ -f "$envfile" ] || err "preset 文件不存在: $envfile"
    # INCLUDE_AI_CAPABILITY → ai-capability; 其余单段直接小写
    set -a; . "$envfile"; set +a
    local profiles=""
    [ "$INCLUDE_INFRA" = true ] && profiles="$profiles infra"
    [ "$INCLUDE_GATEWAY" = true ] && profiles="$profiles gateway"
    [ "$INCLUDE_AI_CAPABILITY" = true ] && profiles="$profiles ai-capability"
    [ "$INCLUDE_NETWORK" = true ] && profiles="$profiles network"
    [ "$INCLUDE_APPS" = true ] && profiles="$profiles apps"
    [ "$INCLUDE_MONITORING" = true ] && profiles="$profiles monitoring"
    [ "$INCLUDE_AGENTS" = true ] && profiles="$profiles agents"
    echo "$profiles"
}

# ============================================================================
# Phase 4: 模型下载
# ============================================================================
phase4_models() {
    log "Phase 4: 模型下载 (约 30 分钟, 视网速)..."
    load_env

    # yq 用于解析 models.yaml
    command -v yq >/dev/null 2>&1 || sudo apt-get install -y yq || sudo snap install yq

    MODEL_SOURCE="$MODEL_SOURCE" DATA_DIR="$DATA_DIR" \
        bash "$REPO_DIR/scripts/download-models.sh" || warn "部分模型下载失败, 可重跑 scripts/download-models.sh"

    write_state 4
}

# ============================================================================
# Phase 5: 启动
# ============================================================================
phase5_start() {
    log "Phase 5: 启动服务..."
    load_env
    load_hardware   # export MODEL_DIR/LLM_*/EMBED_*, envsubst 才能在管道里看到

    # 确保 config 已渲染 (--resume 5 跳过了 Phase 1 的 render_configs, 此处幂等补做)
    # render_configs 内部大多有 [ ! -f ] 幂等保护, 已存在的不会覆盖
    render_configs

    # 编译 llama.cpp (如未装)
    if ! sudo test -x /opt/llama.cpp/llama-server; then
        log "编译 llama.cpp (Vulkan, 约 10-15 分钟)..."
        sudo -E LLAMA_VERSION="${LLAMA_VERSION:-b9840}" bash "$REPO_DIR/native/llama.cpp/build.sh"
    fi

    # 渲染 systemd 模板 (envsubst 读已 export 的 .env + profile 变量)
    # 关键: 变量必须 exported (load_env/load_hardware 已 set -a), 否则管道子进程看不到。
    log "注册 llama.cpp systemd 服务..."
    sudo mkdir -p /etc/systemd/system
    envsubst < "$REPO_DIR/native/llama.cpp/llama-main.service.tpl" | sudo tee /etc/systemd/system/llama-main.service >/dev/null
    envsubst < "$REPO_DIR/native/llama.cpp/llama-embed.service.tpl" | sudo tee /etc/systemd/system/llama-embed.service >/dev/null
    envsubst < "$REPO_DIR/native/llama.cpp/llama-rerank.service.tpl" | sudo tee /etc/systemd/system/llama-rerank.service >/dev/null
    sudo systemctl daemon-reload

    # reranker GGUF 转换重试 (Phase 4 下载了 HF 原版, 但转换需要 llama.cpp 的 convert_hf_to_gguf.py,
    # 该脚本在刚编译完的 /opt/llama.cpp/ 里。此处重试转换。)
    local _rerank_gguf="${MODEL_DIR}/reranker/Qwen3-Reranker-0.6B-f16.gguf"
    if [ ! -f "$_rerank_gguf" ] && [ -f /opt/llama.cpp/convert_hf_to_gguf.py ]; then
        local _rerank_src=$(find "${MODEL_DIR}/reranker" -name "config.json" -exec dirname {} \; 2>/dev/null | head -1)
        if [ -n "$_rerank_src" ]; then
            log "转换 Reranker HF → GGUF (Phase 4 时 convert 脚本未就绪, 此处重试)..."
            PYTHONPATH="/opt/llama.cpp/gguf-py:/opt/llama.cpp" python3 /opt/llama.cpp/convert_hf_to_gguf.py \
                "$_rerank_src" --outtype f16 --outfile "$_rerank_gguf" 2>&1 | tail -2 \
                && log "  ✓ Reranker GGUF 转换完成" \
                || warn "Reranker GGUF 转换失败"
        fi
    fi

    # main + embed 必装; rerank 仅在模型已下载时启动 (避免缺模型 crash-loop)
    sudo systemctl enable --now llama-main llama-embed
    local _rerank_gguf="${DATA_DIR:-/data}/models/reranker/Qwen3-Reranker-0.6B-f16.gguf"
    if [ -f "$_rerank_gguf" ]; then
        sudo systemctl enable --now llama-rerank
    else
        # 模型没下成功, 只 enable 不 now (下次有模型时手动 start, 或重跑 Phase 4)
        sudo systemctl enable llama-rerank 2>/dev/null || true
        warn "rerank 模型未找到 ($_rerank_gguf), 服务已注册但未启动。重跑 scripts/download-models.sh 后 sudo systemctl start llama-rerank"
    fi

    # 等 llama.cpp 就绪 (端口 8082), 超时则报错而非静默继续
    log "等待 llama.cpp 就绪 (最多 120s)..."
    local llama_ready=false
    for _ in $(seq 1 24); do
        if curl -sf http://127.0.0.1:8082/v1/models >/dev/null 2>&1; then llama_ready=true; break; fi
        sleep 5
    done
    [ "$llama_ready" = true ] || err "llama.cpp (8082) 120s 内未就绪, 检查: sudo systemctl status llama-main / journalctl -u llama-main"

    # 启动 compose (一次性带所有 profile, 避免跨 profile depends_on 失败)
    log "启动 Docker 服务 ($PRESET preset)..."

    # ⚠ postgres 密码一致性检测: POSTGRES_PASSWORD 仅在 data 目录首次初始化时生效。
    # 重装时密码重新随机生成, 但旧 data 目录 (/data/postgres) 保留旧密码 →
    # litellm/hindsight/gitea 用新密码连不上 (FATAL: password authentication failed)。
    # 修复: 记录已安装密码, 不匹配则清空 data 目录让 postgres 重新初始化。
    local _pg_data="${DATA_DIR:-/data}/postgres"
    local _pw_file="${_pg_data}/.installed_password"
    if sudo [ -d "$_pg_data/pg_global" ]; then  # 已初始化 (pg_global 是 initdb 产物)
        local _old_pw=$(sudo cat "$_pw_file" 2>/dev/null || true)
        # 清理条件: 密码不匹配 OR 检测文件丢失 (无法确认一致性 → 安全清理)
        # 检测文件丢失场景: 用户手动删过 data 子文件但留了 PG_VERSION, 或升级迁移
        if [ "$_old_pw" != "$POSTGRES_PASSWORD" ]; then
            log "检测到 postgres 密码变更或检测文件缺失 (重装), 清空旧数据目录重新初始化..."
            sudo rm -rf "${_pg_data:?}"
            sudo mkdir -p "$_pg_data"
            log "  ✅ 旧 postgres 数据已清除"
        fi
    fi

    # ⚠ surrealdb 同源问题: OPEN_NOTEBOOK_SURREAL_PASSWORD 首次启动设 root 用户,
    # 之后改密码不生效 (rocksdb 数据保留旧 root)。open-notebook 用新密码连不上。
    # 修复: 凭据指纹不匹配时清空 surrealdb rocksdb 数据重新初始化。
    local _sdb_data="${DATA_DIR:-/data}/open-notebook/db"
    local _cred_file_check="${DATA_DIR:-/data}/.mozin/.installed_credentials"
    local _cur_cred=$(echo "${POSTGRES_PASSWORD}${REDIS_PASSWORD}${LITELLM_MASTER_KEY}${HERMES_API_SERVER_KEY}${QDRANT_API_KEY}${OPEN_NOTEBOOK_SURREAL_PASSWORD}" | sha256sum | cut -d' ' -f1)
    if sudo [ -d "$_sdb_data/mydatabase.db" ]; then
        local _saved_cred=$(cat "$_cred_file_check" 2>/dev/null || true)
        if [ "$_saved_cred" != "$_cur_cred" ]; then
            log "检测到 surrealdb 密码变更或检测文件缺失 (重装), 清空旧 rocksdb 数据重新初始化..."
            sudo rm -rf "${_sdb_data:?}"/*
            log "  ✅ 旧 surrealdb 数据已清除"
        fi
    fi

    local _profiles=""
    for p in $(preset_to_profiles "$PRESET"); do _profiles="$_profiles --profile $p"; done

    # ⚠ 重装时密码随机重新生成, 但 compose up -d 默认不重建已存在容器 →
    # 容器保留旧 env (旧密码), 新密码注入不进去 → litellm/token-usage-api/caddy
    # 之间认证错位。检测: 记录上次安装的密码指纹, 不匹配则 --force-recreate 全部。
    local _cred_file="${DATA_DIR:-/data}/.mozin/.installed_credentials"
    local _cred_hash=$(echo "${POSTGRES_PASSWORD}${REDIS_PASSWORD}${LITELLM_MASTER_KEY}${HERMES_API_SERVER_KEY}${QDRANT_API_KEY}${OPEN_NOTEBOOK_SURREAL_PASSWORD}" | sha256sum | cut -d' ' -f1)
    local _recreate=""
    if [ -f "$_cred_file" ] && [ "$(cat "$_cred_file" 2>/dev/null)" != "$_cred_hash" ]; then
        log "检测到凭据变更 (重装), 强制重建所有容器..."
        _recreate="--force-recreate"
    fi
    sudo mkdir -p "${DATA_DIR:-/data}/.mozin" 2>/dev/null

    sudo docker compose --env-file "$REPO_DIR/.env" $_profiles up -d $_recreate

    # 记录凭据指纹 (供下次重装检测)
    echo "$_cred_hash" | sudo tee "$_cred_file" >/dev/null 2>&1 || true

    # 记录当前 postgres 密码 (供下次重装检测)
    if sudo [ -d "$_pg_data" ]; then
        echo "$POSTGRES_PASSWORD" | sudo tee "$_pw_file" >/dev/null 2>&1 || true
    fi

    # Hermes 原生安装 + systemd (非容器, 仅 full/agents preset)
    # 在 compose up 之后: hermes 启动时 litellm/hindsight 等容器已就绪。
    # 原生部署让 Hermes 拥有完整宿主机能力 (docker/systemctl/网络/文件系统)。
    if [ "$PRESET" = "full" ]; then
        log "安装 Hermes Agent (原生, 非容器)..."
        sudo -E bash "$REPO_DIR/native/hermes/install.sh" || warn "Hermes 安装失败, 可手动: sudo bash native/hermes/install.sh"

        # 渲染 config.yaml (Phase 4 渲染过则跳过; Phase 5 装 hermes 后重试 hash)
        local hermes_dir="${DATA_DIR:-/data}/hermes"
        if [ -x /opt/hermes/.venv/bin/python ] && [ -f "$hermes_dir/config.yaml" ]; then
            # 重新生成 password hash (Phase 4 时 hermes 还没装, 用了明文兜底)
            local _hash
            _hash=$(/opt/hermes/.venv/bin/python -c \
                "from plugins.dashboard_auth.basic import hash_password; print(hash_password('${HERMES_API_SERVER_KEY}'))" 2>/dev/null) || _hash=""
            if [ -n "$_hash" ]; then
                export HERMES_DASHBOARD_PASS_HASH="$_hash"
                # 重新渲染 config.yaml (带上正确的 hash)
                envsubst < "$CONFIG_DIR/hermes/config.yaml.tpl" | sudo tee "$hermes_dir/config.yaml" >/dev/null
                sudo chown "${DEPLOY_USER}:${DEPLOY_USER}" "$hermes_dir/config.yaml"
                log "  ✓ hermes config.yaml password hash 已更新"
            fi
        fi

        # 创建 ops profile (运维 agent, 独立 SOUL.md/skills, approvals=off)
        # 双 agent 架构: ops (运维 :8642) + default (通用 :8643)
        log "创建 Hermes ops profile (运维 agent)..."
        export HOME="$hermes_dir"
        if ! /opt/hermes/.venv/bin/hermes profile list 2>&1 | grep -q "ops"; then
            /opt/hermes/.venv/bin/hermes profile create ops --clone --description "TitanVault 运维 Agent" 2>&1 | tail -2
        fi
        # ⚠ profile --clone 复制的是旧 config.yaml (api_key/hash 是创建时的值)。
        # 重装时 HERMES_API_SERVER_KEY 变了, 必须用最新主 config 覆盖 ops profile 的 config,
        # 否则 gateway (-p ops) 用旧 key 验证 → Caddy 注入新 key → 401 invalid API key。
        local ops_dir="$hermes_dir/.hermes/profiles/ops"
        if [ -f "$hermes_dir/config.yaml" ]; then
            sudo cp "$hermes_dir/config.yaml" "$ops_dir/config.yaml"
            sudo chown "${DEPLOY_USER}:${DEPLOY_USER}" "$ops_dir/config.yaml"
        fi
        # ops SOUL.md (运维人格)
        local ops_dir="$hermes_dir/.hermes/profiles/ops"
        sudo mkdir -p "$ops_dir"
        sudo tee "$ops_dir/SOUL.md" >/dev/null << 'SOULEOF'
你是 TitanVault 工作站的运维 Agent，名为 Hermes。你的职责是管理和维护这台 AMD AI MAX 395 AI 工作站。

## 你的能力
- 你运行在宿主机上（非容器），拥有完整的系统权限
- 你可以使用 docker 命令管理所有服务容器（查看、重启、日志、进入容器）
- 你可以使用 systemctl 管理原生服务（llama.cpp、hermes-dashboard/gateway）
- 你可以读写文件系统、执行 shell 命令、诊断问题

## 工作原则
- 回答简洁直接，先给结论再给细节
- 操作前先检查当前状态（docker ps / systemctl status），基于事实判断
- 重启服务前确认必要性，避免不必要的中断
- 危险操作（删除、修改配置）前说明影响
- 硬件问题以 ops 知识库为准（lspci 可能误判新型号）

## 回答风格
- 用中文回答，技术细节用代码块格式化
- 不废话，用户问什么答什么
SOULEOF
        sudo chown "${DEPLOY_USER}:${DEPLOY_USER}" "$ops_dir/SOUL.md"
        # ops skills
        sudo mkdir -p "$ops_dir/skills"
        sudo cp -r "$CONFIG_DIR/hermes/skills/"* "$ops_dir/skills/" 2>/dev/null || true
        sudo chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "$ops_dir"

        # default profile 不跑 gateway (用户自己开 dashboard 通用对话)
        # 只有 ops profile 跑 gateway api_server, 给 TitanVault AI 助手用

        # 注册 hermes systemd 服务 (dashboard + ops gateway)
        log "注册 Hermes systemd 服务 (dashboard :9119 + ops gateway :8642)..."
        envsubst < "$REPO_DIR/native/hermes/hermes-dashboard.service.tpl" | sudo tee /etc/systemd/system/hermes-dashboard.service >/dev/null
        envsubst < "$REPO_DIR/native/hermes/hermes-gateway.service.tpl" | sudo tee /etc/systemd/system/hermes-gateway.service >/dev/null
        sudo systemctl daemon-reload
        sudo systemctl enable --now hermes-dashboard hermes-gateway

        # Chrome CDP 服务 (供 browser-use / Hermes 浏览器自动化, "数字员工"能力)
        # Hermes 的 browser toolset 经 CDP(:9222) 连接 headless Chrome 操作页面。
        # 仅在 full preset (已装 browser-use + Chrome) 注册。
        if [ "$PRESET" = "full" ]; then
            log "注册 Chrome CDP 服务 (浏览器自动化 :9222)..."
            sudo mkdir -p "${DATA_DIR:-/data}/browser-use/chrome-profile"
            sudo chown "$DEPLOY_USER:$DEPLOY_USER" "${DATA_DIR:-/data}/browser-use" 2>/dev/null || true
            envsubst < "$REPO_DIR/native/chrome-cdp/chrome-cdp.service.tpl" \
                | sudo tee /etc/systemd/system/chrome-cdp.service >/dev/null
            sudo systemctl daemon-reload
            sudo systemctl enable --now chrome-cdp 2>/dev/null || warn "Chrome CDP 启动失败 (browser-use 将不可用)"
        fi

        # 等 ops gateway 就绪 (端口 8642)
        log "等待 Hermes gateway 就绪 (最多 60s)..."
        for _ in $(seq 1 12); do
            if curl -sf http://127.0.0.1:8642/v1/models >/dev/null 2>&1; then log "  ✓ Hermes ops gateway 就绪"; break; fi
            sleep 5
        done
    fi

    # OpenSquilla 原生安装 + systemd (写代码 agent, 需宿主机文件系统/git/build)
    # 在 compose up 之后: provider 走 localhost:4000 (LiteLLM 容器已发布端口)
    if [ "$PRESET" = "full" ]; then
        log "安装 OpenSquilla (原生, 非容器)..."
        sudo -E bash "$REPO_DIR/native/opensquilla/install.sh" || warn "OpenSquilla 安装失败, 可手动: sudo bash native/opensquilla/install.sh"

        # onboard: provider 指向本机 LiteLLM
        log "配置 OpenSquilla provider (指向 LiteLLM)..."
        sudo -u "$DEPLOY_USER" /opt/opensquilla/.venv/bin/opensquilla onboard \
            --provider openai \
            --api-key "$LITELLM_MASTER_KEY" \
            --base-url http://localhost:4000/v1 \
            --model "${LLM_MODEL_NAME:-Qwen3.6-35B-A3B}" \
            --router disabled \
            --minimal --skip-channels --skip-search --skip-image-generation --skip-migration \
            >/dev/null 2>&1 && log "  ✓ OpenSquilla provider 已配置" \
            || warn "OpenSquilla onboard 失败, 可手动: opensquilla onboard"

        # 注册 systemd 服务
        # ⚠ 数据目录可能残留容器写的文件 (uid 10001), 原生服务以 DEPLOY_USER 跑会
        # PermissionError 写 pid lock。chown 回 DEPLOY_USER 确保可写。
        local _osq_dir="${DATA_DIR:-/data}/opensquilla"
        sudo chown -R "$DEPLOY_USER:$DEPLOY_USER" "$_osq_dir" 2>/dev/null || true
        log "注册 OpenSquilla systemd 服务 (:18791)..."
        envsubst < "$REPO_DIR/native/opensquilla/opensquilla.service.tpl" | sudo tee /etc/systemd/system/opensquilla.service >/dev/null
        sudo systemctl daemon-reload
        sudo systemctl enable --now opensquilla

        # 等就绪
        for _ in $(seq 1 12); do
            if curl -sf http://127.0.0.1:18791/healthz >/dev/null 2>&1; then log "  ✓ OpenSquilla 就绪"; break; fi
            sleep 5
        done
    fi

    # open-notebook: 自动配置模型 (开箱即用, 否则用户打开看到空白需手动配)
    # 通过 API 创建 chat+embedding 模型并设默认, 指向本机 LiteLLM。
    # 幂等: 模型已存在则跳过。仅 apps/full preset 有此服务。
    if sudo docker ps --format '{{.Names}}' | grep -q open-notebook; then
        log "配置 Open Notebook 模型 (开箱即用, 指向 LiteLLM)..."
        export LLM_MODEL_NAME="${LLM_MODEL_NAME:-Qwen3.6-35B-A3B}"
        export EMBED_MODEL_NAME="${EMBED_MODEL_NAME:-Qwen3-Embedding-0.6B}"
        bash "$REPO_DIR/scripts/setup-open-notebook.sh" 2>&1 | sed 's/^/  /' || warn "Open Notebook 自动配置失败, 可手动在 UI Settings 配置"
    fi

    # Hermes default profile: 配置模型 (通用对话, 用户在 dashboard 聊天用)
    # ops profile 给运维 gateway; default 给通用对话。两者都需要 config + 模型。
    if [ "$PRESET" = "full" ]; then
        log "配置 Hermes default profile (通用对话 agent)..."
        local _hermes_home="${DATA_DIR:-/data}/hermes"
        local _default_dir="$_hermes_home/.hermes/profiles/default"
        if [ ! -f "$_default_dir/config.yaml" ]; then
            sudo mkdir -p "$_default_dir"
            sudo cp "$_hermes_home/config.yaml" "$_default_dir/config.yaml" 2>/dev/null
            sudo chown -R "$DEPLOY_USER:$DEPLOY_USER" "$_default_dir"
            log "  ✓ default profile config 已创建"
        fi
    fi

    # opensquilla: 配置 provider (指向 LiteLLM)
    # install.sh 安装 opensquilla 后需 onboard 配模型, 否则 gateway 报 "需要连接模型"
    if [ "$PRESET" = "full" ] && [ -x /opt/opensquilla/.venv/bin/opensquilla ]; then
        log "配置 OpenSquilla provider (指向 LiteLLM)..."
        HOME="${DATA_DIR:-/data}/opensquilla" /opt/opensquilla/.venv/bin/opensquilla onboard \
            --provider openai \
            --api-key "$LITELLM_MASTER_KEY" \
            --base-url http://localhost:4000/v1 \
            --model "${LLM_MODEL_NAME:-Qwen3.6-35B-A3B}" \
            --router disabled \
            --minimal --skip-channels --skip-search --skip-image-generation --skip-migration \
            >/dev/null 2>&1 \
            && log "  ✓ OpenSquilla provider 已配置" \
            || warn "OpenSquilla provider 配置失败, 可手动: opensquilla onboard"
        sudo systemctl restart opensquilla 2>/dev/null || true
    fi

    # uptime-kuma: 自动初始化 (创建 admin + 灌入 18 个服务监控)
    if sudo docker ps --format '{{.Names}}' | grep -q uptime-kuma; then
        log "初始化 Uptime Kuma (admin 用户 + 服务监控)..."
        bash "$REPO_DIR/scripts/setup-kuma.sh" 2>&1 | sed 's/^/  /' || warn "Kuma 初始化失败, 可手动访问 :3001 设置"
    fi

    write_state 5
}

# ============================================================================
# Phase 6: 完成 + 引导
# ============================================================================
phase6_done() {
    log "✅ TitanVault 安装完成!"
    load_env
    local_ip="${HOST_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"

    cat <<EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🎉 TitanVault 已就绪
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  门户:        http://${local_ip}                 (Homepage, Caddy :80)
  LLM API:     http://${local_ip}/llm/v1/...      (经 Caddy 反代 LiteLLM)
               或 http://127.0.0.1:4000 (本机直连, 改 LITELLM_BIND 可放开)
  llama.cpp:   http://127.0.0.1:8082 (main) / :8084 (embed) / :8083 (rerank)  [原生 systemd]
  Hermes:      http://127.0.0.1:9119 (dashboard) / :8642 (gateway)  [原生 systemd]
               AI 助手: http://${local_ip}/ (右下角, 经 Caddy /hermes/* 反代)

  首次密码 (仅显示一次, 请立即保存到密码管理器):
    PostgreSQL:    ${POSTGRES_PASSWORD}
    Redis:         ${REDIS_PASSWORD}
    LiteLLM:       ${LITELLM_MASTER_KEY}
    Hermes:        ${HERMES_API_SERVER_KEY}  (用户名 admin, dashboard 登录用)

  配置文件: ${REPO_DIR}/.env
  文档:     docs/getting-started.md

  preset: ${PRESET} | 数据目录: ${DATA_DIR} | 模型源: ${MODEL_SOURCE}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF
    write_state 6
    # 清理 crontab 续接标记
    sudo crontab -l 2>/dev/null | grep -v "install.sh --resume" | sudo crontab - || true
}

# ============================================================================
# 主流程 (支持 --resume 断点续接)
# ============================================================================
main() {
    need_root_check

    # cd 到仓库根: curl|bash 从任意目录运行时, docker compose 需在 compose.yaml 所在目录。
    cd "$REPO_DIR" || err "无法进入仓库目录 $REPO_DIR"

    if [ "${1:-}" = "--resume" ]; then
        # 断点续接。state.json 记录"最后完成的 phase"。
        #   bash install.sh --resume        → 自动从 (最后完成 phase + 1) 继续
        #   bash install.sh --resume N      → 显式从 Phase N 继续 (N = 要执行的下一 phase)
        # 这样避免 Phase 2 完成后 (state=2) 无参 --resume 重跑 Phase 2 → 重启死循环。
        if [ -n "${2:-}" ]; then
            START_PHASE="$2"
        else
            START_PHASE=$(( $(read_state) + 1 ))
        fi
        log "断点续接: 从 Phase ${START_PHASE} 继续"
        case "$START_PHASE" in
            3) phase3_docker; phase4_models; phase5_start; phase6_done ;;
            4) phase4_models; phase5_start; phase6_done ;;
            5) phase5_start; phase6_done ;;
            6) phase6_done ;;
            *) err "无效续接 phase: $START_PHASE (state.json 记录的最后完成 phase: $(read_state); 显式续接请用 3-6)" ;;
        esac
    else
        # 全新安装: Phase 0 → 6
        phase0_detect
        phase1_configure
        phase2_gpu
        phase3_docker
        phase4_models
        phase5_start
        phase6_done
    fi
}

main "$@"
