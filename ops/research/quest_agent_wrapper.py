"""
quest_agent_wrapper.py — 精简 ReAct agent 循环

不依赖 QUEST 完整的 react_agent.py (它需要 torch/vllm 等重依赖)。
自己实现 ReAct 循环: LLM 生成 → 解析 tool_call → 执行工具 → 回填 → 循环。

工具通过 qwen_agent 的 register_tool 机制注册, 接口兼容 QUEST 原生工具。
"""
import os
import re
import json
import time
from typing import List, Dict, Optional

from openai import OpenAI
from qwen_agent.tools.base import BaseTool

TO = chr(60) + "tool_call" + chr(62)
TC = chr(60) + "/tool_call" + chr(62)

# QUEST 的 system prompt (从 QUEST prompt.py 提炼的精简版)
SYSTEM_PROMPT = """You are QUEST, a deep research agent. Your goal is to answer the user's question thoroughly using web search and page reading.

## Available Tools
- search: Search the web. Input: {"query": ["query1", "query2"]} (array of queries)
- visit: Read webpage content. Input: {"url": ["url1", "url2"], "goal": "what you're looking for"}
- make_chart: Generate a chart from data. Input: {"title": "...", "chart_type": "Bar Chart", "x_field": "...", "y_field": "...", "data": [{"...": 0}]}
  Use for comparisons, trends, rankings. chart_type: Bar Chart / Line Chart / Pie Chart / Scatter Plot.
  Only use REAL data from pages you visited.

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
- Use markdown tables for structured comparisons
- Note any conflicting information or gaps
- End with a confidence assessment

To call a tool, output:
""" + TO + """
{"name": "tool_name", "arguments": {...}}
""" + TC + """

After receiving tool results, continue researching or write your final report.
Do NOT call tools forever — when you have enough info, STOP calling tools and write the report."""


class QuestAgent:
    """精简 ReAct agent: 调用 OpenAI 兼容端点 + 执行工具循环。"""

    def __init__(
        self,
        function_list: List[str],
        llm: Dict,
        endpoint: str,
        api_key: str = "EMPTY",
        max_turns: int = 30,
    ):
        self.client = OpenAI(api_key=api_key, base_url=endpoint)
        self.model_name = "QUEST-9B"
        self.max_turns = max_turns
        self.tools: Dict[str, BaseTool] = {}
        for name in function_list:
            tool_cls = self._get_tool_class(name)
            if tool_cls:
                self.tools[name] = tool_cls()

    def _get_tool_class(self, name: str):
        """从 qwen_agent 工具注册表获取工具类。"""
        from qwen_agent.tools.base import TOOL_REGISTRY
        tool_cls = TOOL_REGISTRY.get(name)
        if tool_cls and isinstance(tool_cls, type):
            return tool_cls
        if name == "memory":
            return MemoryTool
        return None

    def _call_llm(self, messages: List[Dict]) -> str:
        """调用 LLM, 返回文本。

        QUEST 是推理模型: 思维链分离到 reasoning_content, 实际输出在 content。
        合并两者: 优先 content, 空则用 reasoning_content。
        上下文保护: 估算总 token, 超过 25000 则裁掉中间的 tool 结果。
        """
        # 上下文保护: 估算总字符数, 超过 80000 (~25K tokens) 则裁中间消息
        total_chars = sum(len(m.get("content", "")) for m in messages)
        if total_chars > 80000:
            # 保留 system + user(原始问题) + 最后 4 条, 中间的 tool 结果截断
            if len(messages) > 6:
                for m in messages[2:-4]:
                    c = m.get("content", "")
                    if len(c) > 500:
                        m["content"] = c[:200] + "\n...[truncated]...\n" + c[-200:]
            total_chars = sum(len(m.get("content", "")) for m in messages)
            print(f"  [context trimmed to ~{total_chars//4} tokens]", flush=True)

        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=10000,
                temperature=0.6,
                top_p=0.95,
                presence_penalty=1.1,
            )
            msg = resp.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning_content", None) or ""
            reply = content if content.strip() else reasoning
            if not reply.strip():
                reply = reasoning + content
            return reply
        except Exception as e:
            return f"[LLM Error: {e}]"

    def _parse_tool_call(self, text: str):
        """从 LLM 输出解析 tool_call。返回 (name, args) 或 None。

        处理 QUEST 特有问题:
        - {{}} 双花括号 (从 prompt format string 转义学到)
        - jinja 格式
        """
        pat1 = re.escape(TO) + r"\s*(.*?)\s*" + re.escape(TC)
        matches = re.findall(pat1, text, re.DOTALL)
        if not matches:
            matches = re.findall(r"<\|start\|>functions\.\w+<\|message\|>\s*(.*?)\s*(?:<\|end\|>|$)", text, re.DOTALL)
        if not matches:
            return None
        raw = matches[-1].strip()

        def _try_parse(s):
            try:
                return json.loads(s)
            except (json.JSONDecodeError, TypeError):
                return None

        call = _try_parse(raw)
        if call is None:
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

    def _execute_tool(self, name: str, args) -> str:
        """执行工具调用。"""
        tool = self.tools.get(name)
        if not tool:
            return f"[Tool Error: '{name}' not available]"
        try:
            if isinstance(args, str):
                args = json.loads(args)
            return tool.call(args)
        except Exception as e:
            return f"[Tool Error executing {name}: {e}]"

    def run(self, question: str) -> str:
        """主 ReAct 循环。返回最终报告。"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        for turn in range(self.max_turns):
            print(f"--- Turn {turn+1}/{self.max_turns} ---", flush=True)
            reply = self._call_llm(messages)
            messages.append({"role": "assistant", "content": reply})

            tool_call = self._parse_tool_call(reply)
            if not tool_call:
                print(">>> 最终报告生成", flush=True)
                return self._extract_report(reply)

            name, args = tool_call
            print(f">>> 调用工具: {name}({str(args)[:80]}...)", flush=True)
            result = self._execute_tool(name, args)
            print(f"<<< 结果: {result[:100]}...", flush=True)

            messages.append({"role": "user", "content": TO + "\n" + result[:8000] + "\n" + TC})

        print(">>> 达到最大轮数, 强制总结", flush=True)
        messages.append({"role": "user", "content": "You have done enough research. Now write your final report based on all information gathered."})
        return self._extract_report(self._call_llm(messages))

    def _extract_report(self, text: str) -> str:
        """从 LLM 输出提取报告 (去掉残留的 tool_call 标记和 jinja 格式)。"""
        pat = re.escape(TO) + r".*?" + re.escape(TC)
        text = re.sub(pat, "", text, flags=re.DOTALL).strip()
        text = re.sub(r"<\|start\|>functions\.\w+<\|message\|>.*?(?:<\|end\|>|$)", "", text, flags=re.DOTALL)
        text = re.sub(r"<\|start\|>.*?<\|message\|>", "", text, flags=re.DOTALL)
        text = re.sub(r"<\|end\|>", "", text)
        text = re.sub(r"<\|im_start\|>.*?<\|im_end\|>", "", text, flags=re.DOTALL)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text


class MemoryTool(BaseTool):
    """精简 memory 工具: 压缩长对话上下文。"""
    name = "memory"
    description = "Condense the conversation memory to free up context. Call when the conversation is getting long."
    parameters = [{"name": "summary", "type": "string", "description": "Optional summary to remember"}]

    def call(self, params, **kwargs):
        return "[memory] Context has been noted. Continue with your research."
