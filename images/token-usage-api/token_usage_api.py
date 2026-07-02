#!/usr/bin/env python3
"""
Aham Station — Usage API

薄代理 + 内存聚合层：从 LiteLLM 的 /spend/logs（免费、事件级）拉取原始用量，
在服务端按 model / api_key / user 任意维度聚合，TTL 缓存避免重复全量拉取。

设计依据（业界标准，OpenAI Usage API / Anthropic / LiteLLM 一致）：
  - API 只返回结构化数字（整数 token、浮点 spend、整数 requests）
  - 格式化（中文/图表）是前端职责，不进 API
  - 提供三层视图：明细(raw logs)、聚合(by model/key/user)、时序(by day)

数据源说明：
  LiteLLM 免费版只提供 /spend/logs（事件流）。聚合报表 /global/spend/report
  是企业版功能。本地自建模型（llama.cpp）在 cost map 里没有定价，spend 恒为 0——
  这是本地推理的正确表现，API 照常返回，前端自行决定是否展示金额。

环境变量:
  LITELLM_BASE_URL   LiteLLM 地址，默认 http://localhost:4000
  LITELLM_MASTER_KEY master key（鉴权用）
  USAGE_API_PORT     监听端口，默认 8090
  USAGE_CACHE_TTL    聚合缓存秒数，默认 60
  USAGE_LOG_LIMIT    单次从 litellm 拉取的事件上限，默认 5000
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict
from typing import Any

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

LITELLM_BASE_URL = os.getenv("LITELLM_BASE_URL", "http://localhost:4000").rstrip("/")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "")
PORT = int(os.getenv("USAGE_API_PORT", "8090"))
CACHE_TTL = int(os.getenv("USAGE_CACHE_TTL", "60"))
LOG_LIMIT = int(os.getenv("USAGE_LOG_LIMIT", "5000"))

app = FastAPI(title="Aham Station Usage API", version="2.0")

# ---------------------------------------------------------------------------
# 缓存：缓存的是“从 litellm 拉到的原始事件列表”，聚合在每次请求时即时算。
# 这样不同 group_by / 时间窗的请求能共享同一份拉取结果，省掉重复网络往返。
# ---------------------------------------------------------------------------
_cache_lock = asyncio.Lock()
_cache: dict[str, Any] = {"logs": None, "fetched_at": 0.0}


async def fetch_logs() -> list[dict]:
    """从 LiteLLM /spend/logs 拉事件。带 TTL 缓存，并发请求合并为一次拉取。"""
    async with _cache_lock:
        now = time.time()
        if _cache["logs"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL:
            return _cache["logs"]
        # 缓存过期，重新拉取
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{LITELLM_BASE_URL}/spend/logs",
                params={"limit": LOG_LIMIT},
                headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"},
            )
            resp.raise_for_status()
            logs = resp.json()
        if not isinstance(logs, list):
            logs = []
        _cache["logs"] = logs
        _cache["fetched_at"] = now
        return logs


def _filter_by_date(logs: list[dict], start: str | None, end: str | None) -> list[dict]:
    """按 startTime 的日期前缀过滤（LiteLLM 返回 ISO8601 带时区，取前 10 位 YYYY-MM-DD）。"""
    if not start and not end:
        return logs
    out = []
    for r in logs:
        ts = (r.get("startTime") or "")[:10]
        if start and ts < start:
            continue
        if end and ts > end:
            continue
        out.append(r)
    return out


def _aggregate(logs: list[dict], group_by: str) -> list[dict]:
    """按指定维度聚合 token / spend / 请求数 / 失败数。"""
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "spend": 0.0,
            "requests": 0,
            "failed_requests": 0,
        }
    )
    field_map = {"model": "model", "api_key": "api_key", "user": "user"}
    field = field_map.get(group_by, "model")
    for r in logs:
        key = r.get(field) or "(unknown)"
        b = buckets[key]
        b["prompt_tokens"] += r.get("prompt_tokens", 0) or 0
        b["completion_tokens"] += r.get("completion_tokens", 0) or 0
        b["total_tokens"] += r.get("total_tokens", 0) or 0
        b["spend"] += r.get("spend", 0) or 0
        b["requests"] += 1
        if (r.get("metadata") or {}).get("status") == "failure":
            b["failed_requests"] += 1
    # 按 total_tokens 降序，便于前端直接展示
    return sorted(
        [{"group": k, **v} for k, v in buckets.items()],
        key=lambda x: x["total_tokens"],
        reverse=True,
    )


def _timeseries(logs: list[dict]) -> list[dict]:
    """按天聚合，用于画趋势图。"""
    days: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
        }
    )
    for r in logs:
        day = (r.get("startTime") or "")[:10]
        if not day:
            continue
        d = days[day]
        d["prompt_tokens"] += r.get("prompt_tokens", 0) or 0
        d["completion_tokens"] += r.get("completion_tokens", 0) or 0
        d["total_tokens"] += r.get("total_tokens", 0) or 0
        d["requests"] += 1
    return [{"date": k, **v} for k, v in sorted(days.items())]


def _totals(logs: list[dict]) -> dict[str, Any]:
    """全量汇总。"""
    return {
        "prompt_tokens": sum(r.get("prompt_tokens", 0) or 0 for r in logs),
        "completion_tokens": sum(r.get("completion_tokens", 0) or 0 for r in logs),
        "total_tokens": sum(r.get("total_tokens", 0) or 0 for r in logs),
        "spend": round(sum(r.get("spend", 0) or 0 for r in logs), 6),
        "requests": len(logs),
        "failed_requests": sum(
            1 for r in logs if (r.get("metadata") or {}).get("status") == "failure"
        ),
    }


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@app.get("/api/usage")
async def get_usage(
    group_by: str = Query("model", pattern="^(model|api_key|user)$"),
    start_date: str | None = Query(None, description="YYYY-MM-DD（含）"),
    end_date: str | None = Query(None, description="YYYY-MM-DD（含）"),
):
    """主接口：聚合用量。默认按 model 分组，返回全部历史。

    对齐 OpenAI Usage API 的响应形状：结构化数字，不预设展示格式。
    """
    try:
        logs = await fetch_logs()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"failed to fetch from litellm: {e}"},
        )

    logs = _filter_by_date(logs, start_date, end_date)
    return {
        "group_by": group_by,
        "start_date": start_date,
        "end_date": end_date,
        "totals": _totals(logs),
        "breakdown": _aggregate(logs, group_by),
    }


@app.get("/api/usage/timeseries")
async def get_timeseries(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
):
    """时序视图：按天的 token / 请求数趋势。用于前端画图。"""
    try:
        logs = await fetch_logs()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"failed to fetch from litellm: {e}"},
        )
    logs = _filter_by_date(logs, start_date, end_date)
    return {"start_date": start_date, "end_date": end_date, "series": _timeseries(logs)}


@app.get("/api/usage/logs")
async def get_logs(
    limit: int = Query(50, ge=1, le=500),
    model: str | None = Query(None),
):
    """明细视图：最近 N 条原始事件，可选按 model 过滤。供调试/审计。"""
    try:
        logs = await fetch_logs()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"failed to fetch from litellm: {e}"},
        )
    if model:
        logs = [r for r in logs if r.get("model") == model]
    # 最近优先
    return {"logs": logs[:limit]}


@app.get("/api/usage/summary")
async def get_summary(
    start_date: str | None = Query(None, description="YYYY-MM-DD（含）"),
    end_date: str | None = Query(None, description="YYYY-MM-DD（含）"),
):
    """首页卡片用：一行汇总。不带日期=全部历史；带日期=该时间窗内。"""
    try:
        logs = await fetch_logs()
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"failed to fetch from litellm: {e}"},
        )
    logs = _filter_by_date(logs, start_date, end_date)
    return {
        "start_date": start_date,
        "end_date": end_date,
        **_totals(logs),
    }


@app.get("/health")
async def health():
    """探活。顺带报告上游 litellm 是否可达，便于排查。"""
    upstream = "unknown"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{LITELLM_BASE_URL}/health/liveliness",
                headers={"Authorization": f"Bearer {LITELLM_MASTER_KEY}"},
            )
            upstream = "ok" if r.status_code == 200 else f"http_{r.status_code}"
    except Exception:
        upstream = "unreachable"
    return {"status": "ok", "upstream_litellm": upstream}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
