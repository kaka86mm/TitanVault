"""
tool_search_local.py — QUEST search tool 本地化 (SearXNG 替换 Serper)

替换 QUEST 原生的 google.serper.dev 调用, 改用本机 SearXNG :8087。
保持 BaseTool 接口不变, QUEST agent 无需改动即可调用。

环境变量:
    SEARXNG_URL  默认 http://localhost:8087
"""
import os
import json
import re
import requests
from typing import List, Union, Optional

from qwen_agent.tools.base import BaseTool, register_tool

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://localhost:8087")


@register_tool("search", allow_overwrite=True)
class Search(BaseTool):
    name = "search"
    description = (
        "Performs batched web searches: supply an array 'query'; the tool "
        "retrieves the top 10 results for each query in one call."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Array of query strings. Include multiple complementary search queries in a single call.",
            },
        },
        "required": ["query"],
    }

    def search_with_searxng(self, query: str) -> str:
        """调用本机 SearXNG, 返回与 Serper 兼容的格式。"""
        # 语言检测: 中文用 zh, 否则 en
        lang = "zh" if any("\u4E00" <= c <= "\u9FFF" for c in query) else "en"
        try:
            resp = requests.get(
                f"{SEARXNG_URL}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": "general",
                    "pageno": 1,
                    "language": lang,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            return f"[search] SearXNG error for '{query}': {e}"

        results = data.get("results", [])
        if not results:
            return f"No results found for query: '{query}'. Use a less specific query."

        web_snippets = []
        for idx, page in enumerate(results[:10], 1):
            title = page.get("title", "")
            link = page.get("url", "")
            snippet = page.get("content", "")
            date_published = ""
            # SearXNG 可能在 publishedDate 给日期
            if page.get("publishedDate"):
                date_published = "\nDate published: " + str(page["publishedDate"])

            entry = f"Title: {title}\nLink: {link}{date_published}"
            if snippet:
                entry += f"\nSnippets: {snippet}"
            web_snippets.append(entry)

        return f"## Search Results\nQuery: {query}\n\n" + "\n\n".join(web_snippets)

    def call(self, params: Union[str, dict], **kwargs) -> str:
        params = self._verify_json_format_args(params)
        query = params.get("query")
        if not query:
            return "[Tool Error] Search query cannot be empty."

        # query 是数组, 每个独立搜索
        queries = query if isinstance(query, list) else [query]
        responses = [self.search_with_searxng(q) for q in queries]
        return "\n\n".join(responses)
