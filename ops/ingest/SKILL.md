---
name: mozin-ingest
description: |
  把任意 URL / 文件 / 文本存入知识库 (Open Notebook), 并支持就内容提问。
  PDF 自动走 MinerU 解析, 网页直接抓取, 全部本地处理。
  当用户说「把这个存进知识库」「这篇加到我的笔记里」「帮我读这个链接存下来」
  「这篇 PDF 存进去」「这个链接讲什么, 存下来之后问」时使用。
  English: "ingest this", "add to knowledge base", "save this URL to notebook", "store this PDF".
version: 1.0.0
author: Mozin
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [知识库, RAG, OpenNotebook, MinerU, PDF, 网页抓取, 内容入库, 学习]
---

# 知识入库与问答 — Hermes Skill

把任意内容存入 Open Notebook 知识库, 让用户日后能就这些内容提问 (RAG)。

| 输入类型 | 处理路径 | 产物 |
|---|---|---|
| **URL** (网页) | ON 直接抓取 → embedding | 可检索可问答的 source |
| **PDF** | MinerU 解析为 markdown + 原 PDF 备份 | 表格/公式保留的高质量 source |
| **DOCX/TXT/MD/EPUB** | ON 上传 + 内置解析 | 可检索 source |
| **纯文本** | 直接存为文本 source | 可检索 source |

## 黄金规则：调用确定性脚本，不要自己拼 curl

Open Notebook 的 API 路径前缀不同版本不一致 (`/api/sources` vs `/sources`)、字段名有差异、PDF 要不要走 MinerU 有判断逻辑。**这些都封装在 `ops/ingest/ingest.sh` 里。** 直接调用：

```
terminal(command="bash $MOZIN_REPO/ops/ingest/ingest.sh <子命令> [参数]", workdir="$MOZIN_REPO")
```

## 工作流

### 场景 A: 存一个 URL ——「把这个链接存进知识库」

```
Step 1: 🔴 CHECKPOINT · 跟用户确认 (如果 URL 看起来可疑/超长)
  「我把这个链接存入 Open Notebook, ON 会抓取网页内容并建立索引。
    标题用 [网页标题/自定义], 继续？」
  - 内部链接/明显正常 → 可跳过确认直接存
  - 不确定来源 → 先 fetch 看一眼内容再决定

Step 2: 入库
  bash ops/ingest/ingest.sh url <URL> --title "<标题>"
  → 输出 source_id

Step 3: 确认 + 告知
  「✅ 已入库 (source_id=xxx)。ON 后台正在抓取+建索引, 约 1-3 分钟后可问答。
    现在可以问关于这篇内容的问题。」
```

### 场景 B: 存一个 PDF ——「这篇 PDF 加到知识库」

```
Step 1: 确认文件 + 大小
  ls -lh <PDF路径>
  file <PDF路径>

Step 2: 检查 MinerU 状态 (PDF 质量的关键)
  bash ops/ingest/ingest.sh probe
  → 看 MinerU 那行是否 ✅

Step 3: 🔴 CHECKPOINT · 告知处理方式
  「这个 PDF 我用【MinerU 解析】(保留表格/公式/图表), 解析后存为可问答的文本源,
    同时备份原 PDF。大 PDF 解析可能要几分钟。继续？」
  - MinerU 不可用 → 降级提示: 「MinerU 暂不可用, 会直接上传, 表格/公式可能解析不全」
  - 用户确认 → 继续

Step 4: 入库
  bash ops/ingest/ingest.sh pdf <路径> --title "<标题>"
  → 内部: MinerU 解析 → 存 markdown 文本源 + 原PDF备份

Step 5: 确认
  「✅ 已入库。MinerU 解析了 N 行 markdown, 原文件也备份了。
    可以直接问关于这篇 PDF 的问题。」
```

### 场景 C: 存文本 ——「把这段话存进知识库」

```
echo "<文本>" | bash ops/ingest/ingest.sh text - --title "<标题>"
# 或
bash ops/ingest/ingest.sh text "<长文本>" --title "<标题>"
```

### 场景 D: 就已入库内容提问 ——「这篇报告的核心结论?」

```
🔴 GATE (ask 前判断): 如果是刚入库的 source (用户 5 分钟内存的),
  先告知「刚入库的内容还在建索引, 可能要等 1-3 分钟才能问答」。
  已入库超过 5 分钟 → 直接 ask。

bash ops/ingest/ingest.sh ask "<问题>"
→ RAG 检索 + LLM 生成答案

🔴 GATE (ask 返回空/无关后): 不要直接重述原问题。
  先 bash ops/ingest/ingest.sh sources 看那个 source 的 status:
    - processing → 告诉用户还在处理, 等会儿再问
    - failed     → 触发重试 POST /sources/<id>/retry
    - ready 但空  → 换问法或缩小范围, 不要机械重试
```

**回答质量问题**：如果答案明显无关或为空，先检查 source 是否处理完成：
```
bash ops/ingest/ingest.sh sources
→ 看那个 source 的状态字段 (processing/ready/failed)
```

### 场景 E: 诊断 ——「知识库怎么不工作了」

```
bash ops/ingest/ingest.sh probe
→ 检查 ON 健康、端点前缀、MinerU、认证, 一眼定位问题
```

## 失败模式速查表（if-then）

