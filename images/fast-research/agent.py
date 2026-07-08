"""
agent.py — Fast Research Agent (ReAct 循环 + 报告迭代)

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
    xiaohongshu_search as tool_xhs, wechat_search as tool_wechat, \
    verify_url as tool_verify_url

# ============================================================================
# Prompts
# ============================================================================

INITIAL_PROMPT = """You are an expert research agent. Today's date: {today}.
Your goal: thoroughly research the user's question using web tools, then write a comprehensive, well-structured research report.

## Tools (output <tool_call> to use one)
- exa: Semantic search (high quality). <tool_call>{{"name":"exa","arguments":{{"query":["your query"]}}}}}}</tool_call>
- search: Web search (google/bing). Same format, name="search".
- twitter: Twitter/X discussions. name="twitter".
- xiaohongshu: 小红书 reviews. name="xiaohongshu".
- wechat: 微信公众号 articles. name="wechat".
- visit: Read a URL in detail. {{"name":"visit","arguments":{{"url":["URL"],"goal":"..."}}}}

## Research Process
1. MUST call tools. Do NOT answer from memory or general knowledge.
2. Break the question into 3-5 sub-questions. Search each separately with DIFFERENT queries.
3. Search at least 5 times. Always include queries with current date for latest data.
4. VISIT 5+ pages to read full content — search snippets are not enough.
5. For Chinese topics: use search + wechat + xiaohongshu. For discussions: use twitter.
6. Collect facts, numbers, statistics, quotes from visited pages.

## Anti-Hallucination Rules
- NEVER fabricate numbers, prices, dates, or statistics.
- Only use data that appears in the text of pages you VISITED.
- If you don't have data for something, omit it — do NOT guess or estimate.
- Do NOT put specific numbers in search queries. Search by topic, not by guessed figures.

## Report Guidelines (when you have gathered enough information, write the report)
Write a detailed, well-structured report using ALL gathered information. Follow these rules:

1. **MUST determine your own concrete, valid conclusions** based on the gathered information. Do NOT defer to general, meaningless conclusions.
2. Write in **markdown** with clear headers: `#` for title, `##` for major sections, `###` for subsections.
3. Use **markdown tables** when presenting structured data or comparisons.
4. **Prioritize relevance, reliability, and significance** of sources. Prefer newer articles over older ones.
5. Include **in-text citations** as markdown hyperlinks at the end of the relevant sentence:
   `Token usage grew 70% in June ([JPMorgan report](https://...)).`
6. Add a **References** section at the END with ALL source URLs (deduplicated):
   ```
   ## References
   1. [Source Name](url1)
   2. [Source Name](url2)
   ```
7. Write in the SAME language as the user's question. Do NOT mix languages.
8. Do NOT include a table of contents.
9. Aim for **2000+ words** if enough data is available.
10. Every key claim, number, or statistic MUST have a citation URL.

This is very important to my career. Assume the current date is {today}.

