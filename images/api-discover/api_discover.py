"""API 自动发现服务。

扫描 docker 容器, 自动发现暴露端口的服务, 探测哪些有 OpenAPI (API 服务),
提供: 服务清单 JSON + 单服务健康检查代理 (解决浏览器 CORS)。

发现规则:
- 扫所有 running 容器, 取 0.0.0.0 发布的端口 (宿主端口)
- 探测每个端口的 /openapi.json (FastAPI 服务) 或 /docs
- 已知服务 (compose 配置) 补充人类可读的名称/描述/端点
- 新装服务只要暴露端口 + 有 openapi 就自动出现在清单里
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from docker import DockerClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

app = FastAPI(title="Mozin API Discover", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 已知服务的元数据 (名称/描述/类型)。未在此表的服务也会被发现, 但只有端口/健康。
# key = 容器名包含的关键词 (匹配容器名, 不区分大小写)
KNOWN_SERVICES: dict[str, dict[str, Any]] = {
    "litellm": {
        "name": "LiteLLM (LLM 网关)", "category": "LLM", "key_required": True,
        "desc": "OpenAI 兼容 LLM 网关。Chat + Embedding。",
        "endpoints": [
            ("POST", "/v1/chat/completions", "对话补全"),
            ("POST", "/v1/embeddings", "向量化"),
            ("GET", "/v1/models", "模型列表"),
        ],
    },
    "sensevoice": {
        "name": "SenseVoice ASR", "category": "语音", "key_required": False,
        "desc": "语音转文字 + 情感 + 事件检测",
        "endpoints": [("POST", "/v1/audio/transcriptions", "语音转文字")],
    },
    "kokoro": {
        "name": "Kokoro TTS", "category": "语音", "key_required": False,
        "desc": "文字转语音 (OpenAI 兼容)",
        "endpoints": [("POST", "/v1/audio/speech", "文字转语音"), ("GET", "/v1/audio/voices", "音色列表")],
    },
    "mineru-api": {
        "name": "MinerU API (PDF 解析)", "category": "文档", "key_required": False,
        "desc": "PDF/文档解析为 Markdown/JSON (ROCm GPU)",
        "endpoints": [("POST", "/file_parse", "同步解析"), ("POST", "/tasks", "异步解析")],
    },
    "mineru-web": {
        "name": "MinerU Web", "category": "文档", "key_required": False, "type": "web",
        "desc": "PDF 解析 Web UI", "endpoints": [],
    },
    "mcpjungle": {
        "name": "MCPJungle", "category": "工具", "key_required": False,
        "desc": "MCP (Model Context Protocol) 工具注册中心",
        "endpoints": [("GET", "/servers", "已注册 servers")],
    },
    "token-usage": {
        "name": "Token 用量统计", "category": "运维", "key_required": False,
        "desc": "LiteLLM token 用量聚合",
        "endpoints": [("GET", "/api/usage", "用量汇总"), ("GET", "/api/usage/timeseries", "时序数据")],
    },
    "gitea": {
        "name": "Gitea", "category": "应用", "key_required": False, "type": "web",
        "desc": "自托管 Git", "endpoints": [],
    },
    "filebrowser": {
        "name": "Filebrowser", "category": "应用", "key_required": False, "type": "web",
        "desc": "文件管理", "endpoints": [],
    },
    "searxng": {
        "name": "SearXNG", "category": "应用", "key_required": False, "type": "web",
        "desc": "元搜索", "endpoints": [("GET", "/search?q=xxx&format=json", "搜索")],
    },
    "open-notebook": {
        "name": "Open Notebook", "category": "应用", "key_required": False, "type": "web",
        "desc": "知识库", "endpoints": [],
    },
    "uptime-kuma": {
        "name": "uptime-kuma", "category": "运维", "key_required": False, "type": "web",
        "desc": "服务监控 + 告警", "endpoints": [],
    },
    "comfyui": {
        "name": "ComfyUI", "category": "图像", "key_required": False,
        "desc": "Stable Diffusion 图像生成 (ROCm GPU)",
        "endpoints": [("GET", "/system_stats", "系统状态"), ("POST", "/prompt", "提交工作流")],
    },
    "hermes": {
        "name": "Hermes Agent", "category": "Agent", "key_required": True, "type": "web",
        "desc": "自我进化的 AI agent (Nous Research)",
        "endpoints": [("GET", "/healthz", "健康检查")],
    },
    "opensquilla": {
        "name": "OpenSquilla", "category": "Agent", "key_required": False,
        "desc": "token 高效 AI agent",
        "endpoints": [("GET", "/healthz", "健康检查"), ("POST", "/api/chat", "对话")],
    },
    "open-design": {
        "name": "Open Design", "category": "Agent", "key_required": False, "type": "web",
        "desc": "设计工具", "endpoints": [],
    },
    "next-ai-draw": {
        "name": "Next AI Draw", "category": "Agent", "key_required": False, "type": "web",
        "desc": "AI 画图", "endpoints": [],
    },
    "aham": {
        "name": "Aham Voice", "category": "语音", "key_required": False,
        "desc": "录音转写 + 会议纪要 (ROCm GPU)",
        "endpoints": [("GET", "/api/health", "健康检查")],
    },
}


def match_known(container_name: str) -> dict[str, Any] | None:
    """容器名匹配已知服务元数据。"""
    name_lower = container_name.lower()
    for key, meta in KNOWN_SERVICES.items():
        if key in name_lower:
            return meta
    return None


def extract_host_ports(container) -> list[int]:
    """从 docker 容器提取 0.0.0.0 发布的宿主端口。"""
    ports = container.attrs.get("HostConfig", {}).get("PortBindings", {}) or {}
    result = []
    for bindings in ports.values():
        if not bindings:
            continue
        for b in bindings:
            ip = b.get("HostIp", "")
            port = b.get("HostPort", "")
            # 只取 0.0.0.0 或空 IP (对外发布的)
            if port and (ip in ("0.0.0.0", "::", "")):
                try:
                    result.append(int(port))
                except ValueError:
                    pass
    return sorted(set(result))


async def probe_openapi(port: int) -> dict[str, Any] | None:
    """探测端口是否有 OpenAPI 定义。经 host-gateway 访问宿主发布端口。"""
    base = os.environ.get("PROBE_BASE", "http://host-gateway")  # 容器内用 host-gateway 访问宿主端口
    async with httpx.AsyncClient(timeout=3) as client:
        for path in ("/openapi.json", "/docs"):
            try:
                r = await client.get(f"{base}:{port}{path}")
                if r.status_code == 200:
                    if path == "/openapi.json":
                        data = r.json()
                        endpoints = []
                        for p, methods in (data.get("paths") or {}).items():
                            for m in methods:
                                if m.upper() in ("GET", "POST", "PUT", "DELETE"):
                                    endpoints.append((m.upper(), p, ""))
                        return {"openapi": True, "title": data.get("info", {}).get("title", ""), "paths": endpoints}
                    return {"openapi": False, "has_docs": True, "paths": []}
            except (httpx.ConnectError, httpx.TimeoutException, Exception):
                continue
    return None


@app.get("/api/services")
async def list_services() -> dict[str, Any]:
    """发现所有运行中的服务 (从 docker 容器自动扫描)。"""
    client = DockerClient(base_url="unix:///var/run/docker.sock")
    try:
        containers = client.containers.list()
    finally:
        client.close()

    services = []
    tasks = []
    container_info = []

    for c in containers:
        ports = extract_host_ports(c)
        if not ports:
            continue
        name = c.name
        meta = match_known(name)
        for port in ports:
            info = {
                "container": name,
                "port": port,
                "image": c.image.tags[0] if c.image.tags else "",
                "name": meta["name"] if meta else name,
                "category": meta["category"] if meta else "其它",
                "desc": meta["desc"] if meta else "",
                "type": meta.get("type", "api") if meta else "api",
                "key_required": meta.get("key_required", False) if meta else False,
                "endpoints": meta["endpoints"] if meta else [],
                "known": meta is not None,
            }
            container_info.append(info)
            tasks.append(probe_openapi(port))

    # 并行探测 OpenAPI
    probe_results = await asyncio.gather(*tasks, return_exceptions=True)
    for info, probe in zip(container_info, probe_results):
        if isinstance(probe, dict):
            if probe.get("openapi") and not info["endpoints"]:
                info["endpoints"] = probe["paths"][:10]  # 新发现的 API, 自动取端点
            info["has_openapi"] = probe.get("openapi", False)
        else:
            info["has_openapi"] = False

    services = container_info
    return {"services": services, "total": len(services)}


@app.get("/api/health/{port}")
async def health_proxy(port: int):
    """健康检查代理 (解决浏览器 CORS)。经 host-gateway 探测宿主端口。"""
    base = os.environ.get("PROBE_BASE", "http://host-gateway")
    paths = ["/health", "/healthz", "/v1/models", "/api/health", "/"]
    async with httpx.AsyncClient(timeout=5) as client:
        for path in paths:
            try:
                r = await client.get(f"{base}:{port}{path}")
                if r.status_code < 500:
                    return {"online": True, "status": r.status_code, "path": path, "port": port}
            except (httpx.ConnectError, httpx.TimeoutException):
                continue
            except Exception:
                continue
    return {"online": False, "status": 0, "port": port}


@app.get("/api/test/{port}")
async def test_proxy(port: int, method: str = "GET", path: str = "/", body: str = ""):
    """API 测试代理 (浏览器发请求经此转发, 避免 CORS + 统一格式)。"""
    base = os.environ.get("PROBE_BASE", "http://host-gateway")
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            headers = {"Content-Type": "application/json"}
            kwargs: dict[str, Any] = {"headers": headers, "timeout": 30}
            if body:
                kwargs["content"] = body
            r = await client.request(method, f"{base}:{port}{path}", **kwargs)
            ct = r.headers.get("content-type", "")
            try:
                resp_body = r.json() if "json" in ct else r.text
            except Exception:
                resp_body = r.text
            return {"status": r.status_code, "body": resp_body, "content_type": ct}
        except Exception as e:
            return {"status": 0, "error": str(e)}


@app.get("/")
async def index():
    """API 指南前端页面。"""
    html_path = os.environ.get("API_GUIDE_HTML", "/app/index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path, media_type="text/html")
    return HTMLResponse("<h1>API Discover</h1><p>index.html not found</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("API_DISCOVER_PORT", "8098")))
