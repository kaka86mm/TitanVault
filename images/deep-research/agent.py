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

from tools import search as tool_search, visit as tool_visit

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
- search: {"name": "search", "arguments": {"query": ["query"]}}
- visit: {"name": "visit", "arguments": {"url": ["url"], "goal": "..."}}

To call a tool:
<tool_call>
{"name": "search", "arguments": {"query": ["new query"]}}
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
        max_turns: int = 5,
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
                    max_tokens=4096,
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
                context.add_version(report)
                emit({"type": "report", "version": context.current_version,
                      "content": report, "changes": "initial" if not is_iteration else "updated"})
                return report

            name, args = tool_call
            result = self._execute_tool(name, args, skip_queries, context, emit)

            # 回填工具结果
            messages.append({"role": "user",
                             "content": f"<tool_response>\n{result[:8000]}\n</tool_response>"})

        # 超过最大轮数, 强制总结
        emit({"type": "thinking", "turn": self.max_turns, "max_turns": self.max_turns,
              "forced": True})
        messages.append({"role": "user",
                         "content": "You have done enough research. Write your final report now."})
        try:
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=4096, temperature=0.7,
            )
            report = self._extract_report(resp.choices[0].message.content or "")
        except Exception as e:
            report = f"# Research Incomplete\n\nReached max turns. Last error: {e}"

        context.add_version(report, changes="forced summary")
        emit({"type": "report", "version": context.current_version,
              "content": report, "changes": "forced"})
        return report

    def _parse_tool_call(self, text: str):
        """从 LLM 输出解析 <tool_call>{...}</tool_call>。"""
        matches = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
        if not matches:
            return None
        try:
            call = json.loads(matches[-1].strip())
            return call.get("name"), call.get("arguments", {})
        except json.JSONDecodeError:
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
        """去掉残留 tool_call 标记, 返回干净报告。"""
        text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL).strip()
        return text
