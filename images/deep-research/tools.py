"""
tools.py — Deep Research 工具集 (SearXNG 搜索 + 网页阅读)

本地化实现, 无外部付费 API。
- search: SearXNG 元搜索引擎
- visit: requests + trafilatura 网页抓取
"""
import os
import re
import json
import requests
from typing import List, Optional
from urllib.parse import urlparse

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://host-gateway:8087")
# 已知需要 JS 渲染的域名 (走 Chrome CDP, 当前简化为标记跳过)
JS_HEAVY_DOMAINS = {"twitter.com", "x.com", "reddit.com", "instagram.com"}


def search(query: str, skip_queries: list = None) -> dict:
    """SearXNG 搜索。返回 {"query", "results": [{"title","url","snippet"}]}.

    skip_queries: 已搜过的 query 列表 (去重, 避免迭代时重复搜索)。
    """
    if skip_queries and query.lower() in [q.lower() for q in skip_queries]:
        return {"query": query, "results": [], "skipped": True}

    lang = "zh" if any("\u4E00" <= c <= "\u9FFF" for c in query) else "en"
    try:
        resp = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json", "categories": "general",
                    "pageno": 1, "language": lang},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"query": query, "results": [], "error": str(e)}

    results = []
    for r in data.get("results", [])[:10]:
        results.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", "")[:200],
        })
    return {"query": query, "results": results}


def visit(url: str, goal: str = "") -> dict:
    """抓取网页正文。返回 {"url", "content", "goal"}."""
    # 检查 JS 重度站点
    domain = urlparse(url).netloc.lower()
    if any(d in domain for d in JS_HEAVY_DOMAINS):
        return {"url": url, "content": "", "error": "JS-heavy site, skipped"}

    # 抓取 HTML
    try:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                 "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        if resp.encoding == "ISO-8859-1":
            resp.encoding = resp.apparent_encoding
        html = resp.text
    except Exception as e:
        return {"url": url, "content": "", "error": str(e)}

    # 提取正文
    text = _html_to_text(html)
    if not text or len(text) < 50:
        return {"url": url, "content": "", "error": "No readable content"}

    # 截断防超长
    text = text[:8000]
    return {"url": url, "content": text, "goal": goal}


def _html_to_text(html: str) -> str:
    """trafilatura 提取正文, 失败则正则去标签。"""
    try:
        import trafilatura
        text = trafilatura.extract(html, include_links=True, include_tables=True,
                                   favor_recall=True)
        if text and len(text) > 100:
            return text
    except Exception:
        pass
    # 退化
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
