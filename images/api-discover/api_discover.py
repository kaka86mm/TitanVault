"""TitanVault API 指南服务 — 自动发现 + 机器可读 manifest。

两类输出:
  GET /manifest.json  — 结构化服务清单 (agent / 开发者消费的机器可读格式)
  GET /               — 人可读页面 (Dashboard 风格, 可视化 manifest)

发现来源:
  1. Docker 容器 (扫 0.0.0.0 发布端口, KNOWN_SERVICES 补充元数据)
  2. NATIVE_SERVICES 静态注册表 (原生 systemd 服务, 容器扫不到)

设计: agent 配置里写死 http://<host>/api-guide/manifest.json 即可拿到全部能力。
"""
from __future__ import annotations

import asyncio
import os
import socket
from typing import Any

import httpx
from docker import DockerClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

app = FastAPI(title="TitanVault API Discover", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# 服务元数据: Docker 容器匹配 (key = 容器名子串, 不区分大小写)
# 每条含: name, category, desc, key_required, type, endpoints
# endpoint 格式: (method, path, desc, request_body_or_None, notes_or_None)
# ============================================================================
KNOWN_SERVICES: dict[str, dict[str, Any]] = {
    "litellm": {
        "name": "LiteLLM (LLM 网关)", "category": "LLM", "key_required": True,
        "icon": "🧠", "color": "#10B981",
        "desc": "OpenAI 兼容 LLM 网关, 统一入口. 推荐通过此服务调用 LLM/Embedding/Rerank",
        "models": ["Qwen3.6-35B-A3B", "Qwen3-Embedding-0.6B", "Qwen3-Reranker-0.6B"],
        "endpoints": [
            ("POST", "/v1/chat/completions", "对话补全 (主力)", {
                "model": "Qwen3.6-35B-A3B",
                "messages": [{"role": "user", "content": "你好, 介绍一下你自己"}],
                "max_tokens": 200, "stream": False,
            }, "需 Authorization: Bearer <LITELLM_MASTER_KEY>"),
            ("POST", "/v1/embeddings", "文本向量化", {
                "model": "Qwen3-Embedding-0.6B",
                "input": "需要向量化的文本",
            }, None),
            ("GET", "/v1/models", "可用模型列表", None, "需 Authorization header"),
        ],
    },
    "sensevoice": {
        "name": "SenseVoice ASR", "category": "语音", "key_required": False,
        "icon": "🎙️", "color": "#F59E0B",
        "desc": "语音转文字 + 情感 + 事件检测 (FunASR, 非流式)",
        "endpoints": [
            ("POST", "/v1/audio/transcriptions", "语音转文字 (multipart file)", None,
             "curl -F file=@audio.mp3 http://<host>:9991/v1/audio/transcriptions"),
        ],
    },
    "kokoro": {
        "name": "Kokoro TTS", "category": "语音", "key_required": False,
        "icon": "🔊", "color": "#EC4899",
        "desc": "文字转语音 (OpenAI 兼容, 67 音色, 9 语言)",
        "endpoints": [
            ("POST", "/v1/audio/speech", "文字转语音", {
                "model": "kokoro", "input": "你好, 这是语音合成测试",
                "voice": "kf",
            }, "返回 audio/wav 二进制"),
            ("GET", "/v1/audio/voices", "可用音色列表", None, None),
        ],
    },
    "mineru-api": {
        "name": "MinerU API (PDF 解析)", "category": "文档", "key_required": False,
        "icon": "📄", "color": "#E8554E",
        "desc": "PDF/文档解析为 Markdown/JSON (GPU 加速)",
        "endpoints": [
            ("POST", "/file_parse", "同步解析文档", None,
             "multipart: file=@doc.pdf  返回 Markdown + 结构化 JSON"),
        ],
    },
    "mcpjungle": {
        "name": "MCPJungle", "category": "工具", "key_required": False,
        "icon": "🔧", "color": "#6366F1",
        "desc": "MCP (Model Context Protocol) 工具注册中心",
        "endpoints": [("GET", "/servers", "已注册 MCP servers", None, None)],
    },
    "token-usage": {
        "name": "Token 用量统计", "category": "运维", "key_required": False,
        "icon": "📊", "color": "#8B5CF6",
        "desc": "LiteLLM token 用量聚合 (供 Dashboard 展示)",
        "endpoints": [
            ("GET", "/api/usage", "用量汇总", None, None),
            ("GET", "/api/usage/timeseries", "时序数据", None, None),
        ],
    },
    "gitea": {
        "name": "Gitea", "category": "应用", "key_required": False, "type": "web",
        "icon": "🐙", "color": "#609926", "primary_port": 3002,
        "desc": "自托管 Git 服务", "endpoints": [],
    },
    "filebrowser": {
        "name": "Filebrowser", "category": "应用", "key_required": False, "type": "web",
        "icon": "📁", "color": "#3B82F6",
        "desc": "Web 文件管理器", "endpoints": [],
    },
    "searxng": {
        "name": "SearXNG", "category": "应用", "key_required": False, "type": "web",
        "icon": "🔍", "color": "#3050FF",
        "desc": "元搜索引擎 (隐私友好)",
        "endpoints": [("GET", "/search?q=xxx&format=json", "搜索 (JSON)", None, None)],
    },
    "open-notebook": {
        "name": "Open Notebook", "category": "应用", "key_required": False, "type": "web",
        "icon": "📓", "color": "#0891B2", "primary_port": 5055,
        "desc": "知识库 + 笔记", "endpoints": [],
    },
    "uptime-kuma": {
        "name": "Uptime Kuma", "category": "运维", "key_required": False, "type": "web",
        "icon": "🟢", "color": "#5CDD8B",
        "desc": "服务监控 + 告警", "endpoints": [],
    },
    "comfyui": {
        "name": "ComfyUI", "category": "图像", "key_required": False,
        "icon": "🎨", "color": "#7C3AED",
        "desc": "Stable Diffusion 图像生成 (GPU 加速)",
        "endpoints": [
            ("GET", "/system_stats", "系统状态", None, None),
            ("POST", "/prompt", "提交工作流", None, "body = ComfyUI workflow JSON"),
        ],
    },
    "aham": {
        "name": "Aham Voice", "category": "语音", "key_required": False,
        "icon": "🎤", "color": "#9B59D0",
        "desc": "录音转写 + 会议纪要 (SenseVoice + LLM)",
        "endpoints": [("GET", "/api/health", "健康检查", None, None)],
    },
    "open-design": {
        "name": "Open Design", "category": "Agent", "key_required": False, "type": "web",
        "icon": "🖌️", "color": "#EC4899", "primary_port": 7456,
        "desc": "AI 设计工具", "endpoints": [],
    },
    "next-ai-draw": {
        "name": "Next AI Draw", "category": "Agent", "key_required": False, "type": "web",
        "icon": "✏️", "color": "#06B6D4", "primary_port": 4733,
        "desc": "AI 画图", "endpoints": [],
    },
    "hindsight": {
        "name": "Hindsight (记忆后端)", "category": "Agent", "key_required": False,
        "icon": "🧩", "color": "#F97316",
        "desc": "Hermes Agent 记忆存储 + 检索",
        "endpoints": [],
    },
}

# ============================================================================
# 原生 systemd 服务注册表 (Docker 扫不到, 手动维护)
# 端口固定, install.sh 装完即定. agent 可直接消费.
# ============================================================================
NATIVE_SERVICES: list[dict[str, Any]] = [
    {
        "id": "llama-main", "name": "llama.cpp (主推理)", "category": "LLM",
        "port": 8082, "base_url": "http://<host>:8082", "key_required": False,
        "icon": "⚡", "color": "#3b9eff", "type": "api",
        "desc": "Qwen3.6-35B-A3B 原生推理 (Vulkan GPU, MTP 投机解码). LiteLLM 背后的引擎",
        "models": ["Qwen3.6-35B-A3B"],
        "endpoints": [
            ("POST", "/v1/chat/completions", "对话补全 (直连引擎)", {
                "model": "Qwen3.6-35B-A3B",
                "messages": [{"role": "user", "content": "你好"}],
                "max_tokens": 100, "stream": False,
            }, "直连不经 LiteLLM, 无需 key. 一般推荐走 LiteLLM :4000"),
            ("GET", "/v1/models", "已加载模型", None, None),
            ("GET", "/slots", "推理槽状态 (并发/队列)", None,
             "返回 [{id, is_processing, n_ctx, ...}], 用于判断是否过载"),
            ("GET", "/metrics", "Prometheus 指标", None,
             "tok/s, cache hit rate, 并发数等, 供 Dashboard 消费"),
        ],
    },
    {
        "id": "llama-embed", "name": "llama.cpp (Embedding)", "category": "LLM",
        "port": 8084, "base_url": "http://<host>:8084", "key_required": False,
        "icon": "🔢", "color": "#2dd4bf", "type": "api",
        "desc": "Qwen3-Embedding-0.6B 文本向量化引擎",
        "models": ["Qwen3-Embedding-0.6B"],
        "endpoints": [
            ("POST", "/v1/embeddings", "文本向量化", {
                "model": "Qwen3-Embedding-0.6B",
                "input": "需要向量化的文本",
            }, None),
        ],
    },
    {
        "id": "llama-rerank", "name": "llama.cpp (Reranker)", "category": "LLM",
        "port": 8083, "base_url": "http://<host>:8083", "key_required": False,
        "icon": "🏷️", "color": "#a855f7", "type": "api",
        "desc": "Qwen3-Reranker-0.6B 交叉编码重排 (hindsight 记忆重排用)",
        "models": ["Qwen3-Reranker-0.6B"],
        "endpoints": [
            ("POST", "/v1/rerank", "重排 (top-k)", {
                "model": "Qwen3-Reranker-0.6B",
                "query": "搜索词",
                "documents": ["候选文档1", "候选文档2"],
                "top_n": 2,
            }, None),
        ],
    },
    {
        "id": "hermes-gateway", "name": "Hermes Gateway", "category": "Agent",
        "port": 8642, "base_url": "http://<host>:8642", "key_required": True,
        "icon": "🤖", "color": "#0091CD", "type": "api",
        "desc": "Hermes Agent API (OpenAI 兼容, ops profile). Portal AI 助手入口",
        "models": [],
        "endpoints": [
            ("GET", "/healthz", "健康检查", None, None),
            ("GET", "/v1/models", "可用模型", None, "需 HERMES_API_SERVER_KEY"),
        ],
    },
    {
        "id": "hermes-dashboard", "name": "Hermes Dashboard", "category": "Agent",
        "port": 9119, "base_url": "http://<host>:9119", "key_required": False,
        "icon": "💬", "color": "#0891B2", "type": "web",
        "desc": "Hermes Agent Web UI (通用对话, default profile)",
        "models": [], "endpoints": [],
    },
    {
        "id": "opensquilla", "name": "OpenSquilla", "category": "Agent",
        "port": 18791, "base_url": "http://<host>:18791", "key_required": False,
        "icon": "🦑", "color": "#F59E0B", "type": "api",
        "desc": "Token 高效 AI Agent Gateway (代码/任务)",
        "models": [],
        "endpoints": [
            ("GET", "/healthz", "健康检查", None, None),
            ("POST", "/api/chat", "对话", {"message": "你好"}, None),
        ],
    },
]

# 排除的容器名 (网关自身 / 内部组件, 不该当独立服务展示)
EXCLUDED_CONTAINERS = {"caddy", "redis", "postgres", "minio", "frp"}

# ============================================================================
# 发现逻辑
# ============================================================================

def match_known(container_name: str) -> dict[str, Any] | None:
    name_lower = container_name.lower()
    for key, meta in KNOWN_SERVICES.items():
        if key in name_lower:
            return meta
    return None


def extract_host_ports(container) -> list[int]:
    ports = container.attrs.get("HostConfig", {}).get("PortBindings", {}) or {}
    result = []
    for bindings in ports.values():
        if not bindings:
            continue
        for b in bindings:
            ip = b.get("HostIp", "")
            port = b.get("HostPort", "")
            if port and (ip in ("0.0.0.0", "::", "")):
                try:
                    result.append(int(port))
                except ValueError:
                    pass
    return sorted(set(result))


async def probe_openapi(port: int) -> dict[str, Any] | None:
    base = os.environ.get("PROBE_BASE", "http://host-gateway")
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
                                    endpoints.append((m.upper(), p, "", None, None))
                        return {"openapi": True, "title": data.get("info", {}).get("title", ""), "paths": endpoints}
                    return {"openapi": False, "has_docs": True, "paths": []}
            except (httpx.ConnectError, httpx.TimeoutException, Exception):
                continue
    return None


def get_hostname() -> str:
    """返回本机 IP (供 manifest base_url 占位). 优先局域网 IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def normalize_service(raw: dict[str, Any]) -> dict[str, Any]:
    """统一服务对象格式 (用于 manifest + 前端)."""
    eps = raw.get("endpoints", [])
    norm_eps = []
    for e in eps:
        if isinstance(e, (list, tuple)):
            method, path, desc = e[0], e[1], e[2] if len(e) > 2 else ""
            req = e[3] if len(e) > 3 else None
            notes = e[4] if len(e) > 4 else None
            norm_eps.append({
                "method": method, "path": path, "desc": desc,
                "request": req, "notes": notes,
            })
        elif isinstance(e, dict):
            norm_eps.append(e)
    return {
        "id": raw.get("id", raw.get("name", "")),
        "name": raw.get("name", raw.get("container", "")),
        "category": raw.get("category", "其它"),
        "port": raw.get("port", 0),
        "base_url": raw.get("base_url", f"http://<host>:{raw.get('port', 0)}"),
        "key_required": raw.get("key_required", False),
        "desc": raw.get("desc", ""),
        "icon": raw.get("icon", "📦"),
        "color": raw.get("color", "#64748B"),
        "type": raw.get("type", "api"),
        "models": raw.get("models", []),
        "endpoints": norm_eps,
        "known": raw.get("known", False),
        "source": raw.get("source", "docker"),
        "has_openapi": raw.get("has_openapi", False),
    }


async def discover_all_services() -> list[dict[str, Any]]:
    """合并原生服务 + Docker 发现的服务, 去重, 返回标准化列表."""
    hostname = get_hostname()
    services: list[dict[str, Any]] = []
    seen_ports: set[int] = set()

    # 1. 原生服务 (优先, 端口固定)
    for ns in NATIVE_SERVICES:
        svc = dict(ns)
        svc["base_url"] = svc.get("base_url", "").replace("<host>", hostname)
        svc["known"] = True
        svc["source"] = "native"
        services.append(normalize_service(svc))
        seen_ports.add(svc["port"])

    # 2. Docker 容器发现
    client = DockerClient(base_url="unix:///var/run/docker.sock")
    try:
        containers = client.containers.list()
    except Exception:
        containers = []
    finally:
        client.close()

    container_info = []
    probe_tasks = []

    for c in containers:
        # 排除基础设施容器
        if any(ex in c.name.lower() for ex in EXCLUDED_CONTAINERS):
            continue

        ports = extract_host_ports(c)
        if not ports:
            continue

        meta = match_known(c.name)

        # 端口去重: 已知服务有 primary_port 就用它; 否则取最小非排除端口
        if meta and meta.get("primary_port") and meta["primary_port"] in ports:
            ports = [meta["primary_port"]]
        else:
            # 排除常见非 API 端口 (SSH 2222, HTTPS 443 等)
            ports = [p for p in ports if p not in (443, 2222)]
            if not ports:
                continue
            ports = [ports[0]]  # 只取第一个

        port = ports[0]
        if port in seen_ports:
            continue  # 原生服务已覆盖 (如 llama 直接引擎被 LiteLLM 代理)

        info = normalize_service({
            "id": c.name, "container": c.name, "name": meta["name"] if meta else c.name,
            "category": meta["category"] if meta else "其它",
            "desc": meta["desc"] if meta else "",
            "icon": meta.get("icon", "📦") if meta else "📦",
            "color": meta.get("color", "#64748B") if meta else "#64748B",
            "type": meta.get("type", "api") if meta else "api",
            "key_required": meta.get("key_required", False) if meta else False,
            "models": meta.get("models", []) if meta else [],
            "endpoints": meta["endpoints"] if meta else [],
            "known": meta is not None, "source": "docker", "port": port,
            "base_url": f"http://{hostname}:{port}",
        })
        container_info.append(info)
        seen_ports.add(port)
        probe_tasks.append(probe_openapi(port))

    # 并行探测 OpenAPI
    probe_results = await asyncio.gather(*probe_tasks, return_exceptions=True)
    for info, probe in zip(container_info, probe_results):
        if isinstance(probe, dict):
            if probe.get("openapi") and not info["endpoints"]:
                # 新发现的 API: 自动取前 8 个端点
                info["endpoints"] = probe["paths"][:8]
            info["has_openapi"] = probe.get("openapi", False)

    services.extend(container_info)
    return services


# ============================================================================
# API 端点
# ============================================================================

@app.get("/manifest.json")
async def manifest() -> dict[str, Any]:
    """机器可读服务清单 — agent 配置写死此 URL 即可获取全部 API 能力."""
    services = await discover_all_services()
    hostname = get_hostname()
    return {
        "version": "2.0",
        "platform": "TitanVault",
        "hardware": "AMD Ryzen AI Max+ 395 (gfx1151, Radeon 8060S, 128GB unified memory)",
        "host": hostname,
        "generated_at": asyncio.get_event_loop().time(),
        "auth": {
            "litellm": {"env": "LITELLM_MASTER_KEY", "header": "Authorization: Bearer <key>"},
            "hermes": {"env": "HERMES_API_SERVER_KEY", "header": "Authorization: Bearer <key>"},
        },
        "entry_points": {
            "recommended_llm": f"http://{hostname}:4000/v1",
            "direct_llama": f"http://{hostname}:8082/v1",
            "manifest": f"http://{hostname}/api-guide/manifest.json",
        },
        "categories": ["LLM", "语音", "文档", "图像", "工具", "Agent", "应用", "运维"],
        "services": services,
        "total": len(services),
    }


@app.get("/api/services")
async def list_services() -> dict[str, Any]:
    """兼容旧格式: 服务列表 (前端 fetch 用)."""
    services = await discover_all_services()
    return {"services": services, "total": len(services)}


@app.get("/api/health/{port}")
async def health_proxy(port: int):
    """健康检查代理 (绕过 CORS)."""
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
    """API 测试代理 (浏览器发请求经此转发, 避免 CORS)."""
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
    """人可读页面 (Dashboard 风格)."""
    html_path = os.environ.get("API_GUIDE_HTML", "/app/index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path, media_type="text/html")
    return HTMLResponse("<h1>TitanVault API Discover</h1><p>index.html not found</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("API_DISCOVER_PORT", "8098")))
