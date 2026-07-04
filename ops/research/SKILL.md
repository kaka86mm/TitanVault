---
name: titanvault-research
description: |
  深度研究 agent。输入一个问题，QUEST-9B 自主搜索网页→阅读详情→多轮迭代→
  生成带引用的研究报告。基于 OSU NLP 的 QUEST deep research 模型。
  当用户说「深度研究一下 XX」「帮我调研 XX」「写一份关于 XX 的研究报告」
  「deep research」「全面分析一下 XX」时使用。
  English: "research X", "deep dive into X", "investigate X thoroughly", "write a report on X".
version: 1.0.0
author: TitanVault
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [深度研究, deep research, QUEST, 调研, 报告, 搜索, 网页抓取]
---

# 深度研究 Agent — Hermes Skill

用 QUEST-9B deep research 模型做自主研究：给定一个问题，agent 会搜索网页、阅读页面、
多轮迭代，最终产出带引用的 markdown 研究报告。**100% 本地**——搜索用 SearXNG，
阅读用 requests/trafilatura，推理用 QUEST-9B（llama.cpp），无外部 API。

## 引擎

| 组件 | 服务 | 作用 |
|---|---|---|
| **QUEST-9B** (Q4) | llama.cpp :8093 | deep research 专用模型（OSU NLP 训练）|
| **SearXNG** | :8087 | 元搜索（聚合 Google/Bing/等）|
| **网页抓取** | requests + trafilatura | 页面阅读 + 正文提取 |
| **记忆/摘要** | LiteLLM :4000 → 35B | 长上下文压缩 |

## 黄金规则：调用 run_quest.py

agent 的搜索/阅读/循环逻辑都在 `ops/research/` 里封装好了。直接调：

```
terminal(command="$HOME/quest-venv/bin/python $TITANVAULT_REPO/ops/research/run_quest.py \"<研究问题>\"", workdir="$TITANVAULT_REPO")
```

## 工作流

### 场景 A: 深度研究一个问题

```
Step 1: 🔴 GATE · 跟用户确认问题范围
  「我用 QUEST deep research 来调研【XX】。这会自主搜索 10-20 个网页，
    阅读 5-10 个页面，生成带引用的报告。预计 3-5 分钟。继续？」
  - 用户补充关注点 → 记下来加到问题里
  - 用户确认 → 继续

Step 2: 运行
  $HOME/quest-venv/bin/python ops/research/run_quest.py "XX 的 YY 方面怎么样?"

Step 3: 交付
  报告保存到 /data/quest-reports/quest-<时间戳>-<问题>.md
  在对话里给摘要 + 文件路径。
  问用户: 要不要把这份报告存入知识库 (Open Notebook)?
  - 要 → 调 titanvault-ingest skill 把报告存入
```

### 场景 B: 研究报告存入知识库（串联 ingest）

研究完成后，报告天然适合存入 Open Notebook 做 RAG：
```
bash ops/ingest/ingest.sh text "$(cat /data/quest-reports/quest-*.md)" --title "调研: XX"
```
之后可以就这份报告提问：`bash ops/ingest/ingest.sh ask "报告里提到的 YY 是什么意思?"`

## 失败模式速查表

| 触发条件 | 一线修复 | 仍失败兜底 |
|---|---|---|
| QUEST-9B :8093 不通 | `systemctl status llama-quest`; 没起则 `sudo systemctl start llama-quest` | 手动起: `LD_LIBRARY_PATH=/opt/llama.cpp /opt/llama.cpp/llama-server -m /data/models/llm/QUEST-9B-Q4-nomtp.gguf --port 8093 -ngl 99 -c 32768` |
| "exceeds context size" | context 太小; 重启服务用 `-c 32768` 或更大 | 减少 max_turns (agent 循环轮数) |
| SearXNG :8087 不通 | `docker compose --profile apps ps searxng`; 没起则拉起 | research 无法工作 (搜索是核心) |
| visit 总是失败 | 网络问题 (部分外站不可达); 检查 `curl -sI <url>` | 搜索结果的 snippet 仍可用, 只是没全文 |
| 报告质量差/跑题 | QUEST-9B 是 9B 模型, 复杂问题可能不够; 换 35B (慢但更强) | 调整问题表述, 更具体 |
| agent 循环不终止 | max_turns 限制兜底; 检查 run_quest.py 的 max_turns 设置 | 手动 Ctrl-C, 看已有搜索结果 |
| torch/transformers 报错 | QUEST venv 可能坏了; 重建: `uv venv ~/quest-venv --python 3.10 && uv pip install ...` | 升级 transformers |

## 权限边界

| 动作 | 允许? | 方式 |
|---|---|---|
| 搜索网页 (SearXNG) | ✅ | QUEST 自主决定 query |
| 抓取网页内容 | ✅ | visit 工具 (requests) |
| 调用 QUEST-9B / LiteLLM | ✅ | 本机推理 |
| 保存报告到 /data/quest-reports | ✅ | run_quest.py 自动 |
| **访问需要登录的页面** | ❌ 拒绝 | 只抓公开页面 |
| **执行用户给的 Python 代码** | ⚠️ 升级 | python 工具默认关闭, 需要时显式开启 |

## 反模式黑名单

| # | 反模式 | 为什么 / 替代 |
|---|---|---|
| 1 | 不确认问题就跑研究 | 研究要 3-5 分钟, 跑错方向浪费时间。先确认 |
| 2 | 把 max_turns 设太大 (>10) | 每轮要 LLM 推理, 太多会超时。4-6 轮够了 |
| 3 | 研究完不存报告 | 报告有复用价值, 存入 Open Notebook 做 RAG |
| 4 | 用 QUEST 做简单事实查询 | "今天天气" 这种用 SearXNG 直接搜更快, QUEST 是深度研究 |
| 5 | 期望 9B 质量 = 35B | 9B 适合快速研究; 要高质量用 35B (改 endpoint) |

## 技术细节

- **QUEST-9B**：OSU NLP 2026 年开源的 deep research agent（2B-35B 系列，我们用 9B 平衡速度/质量）。
  基于 Qwen3.5 架构，经 mid-training + SFT + RL 训练，专精搜索-阅读-报告循环。
- **GGUF 转换**：原始是 `Qwen3_5ForConditionalGeneration`（多模态），转换为纯文本 GGUF 时需 `--no-mtp`（去掉 MTP 层）+ patch `block_count`（修 off-by-one bug）。
- **工具接口**：基于 `qwen_agent.tools.base.BaseTool`，search/visit 是本地化改写（SearXNG/requests 替换 Serper/Jina）。
- **端口 8093**：避开已占用的 8085(filebrowser)/8086 等。

## 环境变量（从 $TITANVAULT_REPO/.env 读）

```
SEARXNG_URL=http://localhost:8087
LITELLM_MASTER_KEY=          # memory/summary 模型用
QUEST_MODEL_PATH=            # QUEST-9B HF 目录 (tokenizer, 可选)
```
