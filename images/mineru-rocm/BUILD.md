# MinerU ROCm 镜像本地构建说明

本目录只含 mineru-api **推理容器** 的 Dockerfile (GPU 后端)。它是 mineru-web 业务层的依赖,
和 mineru-web 的 5 个业务容器一起构成完整的 PDF 解析产品 (共 6 容器, 见 compose/ai-capability.yml)。

## 为什么本地 build (不进 CI / 不推 GHCR)

- 基镜像 `rocm/pytorch` 含完整 ROCm 7.2.3 + PyTorch (~13GB), 推 GHCR 无意义。
- 仅 AMD gfx1151 (Ryzen AI Max+ 395) 能用 GPU, CI runner 无此硬件。

## 架构 (host-inference 模式, 与生产一致)

```
mineru-web (compose/ai-capability.yml, 5 容器):
  frontend :8088  lpdswing/mineru-web-frontend:v3.3.1   (nginx 反代 backend+minio)
  backend  :8089  lpdswing/mineru-web-backend:v3.3.1     (FastAPI, sqlite, 调 host.docker.internal:18080)
  worker   -      lpdswing/mineru-web-backend:v3.3.1     (celery, command: python3 run_worker.py)
  redis    :6381  redis:latest                          (无密码, mineru-web 专用, 独立于 infra redis)
  minio    :9000  minio/minio:RELEASE.2024-12-18...      (minioadmin/minioadmin, 独立)

mineru-api (本镜像, 1 容器, GPU 推理):
  mineru-api :18080→8000  mineru-rocm:latest
    Cmd: mineru-api --host 0.0.0.0 --port 8000 --allow-public-http-client
    Devices: /dev/kfd + /dev/dri, group_add video
```

backend/worker 经 `host.docker.internal:18080` (extra_hosts host-gateway) 调宿主网络上的 mineru-api。

## 基镜像

`rocm/pytorch:rocm7.2.3_ubuntu22.04_py3.10_pytorch_release_2.9.1` (AMD 官方, Verified Publisher)。
gfx1151 已验证 `torch.cuda.is_available()=True` (经 HIP 兼容层, device 字符串仍用 "cuda")。

> 历史: 生产原基于 `cortibox-rocm-base` (一个含 cortibox 全栈 postgres/qdrant/docling/node 的臃肿镜像),
> 但 mineru 只需 ROCm+torch 底子。本发行版改用官方 base, 干净可复现, 不再依赖 cortibox。

## 构建命令

```bash
# 默认 (官方 base):
docker build -t mineru-rocm:latest -f images/mineru-rocm/Dockerfile.rocm images/mineru-rocm/

# 国内构建慢走阿里云源:
docker build -t mineru-rocm:latest --build-arg USE_CN_MIRROR=1 \
    -f images/mineru-rocm/Dockerfile.rocm images/mineru-rocm/

# 用本地已缓存的 rocm/pytorch (离线/特定 tag):
docker build -t mineru-rocm:latest --build-arg ROCM_BASE=rocm/pytorch:<tag> \
    -f images/mineru-rocm/Dockerfile.rocm images/mineru-rocm/
```

## 模型 (4.6GB, 不进镜像, volume 挂载)

挂载到 `${DATA_DIR}/mineru/rocm-models:/models`。首次启动 mineru-api 自动从 modelscope 拉:
- `OpenDataLab/PDF-Extract-Kit-1.0` (布局/OCR/表格检测 pipeline)
- `MinerU2.5-Pro-2605-1.2B` (VLM)

mineru.json (config/mineru/mineru.json) 指定本地模型路径, 避免重复下载。
**不读全局 `MODEL_SOURCE`**: 模型由 mineru-models-download 自管 (iic/OpenDataLab 是 modelscope 原生)。

## GPU 暴露

compose 通过 `devices: ["/dev/kfd", "/dev/dri"]` + `group_add: ["video"]` 直通核显 (gfx1151)。
`MINERU_DEVICE_MODE=cuda` 因 torch ROCm 走 HIP 的 cuda 兼容层。

## 本目录文件

| 文件 | 用途 |
|---|---|
| `Dockerfile.rocm` | mineru-api 推理镜像 (官方 base + mineru[core]==3.4.0) |
| `patch/sitecustomize.py` | monkey-patch, 让 mineru-api 输出 `_pages.md` (按页 markdown), mineru-web worker 依赖 |
| `BUILD.md` | 本文件 |

业务层配置 (parsed.py / nginx.conf / mineru.json) 在 `config/mineru/` (compose 挂载)。
