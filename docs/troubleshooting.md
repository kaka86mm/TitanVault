# 故障排查

常见问题与解决方案。

## GPU 相关

### `未检测到 gfx1151`

安装器 Phase 0 报这个错, 说明 GPU 不是 Radeon 8060S 或驱动未装。

```bash
# 确认 GPU 型号
lspci | grep -i vga
rocminfo | grep -i gfx    # 应见 gfx1151
```

如果是 395 但没识别: 确保 BIOS 里核显启用, 且没装 NVIDIA 驱动抢占。

### llama.cpp 不走 GPU (推理极慢)

```bash
# 检查 llama-server 是否用了 Vulkan
sudo journalctl -u llama-main | grep -i vulkan
# 应见 "ggml_vulkan: Found 1 Vulkan devices"

# 检查显存占用
sudo cat /sys/class/drm/card*/device/mem_info_vram_used_bytes 2>/dev/null
```

如果没走 GPU:
- 确认 `GGML_VULKAN_DEVICE=0` 在 systemd unit 里
- 确认 Vulkan 驱动装了: `vulkaninfo --summary | grep -i amd`
- 重新装: `sudo apt install mesa-vulkan-drivers vulkan-tools`

### 显存不足 (OOM)

35B Q4_K_M 需 ~22GB 显存。395 核显共享内存, 若系统内存不足会 OOM。

```bash
# 查可用显存
sudo cat /sys/class/drm/card*/device/mem_info_vram_free_bytes
```

解决:
- 确保内存 ≥ 64GB
- GRUB 加 `amdgpu.gtt_size=512M` (install.sh Phase 2 已加)
- 换更小量化 (Q3 / 或换小模型, 改 `hardware/aimax-395.profile`)

## Docker 相关

### `docker compose` 报找不到配置文件

确保在仓库根目录运行 (有 `compose.yaml` 的地方):

```bash
cd /path/to/TitanVault
docker compose ps
```

`compose.yaml` 用 `include:` 合并了 7 个分层文件, 必须在这个目录跑。

### 服务起不来: `must be set`

```bash
# 如 POSTGRES_PASSWORD: must be set
# 说明 .env 缺变量或没加载
docker compose --env-file .env config   # 验证 .env 解析
```

重跑 `bash install.sh --resume` 或手动补 `.env`。

### 端口冲突

```bash
# 查谁占了端口
sudo ss -tlnp | grep :8082
```

改 `compose/*.yml` 里对应服务的 `ports:` 主机端口, 或停掉冲突进程。

## 数据库相关

### postgres 认证失败 (litellm/hindsight/gitea 起不来)

重装时密码重新随机生成, 但旧 data 目录保留旧密码。install.sh 有自动检测, 但如果手动操作过:

```bash
# 停 postgres, 清 data, 重启让它重新初始化
sudo docker compose --env-file .env --profile infra stop postgres
sudo rm -rf /data/postgres
sudo docker compose --env-file .env --profile infra --profile gateway --profile ai-capability \
    --profile network --profile apps --profile monitoring --profile agents up -d
```

### 手动建库 (升级场景)

postgres 首次启动时, init 脚本创建 `gitea` / `litellm` / `hindsight` 等库。若数据目录已存在 (非首次), init 不会重跑:

```bash
docker exec mozin-workstation-postgres-1 psql -U postgres -c "CREATE DATABASE <库名>;"
```

## 模型下载

### 下载慢 / 失败

```bash
# 换源 (国内用 modelscope)
MODEL_SOURCE=modelscope bash scripts/download-models.sh

# 单独下某个模型 (改 models.yaml 只留目标, 或直接 python)
python3 -c "from modelscope import snapshot_download; snapshot_download('qwen/Qwen3.6-35B-A3B-GGUF', cache_dir='/data/models/llm')"
```

### mineru 模型缺失

mineru-api 首次启动自动下载模型。若失败:

```bash
docker compose --profile ai-capability logs mineru-api | grep -i model
# 手动下
docker compose --profile ai-capability exec mineru-api mineru-models-download -s modelscope -m all
```

## mineru-rocm 构建

### `rocm/pytorch:... manifest not found` / 构建拉取失败

mineru-api 和 aham-voice-web 的基镜像 `rocm/pytorch:rocm7.2.3_ubuntu22.04_py3.10_pytorch_release_2.9.1`
是 AMD 官方镜像 (Verified Publisher), 正常 `docker pull` 即可。若拉取失败 (网络/代理):

```bash
# 1. 确认代理生效 (国内常需)
docker pull rocm/pytorch:rocm7.2.3_ubuntu22.04_py3.10_pytorch_release_2.9.1

# 2. 若仍失败, 用阿里云源重试 build
docker build --build-arg USE_CN_MIRROR=1 -t mineru-rocm:latest \
    -f images/mineru-rocm/Dockerfile.rocm images/mineru-rocm/
```

> 历史: 曾依赖本地 `cortibox-rocm-base` (~40GB 含 cortibox 全栈), 已废弃改为官方 base。

若暂不想构建, 可跳过 PDF 解析 (其余服务正常):

```bash
# 用不含 ai-capability 的 preset, 或编辑 presets/standard.env 把 INCLUDE_AI_CAPABILITY=false
```

## 续接安装

### 重启后没自动继续

Phase 2 重启后靠 crontab `@reboot` 续接。若没触发:

```bash
sudo crontab -l | grep install.sh   # 应有 @reboot 行
# 手动续接
bash /path/to/TitanVault/install.sh --resume 3
```

### state.json 丢了

```bash
cat ~/.mozin-workstation/state.json
# 没有就从你记得的最后完成的 phase 续: bash install.sh --resume 3 (3-6)
```

## 浏览器自动化

### Hermes 调 browser-use 报错

```bash
# 1. 检查 Chrome CDP 服务
sudo systemctl status chrome-cdp
curl -sf http://127.0.0.1:9222/json/version  # 应返回 Chrome 版本 JSON

# 2. 检查 BH_CHROME_PATH 环境变量
sudo systemctl show hermes-gateway -p Environment | grep CHROME
# 应有 BH_CHROME_PATH=/usr/bin/google-chrome-stable

# 3. snap chromium 冲突 (CDP 不通)
# 必须用 google-chrome-stable (.deb), 不能用 snap chromium
which google-chrome-stable  # 应存在

# 4. chrome-cdp restart 循环 (SingletonLock 残留)
sudo rm -f /data/browser-use/chrome-profile/SingletonLock
sudo systemctl restart chrome-cdp
```

### opensquilla 源码下载失败

opensquilla 从 GitHub 下载源码安装, 国内可能不通。install.sh 有多源 fallback, 若全部失败:

```bash
# 手动下载 (用可达的镜像源)
wget https://ghfast.top/https://github.com/opensquilla/opensquilla/archive/refs/tags/v0.4.1.tar.gz
tar xzf v0.4.1.tar.gz
cd opensquilla-0.4.1
sudo /opt/opensquilla/.venv/bin/pip install . -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 仍解决不了

1. 收集日志:
   ```bash
   docker compose logs --tail=100 > docker-logs.txt
   sudo journalctl -u llama-main -u llama-embed --since "1 hour ago" > llama-logs.txt
   ```
2. 提 issue, 附上日志 + `install.sh --resume` 的输出 + 硬件信息 (`rocminfo | head`)。
