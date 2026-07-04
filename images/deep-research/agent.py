"""
agent.py — Deep Research Agent (ReAct 循环 + 报告迭代)

核心特性:
1. ReAct 循环: LLM → 解析 tool_call → 执行 search/visit → 回填 → 循环
2. 报告迭代: ResearchContext 维护历史, 支持多轮改进
3. SSE 事件: 每步通过 on_event 回调推送进度
4. 搜索去重: 迭代时跳过已搜过的 query
"""
import os
import re
import json
import time
import hashlib
from typing import List, Dict, Optional, Callable
from datetime import datetime

from openai import OpenAI

from tools import search as tool_search, visit as tool_visit, \
    exa_search as tool_exa, twitter_search as tool_twitter, \
    xiaohongshu_search as tool_xhs, \
    verify_claim as tool_verify_claim, verify_url as tool_verify_url

# ============================================================================
# Prompts
# ============================================================================

INITIAL_PROMPT = """You are QUEST, a deep research agent. Today's date: {today}. Answer the user's question by SEARCHING the web, reading pages, then writing a research report.

## Tools (output <tool_call> to use one)
- exa: BEST search (semantic, high quality). Example: <tool_call>{{"name":"exa","arguments":{{"query":["your query"]}}}}}}</tool_call>
- search: Web search (google/bing). Same format, name="search".
- twitter: Twitter/X discussions & opinions. name="twitter".
- xiaohongshu: 小红书 Chinese lifestyle reviews. name="xiaohongshu".
- visit: Read a URL. {{"name":"visit","arguments":{{"url":["URL"],"goal":"..."}}}}

## Research Strategy (CRITICAL — follow strictly)
1. You MUST call tools. Do NOT answer from memory.
2. BREAK DOWN the question into 3-5 sub-questions, search EACH separately.
3. Search at least 5 times total (different angles).
4. Start with exa, then search for follow-ups.
5. Visit 3-5 key pages to read details (not just snippets).

## Anti-Hallucination Rules (CRITICAL)
- NEVER fabricate numbers, prices, dates, or statistics. Only use data from search results.
- NEVER reference future dates. If you don't have data for a time period, say "data not available".
- Every number/price/date in your report MUST come from a visited page. If unsure, omit it.
- Write in ONE language only (match the user's question language).
- Do NOT repeat content. Write the report ONCE.

## Report Format
```
# [Title]

> **Summary**: 2-3 sentence overview.

## 1. [Section]
[Detailed analysis with data from search results, cited with [source: URL]]

## N. Conclusion
```

## Citation Rules
- Use [source: URL] at the END of sentences with data.
- Every key fact MUST have a citation from a page you visited.

When you have enough info, STOP calling tools and write the report ONCE."""


ITERATE_PROMPT = """You are QUEST, a deep research agent. The user wants to IMPROVE an existing research report.

## Previous Report (v{n_versions})
{previous_report}

## Existing Knowledge Already Gathered
{existing_knowledge}

## User's Instruction for This Iteration
{user_instruction}

## Your Task
Based on the user's instruction, improve the report. You may:
- Search for NEW information to fill gaps
- Visit new pages for more detail
- Restructure or rewrite sections
- Add new sections as requested

Do NOT repeat searches you've already done (listed in existing knowledge).
When done, output the COMPLETE updated report in markdown.

## Available Tools
- search: {{"name": "search", "arguments": {{"query": ["query"]}}}}
- exa: {{"name": "exa", "arguments": {{"query": ["query"]}}}} (semantic search, English/technical)
- twitter: {{"name": "twitter", "arguments": {{"query": ["query"]}}}} (social discussions)
- xiaohongshu: {{"name": "xiaohongshu", "arguments": {{"query": ["query"]}}}} (中文生活消费)
- visit: {{"name": "visit", "arguments": {{"url": ["url"], "goal": "..."}}}}

To call a tool:
<tool_call>
{{"name": "search", "arguments": {{"query": ["new query"]}}}}
</tool_call>

When you have enough new info, output the complete updated report."""


