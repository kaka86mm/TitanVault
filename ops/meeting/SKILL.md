---
name: titanvault-meeting
description: |
  会议录音转会议纪要。把任意音频/视频文件变成结构化 markdown 纪要——上传到 Aham Voice
  完成转写+说话人分离+纪要生成，或用 SenseVoice 快速出文字稿。
  当用户说「处理这个会议录音」「帮我把这个会议转成纪要」「转写这段录音」
  「生成会议纪要」「快速转写」「这个会开了什么」时使用。
  English: "process this meeting", "transcribe recording", "meeting minutes", "what was said in this meeting".
version: 1.0.0
author: TitanVault
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [会议, 录音, 转写, ASR, 会议纪要, AhamVoice, SenseVoice, 办公]
---

# 会议录音处理 — Hermes Skill

把会议录音变成 markdown 纪要。两个引擎，一个 skill：

| 场景 | 引擎 | 产物 | 何时用 |
|---|---|---|---|
| **完整模式** (默认) | Aham Voice :8765 | 转写 + 说话人分离 + 结构化纪要 + 情绪 | 要正式纪要、多人会议、要分发 |
| **快速模式** | SenseVoice :9991 | 纯文字稿 (无分离) | 只要文字、单人发言、急着要 |

**判断规则**：用户提到「纪要」「谁说了什么」「多人」「分发」→ 完整模式。用户提到「快速」「只要文字」「文字稿」→ 快速模式。不确定 → 完整模式（更全）。

## 黄金规则：调用确定性脚本，不要自己拼 curl

**不要自己拼 curl 调 Aham API。** 脚本 `ops/meeting/meeting.sh` 封装了 cookie 认证、轮询、导出等所有边界情况。直接调用：

```
terminal(command="bash $TITANVAULT_REPO/ops/meeting/meeting.sh <子命令> [参数]", workdir="$TITANVAULT_REPO")
```

## 工作流

### 场景 A: 完整处理（默认）——「帮我把这个会议转成纪要」

```
Step 1: 确认文件存在 + 探测格式
  file <录音路径>          # 确认是音频/视频
  ls -lh <录音路径>        # 看大小 (Aham 上限 2GB)

Step 2: 🔴 CHECKPOINT · 跟用户确认模式 + 说话人数
  「这个会议我按【完整模式】处理（转写+说话人分离+纪要），预计说话人 N 人。
    如果只要快速文字稿，告诉我用快速模式。继续？」
  - 用户确认 → 继续
  - 用户要快速模式 → 跳到场景 B
  注意: 完整模式首次 ASR 要下载模型 + 实时处理, 1小时录音约需 5-15 分钟

Step 3: 上传
  bash ops/meeting/meeting.sh transcribe <文件> --title "<标题>" --speakers <N>
  → 输出 recording_id (rec_xxx), 记下来

Step 4: 等待 + 轮询 (这是异步的, 别干等)
  bash ops/meeting/meeting.sh wait <recording_id> --for all --timeout 1800
  → 阻塞直到 ASR + 纪要都完成

Step 5: 导出纪要
  bash ops/meeting/meeting.sh minutes <recording_id> -o <标题>-纪要.md
  → 纪要存为 markdown 文件

Step 6: 交付
  告诉用户: 纪要路径 + 一句话摘要 (从纪要开头读)。
  如果纪要里 action items 不清晰, 提醒用户可以用 revise 接口调整。
```

### 场景 B: 快速转写——「快速转写这段」「我只要文字稿」

```
🔴 GATE (非阻塞, 但必须告知): 快速模式 = 无说话人分离、无纪要、无情绪。
  如果用户后续要分发或要"谁说了什么", 必须改用完整模式。
  告知后直接执行, 不等确认 (用户已明确要"快速")。

bash ops/meeting/meeting.sh quick <文件> -o <输出.md>
→ 直接出纯文字稿 (SenseVoice, 通常 1 小时录音 2-5 分钟)
→ 无说话人分离、无纪要、无情绪
```

### 场景 C: 处理到一半查状态——「那个会议转完了吗」

```
bash ops/meeting/meeting.sh status <recording_id>
→ 显示 ASR/纪要/情绪 各阶段状态
```

## 失败模式速查表（if-then）

