# aham-voice-web 本地构建说明

录音转写 + 说话人分离 + 声学情绪 + 会议纪要 Web 应用 (MIT, 用户原创项目)。
本目录含完整源码 (backend/ + frontend/dist/), 在 395 上本地 build。

## 为什么不进 CI / 不推 GHCR

- 基镜像 `rocm/pytorch:rocm7.2.3_ubuntu22.04_py3.10_pytorch_release_2.9.1` (官方, ~13GB),
  含完整 ROCm 7.2.3 + PyTorch 2.9.1。虽可 docker pull, 但仅 AMD gfx1151 (Ryogen AI Max+ 395)
  能用 GPU, CI runner 无此硬件 — 与 `images/mineru-rocm/` 同策略。
- 应用本身 1.5MB, 源码进仓库 (与 sensevoice / token-usage-api 一致)。

## 构建前置

基镜像 `rocm/pytorch:rocm7.2.3_ubuntu22.04_py3.10_pytorch_release_2.9.1` 是 AMD 官方镜像
(Verified Publisher), `docker pull` 即可, gfx1151 已验证 `torch.cuda.is_available()=True`。

## 构建命令

```bash
# ROCm 版 (395 默认):
docker build -t aham-voice-web:rocm \
    -f images/aham-voice-web/Dockerfile.rocm images/aham-voice-web/

# 国内构建慢走阿里云源:
docker build -t aham-voice-web:rocm \
    --build-arg USE_CN_MIRROR=1 \
    -f images/aham-voice-web/Dockerfile.rocm images/aham-voice-web/

# CPU 版 (无 GPU 宿主回退, CI 用):
docker build -t aham-voice-web:cpu \
    -f images/aham-voice-web/Dockerfile.cpu images/aham-voice-web/
```

## GPU 暴露

compose (`compose/ai-capability.yml`) 通过 `devices: ["/dev/kfd", "/dev/dri"]`
+ `group_add: ["video"]` 把核显直通进容器 (与 mineru-api 完全一致)。
`AHAMVOICE_ASR_DEVICE=cuda` 是因为 torch ROCm 走 HIP 的 cuda 兼容层 (非 NVIDIA CUDA)。

## 模型 (ASR, ~4GB, 不进镜像)

容器启动时 `model_download.py` 检测并自动从 modelscope 拉 5 个 FunASR/emotion2vec 模型:

| 模型 | 用途 |
|---|---|
| `speech_fsmn_vad_zh-cn-16k-common-pytorch` | 语音端点检测 (VAD) |
| `punc_ct-transformer_cn-en-common-vocab471067-large` | 标点恢复 |
| `speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch` | 转写 (Paraformer) |
| `speech_campplus_sv_zh-cn_16k-common` | 说话人特征 (声纹) |
| `emotion2vec_plus_large` | 声学情绪 |

挂载到 `${DATA_DIR}/models/ahamvoice`, 与全局模型库统一管理。
**注意**: 这 5 个模型由 `iic` org 发布 (modelscope 原生), 应用写死从 modelscope 拉,
**不读全局 `MODEL_SOURCE`** (modelscope 对 `iic` org 是首选源, 见发行版决策记录)。

## LLM 接入

应用 `get_llm_config()` 读 `LLM_API_KEY/LLM_API_BASE/LLM_MODEL` 三个 env,
compose 已注入指向发行版 LiteLLM 网关 (复用本机 35B), 会议纪要零配置走本机。
用户也可在 Web UI 设置页改指向任意 OpenAI 兼容端点。