| 触发条件 | 一线修复 | 仍失败兜底 |
|---|---|---|
| ON :5055 不通 (probe 全红) | `docker compose --profile apps ps open-notebook`; 没起则 `up -d open-notebook` | 启动慢 (surrealdb 迁移), 等 3 分钟再 probe |
| url 存入后 ask 返回空 | ON 还在抓取+embedding (1-3 min); `sources` 看 status; 等 60s 重试 | source 状态=failed → 重试 `POST /sources/<id>/retry` |
| PDF MinerU 解析超时/失败 | `curl $MINERU_URL/health`; MinerU 没起则 `docker compose --profile ai-capability up -d mineru-api` | 降级: 直接 `file` 子命令 (不走 MinerU), 告知用户表格/公式可能丢 |
| PDF 太大 (>100MB) MinerU OOM | 先拆分: `pdftk big.pdf cat 1-50 output part1.pdf` (按页) | 提醒用户用小一点的 PDF, 或只存关键章节 |
| ask 答案明显跑题 | ON 的 embedding 模型没配好; 检查 `setup-open-notebook.sh` 是否跑过; `GET /api/models` 看 embedding 是否就绪 | 升级到 mozin-ops 处理模型配置 |
| **ask 中文问题报 OUTPUT_PARSING_FAILURE** | ON 的 LLM 用中文问时 JSON 输出格式错误 (英文正常)。已知限制, 非脚本 bug | 换英文提问, 或在完整模式 (`/api/chat/execute`) 下用中文 |
| ask 返回 "Ask operation failed" | 模型 ID 没传对; ingest.sh 会自动从 /api/models/defaults 获取, 检查该端点是否返回有效 model_id | 手动指定: 看 `/api/models` 拿一个 language 类型的 model id |
| text 子命令字段名不对 (string vs content) | ingest.sh 已自动重试两个字段名 | ON 版本太旧/太新, 看 `/openapi.json` 确认字段 |
| 认证 401/403 | ON 启用了密码; 确认 .env 里 OPEN_NOTEBOOK_PASSWORD; probe 会显示密码模式 | 重跑 setup-open-notebook.sh |
| PDF 是扫描件 (纯图片) | MinerU 会做 OCR, 但慢; 正常等 | OCR 质量差→提醒用户提供文字版 PDF |

## 权限边界

| 动作 | 允许? | 方式 |
|---|---|---|
| 读用户提供的文件 | ✅ | `ls`, `file`, `cat` |
| 存入本机 ON / MinerU 解析 | ✅ | `ingest.sh url/file/text/pdf` |
| RAG 问答 | ✅ | `ingest.sh ask` |
| 列出 notebook / source | ✅ | `ingest.sh notebooks/sources` |
| 抓取用户指定的 URL (本机 ON 抓) | ✅ | `ingest.sh url` (ON 服务端抓取, 非脚本抓) |
| **删除 source / notebook** | ❌ 升级 | 告诉用户, 不自动删 |
| **改 ON 配置 / 模型** | ❌ 升级 | 提议 diff, 不直接改 |
| **抓取用户未指定的 URL** | ❌ 拒绝 | 只存用户明确给的 URL, 不自动扩展爬取 |
| **上传文件到外部服务** | ❌ 拒绝 | 所有内容只进本机 ON, 永不上传外部 |

## 反模式黑名单（绝不做的事）

| # | 反模式 | 为什么 / 替代 |
|---|---|---|
| 1 | 自己拼 curl 调 ON API | 路径前缀、字段名、认证都有版本差异。用 `ingest.sh` |
| 2 | PDF 不走 MinerU 直接传 ON | 丢表格/公式/图表。PDF 必须先 probe 检查 MinerU |
| 3 | 存入后不告诉用户「还要等处理」 | embedding 是异步的, 用户马上问会得到空答案, 以为坏了 |
| 4 | ask 返回空就判定「没存进去」 | 80% 是还在处理, 不是失败。先 `sources` 看状态 |
| 5 | 抓取用户没给的 URL | 迷失方向 + 隐私风险。严格只处理用户指定的输入 |
| 6 | 一次存几十个 URL 不分批 | ON 处理是串行的, 批量会堆积。提醒用户分批, 每批等前一批 ready |
| 7 | 把扫描件 PDF 当文字 PDF | 扫描件要 OCR (MinerU 支持), 直接传可能出空白。先 `pdftotext` 试探有无文字层 |
| 8 | ask 答非所问就直接重述原问题 | 换个问法或缩小范围, 或检查 source 是否处理完。机械重试无效 |

## 技术细节（排障时查）

- **Open Notebook** (:5055, UI :8088): 无认证 (本机默认) 或密码 (`OPEN_NOTEBOOK_PASSWORD`)。SurrealDB 后端。Embedding 走 LiteLLM→Qwen3-Embedding。Source 异步处理: 上传立即返回 id, 后台抓取/embedding。
- **路径前缀**: 探测 `/openapi.json` 自动确定 `/api/sources` 或 `/sources`。结果缓存 1 小时 (`/tmp/ingest_on_prefix.cache`)。
- **MinerU** (:18080 mineru-api): 无认证。`POST /file_parse` (multipart file) → markdown。GPU 解析, 大 PDF 慢。
- **/ask 是 SSE 流式**: `curl -N`, 取 `type=final_answer` 的 content 拼接。
- **ON 不能路径反代** (Caddyfile 注明): 必须用原始端口 :5055, 不能走 `/open-notebook/` 子路径。

## 环境变量（从 $MOZIN_REPO/.env 读）

```
OPEN_NOTEBOOK_URL=http://localhost:5055
OPEN_NOTEBOOK_PASSWORD=           # 空=无密码
MINERU_API_URL=http://localhost:18080
```
