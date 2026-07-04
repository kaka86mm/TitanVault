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


# QUEST 的 system prompt (从 QUEST prompt.py 提炼的精简版)
SYSTEM_PROMPT = """You are QUEST, a deep research agent. Your goal is to answer the user's question thoroughly using web search and page reading.

## Available Tools
- search: Search the web. Input: {"query": ["query1", "query2"]} (array of queries)
- visit: Read webpage content. Input: {"url": ["url1", "url2"], "goal": "what you're looking for"}

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
- End with a confidence assessment

To call a tool, output:
<tool_call>
{"name": "tool_name", "arguments": {...}}
</tool_call>

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
        # 工具注册表
        self.tools: Dict[str, BaseTool] = {}
        for name in function_list:
            tool_cls = self._get_tool_class(name)
            if tool_cls:
                self.tools[name] = tool_cls()

    def _get_tool_class(self, name: str):
        """从 qwen_agent 工具注册表获取工具类。"""
        from qwen_agent.tools.base import TOOL_REGISTRY
        # TOOL_REGISTRY: name -> 工具类 (直接是类, 不是 dict)
        tool_cls = TOOL_REGISTRY.get(name)
        if tool_cls and isinstance(tool_cls, type):
            return tool_cls
        # memory 工具特殊处理 (用内置简化版)
        if name == "memory":
            return MemoryTool
        return None

    def _call_llm(self, messages: List[Dict]) -> str:
        """调用 LLM, 返回文本。"""
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=4096,
                temperature=0.7,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            return f"[LLM Error: {e}]"

    def _parse_tool_call(self, text: str):
        """从 LLM 输出解析 tool_call。返回 (name, args) 或 None。"""
        matches = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.DOTALL)
        if not matches:
            return None
        raw = matches[-1].strip()
        try:
            call = json.loads(raw)
            return call.get("name"), call.get("arguments", {})
        except json.JSONDecodeError:
            return None

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

            # 检查是否调工具
            tool_call = self._parse_tool_call(reply)
            if not tool_call:
                # 没有工具调用 = 最终报告
                print(">>> 最终报告生成", flush=True)
                return self._extract_report(reply)

            name, args = tool_call
            print(f">>> 调用工具: {name}({str(args)[:80]}...)", flush=True)
            result = self._execute_tool(name, args)
            print(f"<<< 结果: {result[:100]}...", flush=True)

            # 把工具结果作为 user message 回填
            messages.append({"role": "user", "content": f"<tool_response>\n{result[:8000]}\n</tool_response>"})

        # 超过最大轮数, 强制要 LLM 总结
        print(">>> 达到最大轮数, 强制总结", flush=True)
        messages.append({"role": "user", "content": "You have done enough research. Now write your final report based on all information gathered."})
        return self._extract_report(self._call_llm(messages))

    def _extract_report(self, text: str) -> str:
        """从 LLM 输出提取报告 (去掉残留的 tool_call 标记)。"""
        text = re.sub(r"<tool_call>.*?</tool_call>", "", text, flags=re.DOTALL).strip()
        return text


class MemoryTool(BaseTool):
    """精简 memory 工具: 压缩长对话上下文。"""
    name = "memory"
    description = "Condense the conversation memory to free up context. Call when the conversation is getting long."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def call(self, params, **kwargs):
        return "[memory] Context has been noted. Continue with your research."
