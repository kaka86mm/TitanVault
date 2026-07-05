"""
agent-reach-bridge — HTTP 桥接服务, 让 deep-research 容器调用宿主的 agent-reach 能力。

暴露:
  POST /exa          {"query": "...", "num": 5}  → Exa 语义搜索
  POST /twitter      {"query": "...", "num": 10} → Twitter 搜索/用户时间线
  POST /xiaohongshu  {"query": "...", "num": 10} → 小红书搜索

运行: python3 bridge.py (监听 :18061)
     用 mihomo 代理访问国外平台
"""
import os
import json
import subprocess
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

app = FastAPI(title="Agent Reach Bridge")

# 代理 (mihomo)
PROXY_ENV = {
    "https_proxy": "http://localhost:7890",
    "http_proxy": "http://localhost:7890",
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin") + ":/home/matri/.local/bin",
}
# mcporter/twitter 的环境
FULL_ENV = {**os.environ, **PROXY_ENV}

MCPORTER = "/usr/bin/mcporter"
TWITTER = "/home/matri/.local/bin/twitter"


class SearchReq(BaseModel):
    query: str = ""
    num: int = 5
    user: str = ""  # twitter 用户时间线 (可选)


def _run(cmd: list, timeout: int = 60) -> dict:
    """运行命令, 返回 {"ok": bool, "stdout": str, "stderr": str}。"""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, env=FULL_ENV)
        return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e)}


@app.post("/exa")
async def exa_search(req: SearchReq):
    """Exa 语义搜索。"""
    cmd = [MCPORTER, "call",
           f'exa.web_search_exa(query: "{req.query}", numResults: {req.num})',
           "--timeout", "30000"]
    r = _run(cmd, timeout=45)
    return {"ok": r["ok"], "raw": r["stdout"][:8000],
            "error": r["stderr"] if not r["ok"] else ""}


@app.post("/twitter")
async def twitter_search(req: SearchReq):
    """Twitter 搜索或用户时间线。"""
    if req.user:
        cmd = [TWITTER, "user-posts", f"@{req.user.lstrip('@')}",
               "-n", str(req.num), "--yaml"]
    else:
        cmd = [TWITTER, "search", req.query, "-n", str(req.num), "--yaml"]
    r = _run(cmd, timeout=45)
    return {"ok": r["ok"], "raw": r["stdout"][:8000],
            "error": r["stderr"][:300] if not r["ok"] else ""}


@app.post("/xiaohongshu")
async def xiaohongshu_search(req: SearchReq):
    """小红书搜索。"""
    cmd = [MCPORTER, "call",
           f'xiaohongshu.search_feeds(keyword: "{req.query}")',
           "--timeout", "120000"]
    r = _run(cmd, timeout=130)
    return {"ok": r["ok"], "raw": r["stdout"][:20000],
            "error": r["stderr"][:300] if not r["ok"] else ""}


@app.post("/wechat")
async def wechat_search(req: SearchReq):
    """微信公众号文章搜索 (weixin_search_mcp, :8809)。

    返回 JSON: [{title, real_url, publish_time}]
    real_url 是 mp.weixin.qq.com 真实链接 (已从搜狗跳转链接转换)。
    """
    cmd = [MCPORTER, "call",
           f'weixin.weixin_search(query: "{req.query}")',
           "--timeout", "30000"]
    r = _run(cmd, timeout=40)
    return {"ok": r["ok"], "raw": r["stdout"][:20000],
            "error": r["stderr"][:300] if not r["ok"] else ""}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=18061, log_level="info")