When you have enough info, STOP calling tools and write the complete report."""


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
- search: {{"name": "search", "arguments": {{"query": ["query"]}}}} (web search — do NOT use site: operator)
- exa: {{"name": "exa", "arguments": {{"query": ["query"]}}}} (semantic search, English/technical)
- twitter: {{"name": "twitter", "arguments": {{"query": ["query"]}}}} (social discussions/opinions — USE THIS for social media, NOT site:weibo.com)
- xiaohongshu: {{"name": "xiaohongshu", "arguments": {{"query": ["query"]}}}} (中文生活消费/真实评价)
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
        self.visited_urls[url] = snippet[:3000]

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

        # ── 预热搜索: 自动用 exa + searxng + 社媒各搜一次, 注入初始上下文 ──
        # 首次研究和迭代都执行 (迭代时用户可能要求新的信息源)
        primer = self._primer_search(question, context, emit)
        if primer:
            primer_msg = (f"<tool_response>\n{primer}\n</tool_response>\n\n"
                          f"These are initial results. "
                          f"Now break down the question into sub-questions and search each. "
                          f"Visit key pages for details. Do NOT write the report yet.\n\n"
                          f"IMPORTANT: For social media discussions/opinions, use the twitter/xiaohongshu tools. "
                          f"Do NOT search 'site:weibo.com' or 'site:xueqiu.com' with the search tool — "
                          f"use twitter for discussions and xiaohongshu for user reviews instead.")
            messages.append({"role": "user", "content": primer_msg})

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
                report_body = re.split(r"##\s*📎\s*来源验证", report)[0].strip()
                # 严格的报告验收标准
                n_sections = len(re.findall(r'^##\s+', report_body, re.MULTILINE))
                # 垃圾内容检测: JS代码/HTML标签/网页噪音/重复内容
                bare_urls_count = len(re.findall(r'https?://', report_body))
                has_junk = bool(
                    "</string>" in report_body
                    or "console.error" in report_body
                    or "catch (error)" in report_body
                    or report_body.count("相关网址") > 3
                    or bare_urls_count > 30  # URL列表不是报告
                    or "<|start|>" in report_body
                    or "<tool_call>" in report_body
                    or "functions." in report_body[:100]
                )
                # 检测高度重复 (同一个100字符块出现3+次 = 网页噪音/循环输出)
                if not has_junk and len(report_body) > 500:
                    chunks = [report_body[i:i+100] for i in range(0, len(report_body)-100, 50)]
                    from collections import Counter
                    most_common_count = Counter(chunks).most_common(1)[0][1] if chunks else 0
                    if most_common_count >= 3:
                        has_junk = True
                is_real_report = (
                    report_body.startswith("#")
                    and n_sections >= 3
                    and len(report_body) >= 1000
                    and not has_junk
                    and not report_body.rstrip().endswith("---")
                    and not report_body.rstrip().endswith("> 数据")
                )
                if is_real_report:
                    report = self._verify_report(report, context, emit)
                    context.add_version(report)
                    emit({"type": "report", "version": context.current_version,
                          "content": report, "changes": "initial" if not is_iteration else "updated"})
                    return report
                # 报告太短/空: 如果已有搜索数据, break 去走强制总结 (不走 fallback)
                if context.visited_urls or len(context.searched_queries) >= 3:
                    break
                # 没有足够数据 → fallback 兜底
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
            {"role": "system", "content":
             "You are an expert research analyst. Based on the gathered information below, "
             "write a detailed, well-structured research report answering the user's question. "
             "Follow these rules:\n"
             "1. Write in markdown with clear headers (# title, ## sections, ### subsections).\n"
             "2. Use markdown tables for structured data.\n"
             "3. Include in-text citations as hyperlinks: ([Source Name](url)).\n"
             "4. Add a References section at the end with all source URLs.\n"
             "5. MUST determine concrete conclusions — no generic platitudes.\n"
             "6. Every number/statistic MUST come from the gathered info with a citation.\n"
             "7. Write in the SAME language as the question.\n"
             "8. Aim for 2000+ words. This is very important to my career.\n"
             "Write the report directly, do not call any tools."},
            {"role": "user", "content": summary_prompt},
        ]
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=summary_messages,
                max_tokens=10000, temperature=0.6, top_p=0.95,
                presence_penalty=1.1,
                # 强制总结是最后兜底: 关掉 thinking 确保 content 有输出
                # (thinking 会把 max_tokens 花在 reasoning 上, 导致 content 空)
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
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
        """引用完整性验证 (参考 gpt-researcher 的可信度策略)。

        不再做"重新搜索验证数字"(不可靠且产生误报),而是:
        1. 检查报告中的引用 URL 数量和可达性
        2. 检查含数字的句子是否有对应引用
        3. 追加来源可信度摘要
        """
        emit({"type": "verify_start"})

        # 1. 提取报告中所有引用 URL (markdown 链接 + 裸 URL)
        md_urls = re.findall(r'\[[^\]]*\]\((https?://[^\)]+)\)', report)
        bare_urls = re.findall(r'(?<![\(\"])(https?://[^\s\)\]\}]+)', report)
        all_urls = list(dict.fromkeys(md_urls + bare_urls))  # 合并去重保序

        # 2. 检查引用 URL 可达性 (最多检查 5 个)
        reachable = 0
        unreachable_urls = []
        for url in all_urls[:5]:
            emit({"type": "verify", "claim": url[:60]})
            try:
                check = tool_verify_url(url)
                if check.get("reachable"):
                    reachable += 1
                    emit({"type": "verify_done", "claim": url[:60],
                          "status": "verified"})
                else:
                    unreachable_urls.append(url)
                    emit({"type": "verify_done", "claim": url[:60],
                          "status": "unverified"})
            except Exception:
                emit({"type": "verify_done", "claim": url[:60],
                      "status": "unverified"})

        # 3. 统计含数字句子中有引用的比例 (markdown链接 或 裸URL)
        sentences_with_numbers = re.findall(r'[^\n.。!！?？]*\d+[^\n.。!！?？]*', report)
        cited_sentences = [s for s in sentences_with_numbers
                          if re.search(r'\]\(https?://', s) or re.search(r'https?://', s)]
        citation_rate = len(cited_sentences) / max(len(sentences_with_numbers), 1)

        # 4. 构造来源摘要 (不评判"可信度", 只客观列出来源信息)
        total_cited = len(all_urls)
        checked = min(len(all_urls), 5)
        if total_cited == 0:
            source_note = "报告未包含来源链接"
        elif total_cited >= 8:
            source_note = f"✅ 丰富来源 ({total_cited} 个引用, {reachable}/{checked} 可达)"
        elif total_cited >= 3:
            source_note = f"📚 {total_cited} 个来源, {reachable}/{checked} 可达"
        else:
            source_note = f"📎 {total_cited} 个来源, {reachable}/{checked} 可达"

        summary_lines = [
            "\n\n---\n\n## 📎 来源\n",
            f"> {source_note}\n",
        ]

        if all_urls:
            summary_lines.append("**引用来源:**")
            for i, url in enumerate(all_urls[:15], 1):
                domain = re.search(r'https?://([^/]+)', url)
                domain_name = domain.group(1) if domain else url[:30]
                summary_lines.append(f"{i}. [{domain_name}]({url})")
        else:
            summary_lines.append("⚠️ 本报告未包含来源链接。")

        if unreachable_urls:
            summary_lines.append(f"\n**不可达链接 ({len(unreachable_urls)}):**")
            for url in unreachable_urls[:3]:
                summary_lines.append(f"- {url[:80]}")

        emit({"type": "verify_done", "total": total_cited,
              "verified": reachable, "trust": trust_level})

        return report + "\n".join(summary_lines)

    def _build_summary_prompt(self, question: str, context: ResearchContext,
                              is_iteration: bool) -> str:
        """构建强制总结的精简 prompt (只含知识, 不含对话历史)。"""
        parts = [f"Research Question: {question}\n"]

        if is_iteration and context.latest_report:
            parts.append(f"Previous Report:\n{context.latest_report[:3000]}\n")

        parts.append("Information Gathered from web research:")
        parts.append(f"(Based on {len(context.searched_queries)} searches, "
                      f"{len(context.visited_urls)} pages visited)\n")
        for q in context.searched_queries:
            parts.append(f"- Searched: {q}")
        parts.append("")
        for url, snippet in list(context.visited_urls.items())[:8]:
            parts.append(f"### Source: {url}")
            parts.append(f"{snippet[:1500]}\n")

        parts.append(f"\nUsing the above information, answer: \"{question}\" "
                      f"in a detailed report with in-text citations and a References section.")
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
        QUEST 关掉 thinking 后可能输出 <|start|>functions.xxx<|message|> 格式。
        """
        # 格式1: <tool_call>{...}</tool_call>
        matches = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
        # 格式2: <|start|>functions.xxx<|message|>{...} (Qwen jinja 格式)
        if not matches:
            matches2 = re.findall(r"<\|start\|>functions\.\w+<\|message\|>\s*(.*?)\s*(?:<\|end\|>|$)", text, re.DOTALL)
            matches = matches2
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
        # 微信公众号搜索 (中文问题默认纳入, 补充深度行业分析)
        if any('\u4e00' <= c <= '\u9fff' for c in question):
            emit({"type": "search", "query": question[:60], "engine": "wechat", "auto": True})
            r_wx = tool_wechat(question[:60])
            context.add_search(f"wechat:{question[:60]}")
            if r_wx.get("results"):
                results.append("## 微信公众号文章\n" + self._format_search_results(r_wx))
                emit({"type": "search_done", "query": question[:60],
                      "count": len(r_wx["results"]), "engine": "wechat", "auto": True})
            else:
                emit({"type": "search_done", "query": question[:60], "count": 0,
                      "engine": "wechat", "auto": True})
        # 最新动态搜索: 加 "最新/latest/2026" 关键词, 确保覆盖到当前月份
        today = datetime.now()
        recent_q = f"{question[:40]} 最新 {today.year}年{today.month}月"
        emit({"type": "search", "query": recent_q, "engine": "searxng", "auto": True})
        r3 = tool_search(recent_q)
        context.add_search(recent_q)
        if r3.get("results"):
            results.append(self._format_search_results(r3))
            emit({"type": "search_done", "query": recent_q,
                  "count": len(r3["results"]), "engine": "searxng", "auto": True})
        else:
            emit({"type": "search_done", "query": recent_q, "count": 0,
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
            # 微信公众号 (中文深度分析/行业观点)
            emit({"type": "search", "query": tw_q, "engine": "wechat", "auto": True})
            r5 = tool_wechat(tw_q)
            context.add_search(f"wechat:{tw_q}")
            if r5.get("results"):
                results.append("## 微信公众号文章\n" + self._format_search_results(r5))
                emit({"type": "search_done", "query": tw_q,
                      "count": len(r5["results"]), "engine": "wechat", "auto": True})
            else:
                emit({"type": "search_done", "query": tw_q, "count": 0,
                      "engine": "wechat", "auto": True,
                      "error": r5.get("error", "")})

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

        elif name == "wechat":
            # 微信公众号文章搜索 (中文深度分析/行业观点)
            queries = args.get("query", [])
            if isinstance(queries, str):
                queries = [queries]
            all_results = []
            for q in queries[:2]:
                emit({"type": "search", "query": q, "engine": "wechat"})
                r = tool_wechat(q)
                context.add_search(f"wechat:{q}")
                if r.get("results"):
                    all_results.append(self._format_search_results(r))
                    emit({"type": "search_done", "query": q,
                          "count": len(r["results"]), "engine": "wechat"})
                else:
                    emit({"type": "search_done", "query": q, "count": 0,
                          "engine": "wechat", "error": r.get("error", "")})
            return "\n\n".join(all_results) if all_results else "[微信: no results]"

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
        # 1. 各种标记块 (保留 References/引用内容)
        for tag in ["tool_call", "think", "tool_response"]:
            text = re.sub(r"<%s>.*?</%s>" % (tag, tag), "", text, flags=re.DOTALL)
            text = re.sub(r"<%s>.*" % tag, "", text, flags=re.DOTALL)
        # 清理 Qwen jinja 格式残留: <|start|>functions.xxx<|message|>...<|end|>
        text = re.sub(r"<\|start\|>functions\.\w+<\|message\|>.*?(?:<\|end\|>|$)", "", text, flags=re.DOTALL)
        text = re.sub(r"<\|start\|>.*?<\|message\|>", "", text, flags=re.DOTALL)
        text = re.sub(r"<\|end\|>", "", text)
        text = re.sub(r"<\|im_start\|>.*?<\|im_end\|>", "", text, flags=re.DOTALL)
        # note/related_urls 只去标签本身, 保留内容 (可能含引用链接)
        for tag in ["note", "related_urls"]:
            text = re.sub(r"</?%s>" % tag, "", text)
        # 清理网页代码泄露: JS代码块、</string>标签、HTML script
        text = re.sub(r"</?string>", "", text)
        text = re.sub(r"\bconsole\.\w+\(.*?\);?", "", text)
        text = re.sub(r"\} catch \(error\) \{[^}]*\}", "", text, flags=re.DOTALL)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # 去掉高度重复的"相关网址"段落 (网页噪音)
        text = re.sub(r"(相关网址\n(?:(?:https?://\S+\n?){2,}|\S+\n)){2,}", "相关网址\n（见引用列表）\n", text)
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
