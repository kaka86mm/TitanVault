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
    verify_claim as tool_verify_claim, verify_url as tool_verify_url

# ============================================================================
# Prompts
# ============================================================================

INITIAL_PROMPT = """You are QUEST, a deep research agent. Your goal is to answer the user's question thoroughly using web search and page reading.

## Available Tools
- search: Search the web. Input: {"name": "search", "arguments": {"query": ["query1", "query2"]}}
- visit: Read webpage content. Input: {"name": "visit", "arguments": {"url": ["url1"], "goal": "what you need"}}

## Process
1. Break down the question into sub-questions
2. Search for information on each sub-question
3. Visit relevant pages to read details
4. Cross-reference and verify findings
5. Synthesize a comprehensive answer with citations

## Output Format
When you have gathered enough information, write your final report in markdown:
- Start with a direct answer summary
- Include detailed findings with [source: URL] citations
- Note any conflicting information or gaps

To call a tool, output:
<tool_call>
{"name": "search", "arguments": {"query": ["your query"]}}
</tool_call>

After receiving tool results, continue researching or write your final report.
When you have enough info, STOP calling tools and write the report directly."""

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
            system = INITIAL_PROMPT
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

        for turn in range(self.max_turns):
            emit({"type": "thinking", "turn": turn + 1, "max_turns": self.max_turns})

            # LLM 推理
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=8192,
                    temperature=0.7,
                )
                reply = resp.choices[0].message.content or ""
            except Exception as e:
                emit({"type": "error", "message": f"LLM error: {e}"})
                return f"# Research Failed\n\nLLM error: {e}"

            messages.append({"role": "assistant", "content": reply})

            # 解析 tool_call
            tool_call = self._parse_tool_call(reply)
            if not tool_call:
                # 没工具调用 = 最终报告
                report = self._extract_report(reply)
                if not report or len(report) < 20:
                    report = self._build_fallback_report(question, context)
                # 幻觉验证
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
                max_tokens=4096, temperature=0.7,
            )
            report = self._extract_report(resp.choices[0].message.content or "")
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
        """从报告抽取需要验证的事实声明 (含数字/日期/百分比的句子)。"""
        # 按句子分割
        sentences = re.split(r"[。.!！?？\n]+", report)
        claims = []
        for s in sentences:
            s = s.strip()
            if len(s) < 15 or len(s) > 200:
                continue
            # 优先级: 含数字/百分比/日期/对比词
            has_number = bool(re.search(r"\d+(?:\.\d+)?%?|¥|$", s))
            has_date = bool(re.search(r"\d{4}\s*年|\d{1,2}\s*月|january|february|202[0-9]", s, re.I))
            has_compare = bool(re.search(r"\b(?:more|less|faster|slower|better|worse|"
                                          r"比|超过|低于|高于|提升|降低)\b", s, re.I))
            if has_number or has_date or has_compare:
                # 去掉 markdown 标记
                clean = re.sub(r"[#*`\[\]()]|source:.*", "", s).strip()
                if clean and len(clean) > 15:
                    claims.append(clean)
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
        """LLM 总结失败时的兜底: 用已收集的知识拼报告。"""
        lines = [f"# Research: {question}\n"]
        lines.append(f"> 自动生成 (基于 {len(context.searched_queries)} 次搜索, "
                      f"{len(context.visited_urls)} 个页面)\n")

        if context.visited_urls:
            lines.append("## Key Findings\n")
            for url, snippet in list(context.visited_urls.items())[:8]:
                lines.append(f"### {url}\n")
                lines.append(f"{snippet[:800]}\n")
                lines.append(f"[source: {url}]\n")
        else:
            lines.append("## Search Results\n")
            lines.append("The research agent searched but could not extract "
                          "detailed page content. Key search queries:\n")
            for q in context.searched_queries:
                lines.append(f"- {q}")

        return "\n".join(lines)

    def _parse_tool_call(self, text: str):
        """从 LLM 输出解析 <tool_call>{...}</tool_call>。"""
        matches = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
        if not matches:
            return None
        try:
            call = json.loads(matches[-1].strip())
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
        except (json.JSONDecodeError, AttributeError, TypeError):
            return None

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

        return f"[Unknown tool: {name}]"

    def _format_search_results(self, r: dict) -> str:
        lines = [f"## Search Results: {r['query']}"]
        for i, item in enumerate(r["results"], 1):
            lines.append(f"{i}. {item['title']}\n   {item['url']}\n   {item['snippet']}")
        return "\n".join(lines)

    def _extract_report(self, text: str) -> str:
        """去掉残留 tool_call 标记和非内容行, 返回干净报告。"""
        # 去掉闭合的 <tool_call>...</tool_call>
        text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL)
        # 去掉未闭合的 <tool_call> (到行尾或文件尾)
        text = re.sub(r"<tool_call>.*", "", text, flags=re.DOTALL)
        # 去掉 [visit] / [search] 等伪 tool 标记块
        text = re.sub(r"\[(?:visit|search|memory)\][^\n]*\n(?:[^\n]*\n){0,5}", "", text)
        # 去掉 <think> 块
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # 去掉残留的 thinking 开头
        text = re.sub(r"^<think>.*$", "", text, flags=re.MULTILINE)
        # 找到第一个 markdown 标题 (#) 作为报告起点
        m = re.search(r"^(#{1,3}\s+.+)$", text, re.MULTILINE)
        if m:
            text = text[m.start():]
        # 清理多余空行
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text