# ============================================================================
# ResearchContext — 迭代核心
# ============================================================================

class ResearchContext:
    """维护一个研究 session 的全部状态, 支持迭代。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = datetime.now().isoformat()
        self.status = "active"  # active / finalized
        self.messages: List[dict] = []
        self.searched_queries: List[str] = []
        self.visited_urls: Dict[str, str] = {}  # url -> content snippet
        self.versions: List[dict] = []
        self.current_version = 0
        self.attachments: List[dict] = []  # [{filename, md, source_type}]

    @property
    def latest_report(self) -> str:
        if self.versions:
            return self.versions[-1].get("content", "")
        return ""

    @property
    def n_versions(self) -> int:
        return len(self.versions)

    def add_message(self, content: str, is_followup: bool = False):
        self.messages.append({
            "role": "user",
            "content": content,
            "turn_id": len(self.messages),
            "is_followup": is_followup,
        })

    def add_search(self, query: str):
        if query not in self.searched_queries:
            self.searched_queries.append(query)

    def add_visit(self, url: str, snippet: str):
        self.visited_urls[url] = snippet[:500]

    def add_version(self, content: str, changes: str = ""):
        self.current_version += 1
        self.versions.append({
            "version": self.current_version,
            "content": content,
            "changes": changes,
            "timestamp": datetime.now().isoformat(),
        })

    def add_attachment(self, filename: str, md: str, source_type: str):
        self.attachments.append({
            "filename": filename, "md": md, "source_type": source_type,
        })

    def format_attachments(self) -> str:
        """格式化附件内容供 system prompt 注入。"""
        if not self.attachments:
            return ""
        parts = ["\n\n## USER-PROVIDED DOCUMENTS (High Trust Source)"]
        parts.append("The following documents are provided by the user. "
                      "They have HIGHER credibility than web search results. "
                      "Prioritize information from these documents and cite them as "
                      "[📎 source: filename]. Cross-reference web search results "
                      "against these documents when possible.\n")
        for att in self.attachments:
            content = att.get("md", "")[:5000]  # 每个附件截断到 5000 字符
            parts.append(f"### [USER_DOCUMENT: {att['filename']}]\n{content}\n")
        return "\n".join(parts)

    def summarize_visited(self, max_items: int = 10) -> str:
        """给 agent 的已有知识摘要。"""
        if not self.visited_urls:
            return "(no prior research)"
        lines = [f"Already searched: {', '.join(self.searched_queries[:10])}"]
        lines.append(f"Already visited {len(self.visited_urls)} pages:")
        for url, snippet in list(self.visited_urls.items())[:max_items]:
            lines.append(f"  - {url}: {snippet[:100]}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "status": self.status,
            "messages": self.messages,
            "searched_queries": self.searched_queries,
            "visited_urls": self.visited_urls,
            "versions": self.versions,
            "current_version": self.current_version,
            "attachments": self.attachments,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ResearchContext":
        ctx = cls(d["session_id"])
        ctx.created_at = d.get("created_at", "")
        ctx.status = d.get("status", "active")
        ctx.messages = d.get("messages", [])
        ctx.searched_queries = d.get("searched_queries", [])
        ctx.visited_urls = d.get("visited_urls", {})
        ctx.versions = d.get("versions", [])
        ctx.current_version = d.get("current_version", 0)
        ctx.attachments = d.get("attachments", [])
        return ctx


# ============================================================================
# ResearchAgent — ReAct 循环
# ============================================================================

class ResearchAgent:
    """QUEST-9B 驱动的 deep research agent, 支持首轮 + 迭代。"""

    def __init__(
        self,
        endpoint: str = "http://host-gateway:8093/v1",
        api_key: str = "EMPTY",
        model: str = "QUEST-9B",
        max_turns: int = 6,
    ):
        self.client = OpenAI(api_key=api_key, base_url=endpoint)
        self.model = model
        self.max_turns = max_turns

    def run(
        self,
        question: str,
        context: Optional[ResearchContext] = None,
        on_event: Callable = None,
    ) -> str:
        """运行研究 (首轮或迭代)。返回报告 markdown。

        context 非空 = 迭代模式。
        on_event(event_dict) = SSE 事件回调。
        """
        is_iteration = context is not None and context.n_versions > 0

        # 构建 system prompt
        if is_iteration:
            system = ITERATE_PROMPT.format(
                n_versions=context.n_versions,
                previous_report=context.latest_report[:6000],
                existing_knowledge=context.summarize_visited(),
                user_instruction=question,
            )
            skip_queries = context.searched_queries
        else:
            system = INITIAL_PROMPT.format(today=datetime.now().strftime("%Y-%m-%d"))
            skip_queries = []
            context = context or ResearchContext("temp")

        # 注入用户附件 (高可信度知识)
        attachment_text = context.format_attachments()
        if attachment_text:
            system = system + attachment_text

        def emit(event):
            if on_event:
                on_event(event)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ]

        emit({"type": "start", "question": question,
              "iteration": is_iteration, "max_turns": self.max_turns})

        # ── 预热搜索: 自动用 exa + searxng 各搜一次, 注入初始上下文 ──
        # 只给标题+URL (不给完整 snippet), 引导 QUEST 自己 visit 深入阅读
        primer = self._primer_search(question, context, emit)
        if primer:
            messages.append({"role": "user",
                             "content": f"<tool_response>\n{primer}\n</tool_response>\n\n"
                                        f"These are initial results (titles only). "
                                        f"Now break down the question into sub-questions and search each. "
                                        f"Visit key pages for details. Do NOT write the report yet."})

        for turn in range(self.max_turns):
            emit({"type": "thinking", "turn": turn + 1, "max_turns": self.max_turns})

            # LLM 推理
            # QUEST 官方推荐参数 (react_agent.py): max_tokens=10000, temp=0.6, top_p=0.95
            # QUEST 基于 Qwen3.5, llama.cpp 会把思维链分离到 reasoning_content 字段。
            # 官方做法: content = reasoning_content + content (合并后用)。
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=10000,
                    temperature=0.6,
                    top_p=0.95,
                    presence_penalty=1.1,
                )
                msg = resp.choices[0].message
                content = msg.content or ""
                reasoning = getattr(msg, "reasoning_content", None) or ""
                # 合并: 推理内容 + 实际输出 (官方做法)
                # _parse_tool_call 和 _extract_report 会从中提取有用部分
                reply = content if content.strip() else reasoning
                if not reply.strip():
                    reply = reasoning + content  # 都有就拼一起
            except Exception as e:
                emit({"type": "error", "message": f"LLM error: {e}"})
                return f"# Research Failed\n\nLLM error: {e}"

            messages.append({"role": "assistant", "content": reply})

            # 解析 tool_call
            tool_call = self._parse_tool_call(reply)
            if not tool_call:
                # 没工具调用 = 可能是最终报告
                report = self._extract_report(reply)
                # 报告够长, 或者看起来像报告(有标题) → 接受
                if report and (len(report) >= 150 or report.startswith("#")):
                    report = self._verify_report(report, context, emit)
                    context.add_version(report)
                    emit({"type": "report", "version": context.current_version,
                          "content": report, "changes": "initial" if not is_iteration else "updated"})
                    return report
                else:
                    # 提取失败 (太短/纯思维链) → fallback 兜底
                    report = self._build_fallback_report(question, context)
                    report = self._verify_report(report, context, emit)
                    context.add_version(report)
                    emit({"type": "report", "version": context.current_version,
                          "content": report, "changes": "initial" if not is_iteration else "updated"})
                    return report

            name, args = tool_call
            try:
                result = self._execute_tool(name, args, skip_queries, context, emit)
            except Exception as e:
                emit({"type": "error", "message": f"Tool {name} error: {e}"})
                result = f"[Tool {name} error: {e}]"

            # 回填工具结果
            messages.append({"role": "user",
                             "content": f"<tool_response>\n{result[:8000]}\n</tool_response>"})

        # 超过最大轮数, 强制总结
        emit({"type": "thinking", "turn": self.max_turns, "max_turns": self.max_turns,
              "forced": True})

        # 强制总结: 用精简上下文 (不传完整对话历史, 只传已收集的知识)
        # 避免 QUEST-9B 因上下文过大而返回空
        summary_prompt = self._build_summary_prompt(question, context, is_iteration)
        summary_messages = [
            {"role": "system", "content": "You are a research assistant. Based on the gathered information below, write a comprehensive research report in markdown with citations. Write the report directly, do not call any tools."},
            {"role": "user", "content": summary_prompt},
        ]
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=summary_messages,
                max_tokens=10000, temperature=0.6, top_p=0.95,
                presence_penalty=1.1,
            )
            msg = resp.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning_content", None) or ""
            raw = content if content.strip() else (reasoning + content)
            report = self._extract_report(raw)
        except Exception as e:
            report = ""

        # 如果强制总结也空, 用已收集的知识拼一个基础报告
        if not report or len(report) < 50:
            report = self._build_fallback_report(question, context)

        # 幻觉验证 (强制总结的也要验证)
        report = self._verify_report(report, context, emit)
        context.add_version(report, changes="forced summary")
        emit({"type": "report", "version": context.current_version,
              "content": report, "changes": "forced"})
        return report

    def _verify_report(self, report: str, context: ResearchContext,
                       emit: Callable) -> str:
        """幻觉抵御: 抽取关键事实声明 → 搜索引擎二次验证 → 追加验证摘要。

        最多验证 8 个声明 (优先含数字/日期的)。验证结果追加到报告末尾。
        """
        emit({"type": "verify_start"})
        claims = self._extract_claims(report)

        if not claims:
            emit({"type": "verify_done", "total": 0})
            return report

        # 最多 8 个
        claims = claims[:8]
        results = []

        for claim in claims:
            emit({"type": "verify", "claim": claim[:80]})
            try:
                vr = tool_verify_claim(claim)
                results.append({"claim": claim, **vr})
                emit({"type": "verify_done", "claim": claim[:80],
                      "status": vr["status"], "evidence_count": len(vr.get("evidence", []))})
            except Exception as e:
                results.append({"claim": claim, "status": "unverified",
                                "error": str(e)})
                emit({"type": "verify_done", "claim": claim[:80],
                      "status": "unverified", "error": str(e)})

        # 验证 URL 引用可达性
        url_claims = re.findall(r"\[source: (.+?)\]|🔗 (.+?)(?:\s|$)", report)
        for url_group in url_claims[:5]:
            url = url_group[0] or url_group[1]
            if url.startswith("http"):
                url_check = tool_verify_url(url)
                if not url_check.get("reachable"):
                    results.append({"claim": f"URL: {url}",
                                    "status": "unverified",
                                    "reason": "链接不可达"})

        # 构造验证摘要
        verified = sum(1 for r in results if r["status"] == "verified")
        partial = sum(1 for r in results if r["status"] == "partial")
        unverified = sum(1 for r in results if r["status"] == "unverified")

        summary_lines = [
            "\n\n---\n\n## 🔍 事实验证\n",
            f"> 自动验证了 {len(results)} 个关键声明: "
            f"✅ {verified} 已验证 / ⚠️ {partial} 部分验证 / ❌ {unverified} 未验证\n",
        ]

        for r in results:
            status_icon = {"verified": "✅", "partial": "⚠️", "unverified": "❌"}.get(
                r["status"], "❓")
            summary_lines.append(f"- {status_icon} **{r['claim'][:100]}**")
            if r.get("evidence"):
                for ev in r["evidence"][:2]:
                    summary_lines.append(f"  - [{ev.get('title','')[:50]}]({ev.get('url','')})")
            elif r.get("reason"):
                summary_lines.append(f"  - {r['reason']}")

        emit({"type": "verify_done", "total": len(results),
              "verified": verified, "partial": partial, "unverified": unverified})

        return report + "\n".join(summary_lines)

    def _extract_claims(self, report: str) -> list:
        """从报告抽取需要验证的事实声明 (含数字/日期/百分比的句子)。

        会先清理 URL/markdown链接/引用来源, 避免把链接碎片当声明。
        """
        # 预处理: 去掉 URL、markdown 链接、引用来源标记
        clean_report = report
        # 去掉 markdown 链接 [text](url) → text
        clean_report = re.sub(r"\[([^\]]*)\]\(https?://[^\)]+\)", r"\1", clean_report)
        # 去掉裸 URL
        clean_report = re.sub(r"https?://\S+", "", clean_report)
        # 去掉 (来源：xxx) / (source: xxx) 整段
        clean_report = re.sub(r"[（(]\s*(?:来源|source)[:：].*?[)）]", "", clean_report, flags=re.IGNORECASE)
        # 去掉 [source: xxx]
        clean_report = re.sub(r"\[source:.*?\]", "", clean_report, flags=re.IGNORECASE)
        # 去掉 markdown 标记符号
        clean_report = re.sub(r"[#*`>]", "", clean_report)

        # 按句子分割
        sentences = re.split(r"[。.!！?？\n]+", clean_report)
        claims = []
        for s in sentences:
            s = s.strip().strip("：:、，,")
            if len(s) < 20 or len(s) > 200:
                continue
            # 跳过纯 URL 碎片 / 文件扩展名 / 无意义的短串
            if re.match(r"^(com|html|www|http|https|org|net|article|\d+)$", s, re.I):
                continue
            # 必须包含实际词汇 (中文字符≥3 或 英文单词≥3)
            cn_chars = len(re.findall(r"[\u4e00-\u9fff]", s))
            en_words = len(re.findall(r"[a-zA-Z]{2,}", s))
            if cn_chars < 3 and en_words < 3:
                continue
            # 优先级: 含数字/百分比/日期/对比词
            has_number = bool(re.search(r"\d+(?:\.\d+)?\s*[%万千亿元倍]|\d+\.\d+|"
                                        r"\d{2,}", s))
            has_date = bool(re.search(r"\d{4}\s*年|\d{1,2}\s*月|"
                                      r"january|february|202[0-9]", s, re.I))
            has_compare = bool(re.search(r"\b(?:more|less|faster|slower|better|worse|"
                                          r"比|超过|低于|高于|提升|降低|上涨|下降|增长)\b", s, re.I))
            if has_number or has_date or has_compare:
                claims.append(s)
        return claims

    def _build_summary_prompt(self, question: str, context: ResearchContext,
                              is_iteration: bool) -> str:
        """构建强制总结的精简 prompt (只含知识, 不含对话历史)。"""
        parts = [f"Research Question: {question}\n"]

        if is_iteration and context.latest_report:
            parts.append(f"Previous Report:\n{context.latest_report[:3000]}\n")

        parts.append("Information Gathered:")
        for q in context.searched_queries:
            parts.append(f"- Searched: {q}")
        for url, snippet in list(context.visited_urls.items())[:8]:
            parts.append(f"- {url}:\n  {snippet[:500]}")

        parts.append("\nWrite a comprehensive report answering the question. "
                      "Use markdown with headers and [source: URL] citations.")
        return "\n".join(parts)

    def _build_fallback_report(self, question: str, context: ResearchContext) -> str:
        """LLM 总结失败时的兜底: 用已收集的知识整理成研究笔记。

        注意: 这里展示的是"采集到的信息摘要", 不是 AI 生成的分析报告。
        会明确标注, 避免与正式报告混淆。
        """
        lines = [f"# {question}\n"]
        n_search = len(context.searched_queries)
        n_visit = len(context.visited_urls)
        lines.append(f"> ⚠️ AI 生成报告失败, 以下为采集到的原始信息摘要 "
                     f"(基于 {n_search} 次搜索, {n_visit} 个页面访问)。"
                     f"可点击「迭代」让 AI 基于这些信息生成正式报告。\n")

        if context.visited_urls:
            lines.append("## 采集到的关键信息\n")
            for i, (url, snippet) in enumerate(list(context.visited_urls.items())[:6], 1):
                # 提取前 3 句作为摘要, 不堆全文
                sentences = snippet.split("。")
                summary = "。".join(sentences[:3])
                if len(summary) < 20:
                    summary = snippet[:300]
                lines.append(f"{i}. {summary[:400]}\n")
                lines.append(f"   [source: {url}]\n")
        elif context.searched_queries:
            lines.append("## 搜索记录\n")
            lines.append("AI 进行了以下搜索但未能提取页面内容:\n")
            for q in context.searched_queries[:10]:
                lines.append(f"- {q}")
        else:
            lines.append("未能采集到有效信息,请尝试重新研究或换个问法。\n")

        return "\n".join(lines)

    def _parse_tool_call(self, text: str):
        """从 LLM 输出解析 <tool_call>{...}</tool_call>。

        QUEST 常模仿 prompt 里的 {{}} 转义格式, 这里统一还原成单花括号再解析。
        """
        matches = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
        if not matches:
            return None
        raw = matches[-1].strip()
        # QUEST 可能输出 {{}} 双花括号 (从 prompt format string 转义学到)
        # 先试直接解析; 失败才替换双花括号 (避免破坏正常 JSON 嵌套的 }})
        def _try_parse(s):
            try:
                return json.loads(s)
            except (json.JSONDecodeError, TypeError):
                return None

        call = _try_parse(raw)
        if call is None:
            # 替换双花括号后重试 (循环处理嵌套的 {{}}})
            fixed = raw
            for _ in range(10):
                fixed = fixed.replace("{{", "{").replace("}}", "}")
                call = _try_parse(fixed)
                if call is not None:
                    break
                if "{{" not in fixed and "}}" not in fixed:
                    break
        if not isinstance(call, dict):
            return None
        name = call.get("name")
        args = call.get("arguments", {})
        if not name:
            return None
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        return name, args

    def _primer_search(self, question: str, context: ResearchContext,
                       emit) -> str:
        """预热搜索: 自动用 exa + searxng 各搜一次, 注入初始上下文。

        QUEST-9B 倾向只调 search 且不稳定, 这里强制先跑两个引擎,
        让模型后续专注于 visit + twitter/小红书 (社媒讨论)。
        """
        results = []
        # Exa 语义搜索 (高质量)
        emit({"type": "search", "query": question, "engine": "exa", "auto": True})
        r = tool_exa(question, num=5)
        context.add_search(question)
        if r.get("results"):
            results.append(self._format_search_results(r))
            emit({"type": "search_done", "query": question,
                  "count": len(r["results"]), "engine": "exa", "auto": True})
        else:
            emit({"type": "search_done", "query": question, "count": 0,
                  "engine": "exa", "auto": True})
        # SearXNG 通用搜索
        emit({"type": "search", "query": question, "engine": "searxng", "auto": True})
        r2 = tool_search(question)
        context.add_search(question)
        if r2.get("results"):
            results.append(self._format_search_results(r2))
            emit({"type": "search_done", "query": question,
                  "count": len(r2["results"]), "engine": "searxng", "auto": True})
        else:
            emit({"type": "search_done", "query": question, "count": 0,
                  "engine": "searxng", "auto": True})

        # 社媒讨论: 问题含社区/评价/体验等关键词时, 自动追加 twitter + 小红书
        social_kws = ["讨论", "评价", "体验", "怎么看", "大家", "觉得", "观点",
                      "opinion", "review", "discuss", "community", "think",
                      "社区", "用户", "真实", "口碑", "测评", "推荐"]
        is_social = any(kw in question.lower() for kw in social_kws)
        if is_social:
            # Twitter (英文社媒讨论)
            tw_q = question[:80]
            emit({"type": "search", "query": tw_q, "engine": "twitter", "auto": True})
            r3 = tool_twitter(tw_q, num=10)
            context.add_search(f"twitter:{tw_q}")
            if r3.get("results"):
                results.append("## Twitter/X Discussions\n" + self._format_search_results(r3))
                emit({"type": "search_done", "query": tw_q,
                      "count": len(r3["results"]), "engine": "twitter", "auto": True})
            else:
                emit({"type": "search_done", "query": tw_q, "count": 0,
                      "engine": "twitter", "auto": True,
                      "error": r3.get("error", "")})
            # 小红书 (中文生活消费)
            emit({"type": "search", "query": tw_q, "engine": "xiaohongshu", "auto": True})
            r4 = tool_xhs(tw_q)
            context.add_search(f"xhs:{tw_q}")
            if r4.get("results"):
                results.append("## 小红书笔记\n" + self._format_search_results(r4))
                emit({"type": "search_done", "query": tw_q,
                      "count": len(r4["results"]), "engine": "xiaohongshu", "auto": True})
            else:
                emit({"type": "search_done", "query": tw_q, "count": 0,
                      "engine": "xiaohongshu", "auto": True,
                      "error": r4.get("error", "")})

        return "\n\n".join(results) if results else ""

    def _execute_tool(self, name: str, args, skip_queries, context, emit) -> str:
        """执行工具, 推送事件, 累积 context。"""
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}

        if name == "search":
            queries = args.get("query", [])
            if isinstance(queries, str):
                queries = [queries]
            all_results = []
            for q in queries:
                emit({"type": "search", "query": q})
                r = tool_search(q, skip_queries=skip_queries)
                context.add_search(q)
                if r.get("results"):
                    formatted = self._format_search_results(r)
                    all_results.append(formatted)
                    emit({"type": "search_done", "query": q,
                          "count": len(r["results"])})
                else:
                    emit({"type": "search_done", "query": q, "count": 0})
            return "\n\n".join(all_results) if all_results else "[No results]"

        elif name == "visit":
            urls = args.get("url", [])
            if isinstance(urls, str):
                urls = [urls]
            goal = args.get("goal", "")
            all_content = []
            for u in urls[:5]:
                emit({"type": "visit", "url": u, "goal": goal})
                r = tool_visit(u, goal)
                if r.get("content"):
                    context.add_visit(u, r["content"])
                    all_content.append(f"## {u}\n{r['content'][:4000]}")
                    emit({"type": "visit_done", "url": u,
                          "length": len(r["content"])})
                else:
                    emit({"type": "visit_done", "url": u, "error": r.get("error", "failed")})
            return "\n\n---\n\n".join(all_content) if all_content else "[No content]"

        elif name == "exa":
            # Exa 语义搜索 (擅长英文/技术/代码, 高质量)
            queries = args.get("query", [])
            if isinstance(queries, str):
                queries = [queries]
            all_results = []
            for q in queries[:3]:
                emit({"type": "search", "query": q, "engine": "exa"})
                r = tool_exa(q, num=5)
                context.add_search(q)
                if r.get("results"):
                    all_results.append(self._format_search_results(r))
                    emit({"type": "search_done", "query": q,
                          "count": len(r["results"]), "engine": "exa"})
                else:
                    emit({"type": "search_done", "query": q, "count": 0,
                          "engine": "exa", "error": r.get("error", "")})
            return "\n\n".join(all_results) if all_results else "[Exa: no results]"

        elif name == "twitter":
            # Twitter/X 搜索 (社交媒体讨论/观点)
            queries = args.get("query", [])
            if isinstance(queries, str):
                queries = [queries]
            all_results = []
            for q in queries[:2]:
                emit({"type": "search", "query": q, "engine": "twitter"})
                r = tool_twitter(q, num=10)
                context.add_search(f"twitter:{q}")
                if r.get("results"):
                    all_results.append(self._format_search_results(r))
                    emit({"type": "search_done", "query": q,
                          "count": len(r["results"]), "engine": "twitter"})
                else:
                    emit({"type": "search_done", "query": q, "count": 0,
                          "engine": "twitter", "error": r.get("error", "")})
            return "\n\n".join(all_results) if all_results else "[Twitter: no results or not authenticated]"

        elif name == "xiaohongshu":
            # 小红书搜索 (中文生活消费/真实体验)
            queries = args.get("query", [])
            if isinstance(queries, str):
                queries = [queries]
            all_results = []
            for q in queries[:2]:
                emit({"type": "search", "query": q, "engine": "xiaohongshu"})
                r = tool_xhs(q)
                context.add_search(f"xhs:{q}")
                if r.get("results"):
                    all_results.append(self._format_search_results(r))
                    emit({"type": "search_done", "query": q,
                          "count": len(r["results"]), "engine": "xiaohongshu"})
                else:
                    emit({"type": "search_done", "query": q, "count": 0,
                          "engine": "xiaohongshu", "error": r.get("error", "")})
            return "\n\n".join(all_results) if all_results else "[小红书: no results or not logged in]"

        return f"[Unknown tool: {name}]"

    def _format_search_results(self, r: dict) -> str:
        lines = [f"## Search Results: {r['query']}"]
        for i, item in enumerate(r["results"], 1):
            lines.append(f"{i}. {item['title']}\n   {item['url']}\n   {item['snippet']}")
        return "\n".join(lines)

    def _extract_report(self, text: str) -> str:
        """从 LLM 输出提取干净的研究报告。

        清理顺序:
        1. tool_call/think/tool_response 标记
        2. </note> 等 XML 残留
        3. 搜索结果块、JSON 片段
        4. 找第一个 markdown 标题作为报告起点
        5. 去重 (QUEST 可能中英文各输出一遍)
        """
        # 1. 各种标记块
        for tag in ["tool_call", "think", "tool_response", "note"]:
            text = re.sub(r"<%s>.*?</%s>" % (tag, tag), "", text, flags=re.DOTALL)
            text = re.sub(r"<%s>.*" % tag, "", text, flags=re.DOTALL)
            text = re.sub(r"</%s>" % tag, "", text)
        # 2. 搜索结果块
        text = re.sub(r"^##\s*Search Results?:.*?(?=^##\s|\Z)", "", text,
                      flags=re.DOTALL | re.MULTILINE)
        # 3. 伪 tool 标记 + 裸 JSON
        text = re.sub(r"\[(?:visit|search|memory)\][^\n]*\n(?:[^\n]*\n){0,5}", "", text)
        text = re.sub(r'^\s*\{["\']name["\'].*?\}.*$', "", text, flags=re.MULTILINE)
        # 4. 找第一个 markdown 标题作为报告起点
        m = re.search(r"^#{1,3}\s+.+", text, re.MULTILINE)
        if m:
            text = text[m.start():]
        # 5. 去重: QUEST 可能中英文各输出一遍报告
        # 找所有 ## 或 # 开头的顶级标题位置, 如果报告明显重复 (>2个相同标题), 截到第一次重复处
        headings = re.findall(r"^(#{1,2}\s+.+)$", text, re.MULTILINE)
        if len(headings) >= 4:
            # 检测重复: 如果前半段和后半段标题高度相似, 截取前半段
            mid = len(text) // 2
            first_half_headings = [h for h in headings if text.find(h) < mid]
            second_half_headings = [h for h in headings if text.find(h) >= mid]
            if len(first_half_headings) >= 2 and len(second_half_headings) >= 2:
                # 简单检测: 如果第二个 ## 标题的内容和第一个类似, 截断
                first_h1 = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
                if first_h1:
                    h1_text = first_h1.group(1).strip()
                    # 找 h1_text 在后面的重复
                    later = text[first_h1.end():]
                    if h1_text in later or later.find("Research Report") >= 0:
                        # 截到第一次重复的标题前
                        dup_pos = later.find("Research Report")
                        if dup_pos >= 0:
                            text = text[:first_h1.end() + dup_pos].rstrip()
        # 6. 清理多余空行
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text
