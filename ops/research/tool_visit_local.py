"""
tool_visit_local.py — QUEST visit tool 本地化 (requests+trafilatura 替换 Jina)

替换 QUEST 原生的 r.jina.ai 调用, 改用本机直接抓取 + trafilatura 提取正文。
对于需要 JS 渲染的页面, 可选走 Chrome CDP。

保持 BaseTool 接口不变, QUEST agent 无需改动即可调用。

环境变量:
    CHROME_CDP_URL  默认 http://localhost:9222 (可选, JS 重度页面用)
"""
import os
import re
import json
import subprocess
import requests
from typing import List, Union, Optional, Dict
from urllib.parse import urlparse

from qwen_agent.tools.base import BaseTool, register_tool

# Summary model 配置 (从环境变量读, 指向本机 LiteLLM)
SUMMARY_MODEL_NAME = os.environ.get("SUMMARY_MODEL_NAME", "gpt-4o-mini")
SUMMARY_API_BASE = os.environ.get("SUMMARY_API_BASE", os.environ.get("API_BASE", "http://localhost:4000/v1"))
SUMMARY_API_KEY = os.environ.get("SUMMARY_API_KEY", os.environ.get("API_KEY", "EMPTY"))
CHROME_CDP_URL = os.environ.get("CHROME_CDP_URL", "http://localhost:9222")

# 已知需要 JS 渲染的域名 (走 Chrome CDP)
JS_HEAVY_DOMAINS = {
    "twitter.com", "x.com", "reddit.com", "instagram.com",
    "facebook.com", "linkedin.com", "tiktok.com",
}


def _is_js_heavy(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    return any(d in domain for d in JS_HEAVY_DOMAINS)


def _fetch_with_chrome(url: str, timeout: int = 20) -> Optional[str]:
    """用已开的 Chrome CDP 实例拿渲染后的 HTML。"""
    try:
        import websocket  # 延迟导入, 可能没装
        ws_url = f"{CHROME_CDP_URL}/json/new?{url}"
        resp = requests.put(ws_url, timeout=timeout).json()
        target_id = resp.get("id")
        ws_url = resp.get("webSocketDebuggerUrl")
        if not ws_url:
            return None
        ws = websocket.create_connection(ws_url, timeout=timeout)
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": "document.documentElement.outerHTML",
                                       "returnByValue": True}}))
        result = json.loads(ws.recv())
        ws.close()
        # 关闭 tab
        requests.get(f"{CHROME_CDP_URL}/json/close/{target_id}", timeout=5)
        html = result.get("result", {}).get("result", {}).get("value", "")
        return html if html else None
    except Exception:
        return None


def _fetch_with_requests(url: str, timeout: int = 15) -> Optional[str]:
    """直接 requests 抓取 HTML。"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        # 检测编码
        if resp.encoding == "ISO-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text
    except Exception:
        return None


def _html_to_text(html: str) -> str:
    """用 trafilatura 提取正文 (没有则退化为正则去标签)。"""
    try:
        import trafilatura
        text = trafilatura.extract(
            html,
            include_links=True,
            include_tables=True,
            favor_recall=True,
        )
        if text and len(text) > 100:
            return text
    except ImportError:
        pass
    # 退化: 正则去标签
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:8000]  # 截断防超长


def _summarize(text: str, url: str) -> str:
    """用本机 LLM 做网页摘要 (如果文本太长)。"""
    if len(text) < 3000:
        return text
    try:
        from openai import OpenAI
        client = OpenAI(api_key=SUMMARY_API_KEY, base_url=SUMMARY_API_BASE)
        resp = client.chat.completions.create(
            model=SUMMARY_MODEL_NAME,
            messages=[
                {"role": "system", "content": "Extract the key information from this webpage content. "
                                               "Keep all facts, numbers, names, and dates. "
                                               "Output clean markdown."},
                {"role": "user", "content": f"URL: {url}\n\nContent:\n{text[:12000]}"},
            ],
            max_tokens=2000,
        )
        return resp.choices[0].message.content
    except Exception as e:
        # 摘要失败则截断返回
        return text[:6000] + f"\n\n[Note: summarization failed ({e}), showing truncated content]"


@register_tool("visit", allow_overwrite=True)
class Visit(BaseTool):
    name = "visit"
    description = (
        "Read webpage content from one or more URLs. Supply 'url' (string or array). "
        "Returns the main text content of each page, summarized if very long."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Array of URLs to read.",
            },
            "goal": {
                "type": "string",
                "description": "The goal/purpose of reading these pages (helps focus extraction).",
            },
        },
        "required": ["url"],
    }

    def readpage(self, url: str, goal: str = "") -> str:
        # 1. 选抓取方式
        html = None
        if _is_js_heavy(url):
            html = _fetch_with_chrome(url)
        if not html:
            html = _fetch_with_requests(url)
        if not html:
            return f"[visit] Failed to fetch {url}"

        # 2. 提取正文
        text = _html_to_text(html)
        if not text or len(text) < 50:
            return f"[visit] No readable content at {url}"

        # 3. 太长则摘要
        text = _summarize(text, url)

        prefix = f"## {url}\n"
        if goal:
            prefix += f"(Reading goal: {goal})\n"
        return prefix + text

    def call(self, params: Union[str, dict], **kwargs) -> str:
        params = self._verify_json_format_args(params)
        urls = params.get("url", [])
        goal = params.get("goal", "")
        if isinstance(urls, str):
            urls = [urls]
        if not urls:
            return "[Tool Error] No URL provided."

        results = []
        for u in urls[:5]:  # 限制每次最多 5 个
            results.append(self.readpage(u, goal))
        return "\n\n---\n\n".join(results)