| 触发条件 | 一线修复 | 仍失败兜底 |
|---|---|---|
| Aham :8765 不通 (login/transcribe 报连接错误) | `docker compose --profile ai-capability ps aham-voice-web` 看是否 Up; 没起则 `docker compose --profile ai-capability up -d aham-voice-web` | 检查 ROCm: `rocm-smi`; GPU 不识别→这是硬件问题, 升级到 titanvault-ops skill 处理 |
| 文件过大 (>2GB) | 用 ffmpeg 切分: `ffmpeg -i big.m4a -t 3600 -c copy part1.m4a` (按小时切) | 提醒用户分段录音 |
| `transcribe` 返回 401 | Aham 启用了密码但 cookie 过期 → `meeting.sh login` 重新登录 | 确认 .env 里 AHAMVOICE_ACCESS_PASSWORD 正确 |
| `wait` 超时 (ASR 长时间 running) | 首次运行要下 ~4GB ASR 模型, 可能很慢; `docker logs aham-voice-web --tail 20` 看进度 | 模型下载失败→检查网络/磁盘, 升级处理 |
| `wait` 显示 summary failed | 纪要 LLM (走 LiteLLM) 失败; 确认 `litellm:4000` 可用; 重试 `POST /api/recordings/<id>/summarize` | 用纯转写 (transcript) 兜底, 告诉用户纪要生成失败但有文字稿 |
| SenseVoice quick 模式失败 (:9991 不通) | `docker compose --profile ai-capability ps sensevoice`; 没起则拉起 | 改用完整模式 (Aham 自带 ASR, 不依赖 SenseVoice) |
| 音频格式不支持 (Aham/SenseVoice 拒绝) | `ffmpeg -i <in> -ar 16000 -ac 1 -c:a opus <out>.ogg` 转码后重试 | 提醒用户提供 wav/mp3/m4a/ogg/webm 常见格式 |
| **SenseVoice quick 模式中文识别成 "chinese letter"** | 输入音频不是真正的中文人声 (如用英文 TTS 生成中文, 或音频是噪音/静音)。SenseVoice 中文本身正常, 用真实中文录音验证过 | 确认音频是真人中文录音; 用 `file <audio>` 看格式, 16kHz wav 最佳 |
| 拿到纪要但内容是乱码/空 | ASR 可能在处理中, summary 还没真完成; `status` 确认 summary_status=done | 重跑: `meeting.sh wait <id> --for summary` 再导出 |

## 权限边界

| 动作 | 允许? | 方式 |
|---|---|---|
| 读录音文件 / 探测格式 | ✅ | `file`, `ls`, `ffprobe` |
| 上传到本机 Aham / SenseVoice | ✅ | `meeting.sh transcribe/quick` |
| 轮询 / 导出纪要 | ✅ | `meeting.sh wait/status/minutes/transcript` |
| 用 ffmpeg 转码/切分音频 | ✅ 低风险 | 只读原文件, 输出新文件 |
| 调用 Aham revise 接口改纪要 | ✅ | `POST /api/recordings/<id>/summary/revise` |
| **删除 recording** | ❌ 升级 | 告诉用户, 不要自动删 (纪要可能还要) |
| **改 Aham 配置 / .env** | ❌ 升级 | 提议 diff, 不直接改 |
| **录音上传到外部服务** | ❌ 拒绝 | 会议录音含敏感信息, 只在本机处理, 永不上传外部 |

## 反模式黑名单（绝不做的事）

| # | 反模式 | 为什么 / 替代 |
|---|---|---|
| 1 | 自己拼 curl 调 Aham API | 漏掉 cookie 认证、轮询逻辑、错误处理。用 `meeting.sh` |
| 2 | 用完整模式却不告诉用户预计耗时 | 1 小时录音可能等 15 分钟。上传前必须告知 |
| 3 | 干等 ASR 不轮询 | 用 `wait` 子命令阻塞轮询, 别在对话里 sleep |
| 4 | 拿到纪要就结束, 不给摘要 | 用户要打开文件才知道内容。必须在对话里给一句话摘要 |
| 5 | 把录音上传到云端转写 | 违反数据本地原则。只用本机 Aham/SenseVoice |
| 6 | 处理超大文件不切分 | >2GB Aham 拒绝。先 ffmpeg 切分 |
| 7 | 快速模式产出当正式纪要分发 | 快速模式无说话人分离, 会误导。分发必须用完整模式 |

## 引擎技术细节（遇到问题时查）

- **Aham Voice** (:8765): 完整产品。Cookie 认证 (HttpOnly `aham_token`, 无密码模式跳过)。进程内加载 FunASR (Paraformer+VAD+CAM++说话人+emotion2vec)。纪要走 LiteLLM→Qwen3.6-35B。**不调用 SenseVoice**——它自带 ASR。
- **SenseVoice** (:9991): 纯 ASR API (OpenAI 兼容 `/v1/audio/transcriptions`)。无认证。适合脚本化快速转写, 无说话人分离。
- 上传: `POST /api/recordings` (multipart), `auto_process=true` 自动触发 ASR→纪要。
- 轮询: `GET /api/recordings/<id>` 读 `tasks.{asr,summary,emotion}_status`。
- 导出: `GET /api/recordings/<id>/export/{summary,transcript}.md`。

## 环境变量（从 $TITANVAULT_REPO/.env 读）

```
AHAMVOICE_URL=http://localhost:8765
AHAMVOICE_ACCESS_PASSWORD=     # 空=无密码 (内网默认)
SENSEVOICE_URL=http://localhost:9991
MEETING_TIMEOUT=1800           # 等待超时 (秒)
```
