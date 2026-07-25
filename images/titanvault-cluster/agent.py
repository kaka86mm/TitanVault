"""
agent.py — TitanVault Cluster Agent

每节点运行的 P2P 编排服务:
- mDNS 自动发现其他节点
- WebSocket 实时推送集群状态到 Dashboard
- 模型部署编排 (远程启动 rpc-server, 本地启动 llama-server --rpc)
- OpenAI API 透传
"""
import os
import json
import time
import uuid
import socket
import logging
import asyncio
import threading
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx

from discovery import ClusterDiscovery, PeerNode, get_best_interface_ip
from node import collect_node_status, NodeStatus, check_port_open
from model_registry import get_all_models, get_model_info
from orchestrator import (
    plan_deployment, start_rpc_server, start_distributed_server,
    stop_process, DeploymentPlan,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("cluster.agent")

# ============================================================================
# 全局状态
# ============================================================================

NODE_ID = os.environ.get("CLUSTER_NODE_ID", f"node-{socket.gethostname()[:8]}")
AGENT_PORT = int(os.environ.get("CLUSTER_AGENT_PORT", "8094"))
MY_IP = ""
LLAMA_CPP_DIR = os.environ.get("LLAMA_CPP_DIR", "/opt/llama.cpp")

# 集群状态
discovery: Optional[ClusterDiscovery] = None
# 已连接的 WebSocket 客户端
ws_clients: set[WebSocket] = set()
# 当前部署
current_deployment: Optional[DeploymentPlan] = None
current_rpc_proc = None  # 本地的 rpc-server 进程 (worker 模式)
current_server_proc = None  # 本地的 llama-server 进程 (master 模式)
# peer 节点状态缓存 (通过 HTTP 拉取)
peer_statuses: dict[str, dict] = {}

app = FastAPI(title="TitanVault Cluster Agent")


# ============================================================================
# 状态收集 & 广播
# ============================================================================

def refresh_my_status() -> dict:
    """收集本节点状态。"""
    status = collect_node_status(NODE_ID, AGENT_PORT, MY_IP)
    # 更新角色
    if current_server_proc and current_server_proc.poll() is None:
        status.role = "master"
        status.role_detail = f"Serving {current_deployment.model_name}" if current_deployment else "Starting..."
    elif current_rpc_proc and current_rpc_proc.poll() is None:
        status.role = "worker"
        status.role_detail = "RPC server running"
    return status.to_dict()


async def fetch_peer_status(peer: PeerNode) -> Optional[dict]:
    """通过 HTTP 拉取对端节点的状态。"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"http://{peer.ip}:{peer.port}/api/status")
            if resp.status_code == 200:
                data = resp.json()
                data["is_self"] = False
                return data
    except Exception as e:
        logger.debug(f"Failed to fetch status from {peer.node_id}: {e}")
    return None


async def get_cluster_status() -> dict:
    """获取完整集群状态 (自己 + 所有 peer)。"""
    nodes = [refresh_my_status()]
    peers = discovery.get_peers() if discovery else []
    for peer in peers:
        status = await fetch_peer_status(peer)
        if status:
            nodes.append(status)
    return {
        "cluster_id": NODE_ID,  # 简化: 用自己的 ID
        "nodes": nodes,
        "node_count": len(nodes),
        "timestamp": datetime.now().isoformat(),
    }


async def broadcast_to_clients(message: dict):
    """向所有 WebSocket 客户端广播消息。"""
    if not ws_clients:
        return
    text = json.dumps(message, ensure_ascii=False)
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send_text(text)
        except Exception:
            dead.add(ws)
    ws_clients.difference_update(dead)


async def status_broadcast_loop():
    """定期广播集群状态到 WebSocket 客户端。"""
    while True:
        try:
            status = await get_cluster_status()
            await broadcast_to_clients({"type": "cluster_status", "data": status})
        except Exception as e:
            logger.error(f"Broadcast error: {e}")
        await asyncio.sleep(5)


# ============================================================================
# API 路由
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Cluster Dashboard。"""
    # 尝试读模板, 回退到内联
    import pathlib
    tpl = pathlib.Path(__file__).parent / "templates" / "dashboard.html"
    if tpl.exists():
        return HTMLResponse(tpl.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>TitanVault Cluster</h1><p>Dashboard template missing</p>")


@app.get("/api/status")
async def api_status():
    """本节点状态 (给其他节点拉取用)。"""
    return refresh_my_status()


@app.get("/api/cluster")
async def api_cluster():
    """完整集群状态。"""
    return await get_cluster_status()


@app.get("/api/models")
async def api_models():
    """可用模型列表 (预置 + 本地扫描)。"""
    return {"models": get_all_models()}


@app.get("/api/deployment")
async def api_deployment():
    """当前部署状态。"""
    if current_deployment:
        return {
            "deployed": True,
            "plan": current_deployment.to_dict(),
            "rpc_running": current_rpc_proc is not None and current_rpc_proc.poll() is None,
            "server_running": current_server_proc is not None and current_server_proc.poll() is None,
        }
    return {"deployed": False}


@app.post("/api/plan")
async def api_plan(req: Request):
    """计算部署方案 (不执行, 只预览)。"""
    body = await req.json()
    model_path = body.get("model_path", "")
    model = get_model_info(model_path)
    if not model:
        raise HTTPException(404, "Model not found")

    total_layers = model.get("layers") or 64
    cluster = await get_cluster_status()
    nodes = [
        {
            "node_id": n["node_id"],
            "ip": n["ip"],
            "port": n["port"],
            "vram_free_gb": n.get("vram_free_gb", n.get("vram_total_gb", 64)),
            "is_self": n.get("is_self", False),
        }
        for n in cluster["nodes"]
        if n.get("vram_total_gb", 0) > 0 or n.get("is_self")
    ]
    if len(nodes) < 1:
        raise HTTPException(400, "No nodes available")

    plan = plan_deployment(model_path, model["name"], total_layers, nodes)
    return plan.to_dict()


@app.post("/api/deploy")
async def api_deploy(req: Request):
    """部署模型: 远程启动 worker rpc-server + 本地启动 master llama-server。"""
    global current_deployment, current_rpc_proc, current_server_proc

    body = await req.json()
    model_path = body.get("model_path", "")
    model = get_model_info(model_path)
    if not model:
        raise HTTPException(404, "Model not found")
    if not os.path.exists(model_path):
        raise HTTPException(400, f"Model file not found: {model_path}")

    # 先停止已有部署
    await api_undeploy()

    total_layers = model.get("layers") or 64
    cluster = await get_cluster_status()
    nodes = [
        {
            "node_id": n["node_id"],
            "ip": n["ip"],
            "port": n["port"],
            "vram_free_gb": n.get("vram_free_gb", n.get("vram_total_gb", 64)),
            "is_self": n.get("is_self", False),
        }
        for n in cluster["nodes"]
        if n.get("vram_total_gb", 0) > 0 or n.get("is_self")
    ]

    plan = plan_deployment(model_path, model["name"], total_layers, nodes)

    # 1. 远程启动 worker rpc-server (通过 agent API)
    for worker in plan.workers:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"http://{worker['ip']}:{worker.get('port', AGENT_PORT)}/api/rpc/start",
                    json={"port": 50052}
                )
                logger.info(f"Remote rpc-server start on {worker['node_id']}: {resp.status_code}")
        except Exception as e:
            logger.error(f"Failed to start rpc-server on {worker['node_id']}: {e}")

    # 2. 等待 worker rpc-server 就绪
    await asyncio.sleep(3)

    # 3. 本地启动 master llama-server (--rpc)
    extra_args = []
    if model.get("notes") and "MoE" in model.get("notes", ""):
        extra_args += ["--parallel", "2", "-cb"]

    current_server_proc = start_distributed_server(
        model_path=model_path,
        rpc_endpoints=plan.rpc_endpoints if plan.workers else "",
        tensor_split=plan.tensor_split if plan.workers else "",
        ngl=plan.ngl,
        model_alias=model["name"],
        extra_args=extra_args,
    )
    current_deployment = plan

    await broadcast_to_clients({
        "type": "deployment_update",
        "data": {"deployed": current_server_proc is not None, "plan": plan.to_dict()},
    })

    return {"deployed": current_server_proc is not None, "plan": plan.to_dict()}


@app.post("/api/undeploy")
async def api_undeploy():
    """停止当前部署。"""
    global current_deployment, current_rpc_proc, current_server_proc

    # 停止主 server
    if current_server_proc:
        stop_process(current_server_proc)
        current_server_proc = None

    # 停止远程 worker rpc-server
    if current_deployment:
        for worker in current_deployment.workers:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        f"http://{worker['ip']}:{worker.get('port', AGENT_PORT)}/api/rpc/stop"
                    )
            except Exception:
                pass

    # 停止本地 rpc-server (如果自己是 worker)
    if current_rpc_proc:
        stop_process(current_rpc_proc)
        current_rpc_proc = None

    current_deployment = None
    await broadcast_to_clients({"type": "deployment_update", "data": {"deployed": False}})
    return {"stopped": True}


@app.post("/api/rpc/start")
async def api_rpc_start(req: Request):
    """在本地启动 rpc-server (被远程 master 调用)。"""
    global current_rpc_proc
    if current_rpc_proc and current_rpc_proc.poll() is None:
        return {"running": True, "message": "rpc-server already running"}

    body = await req.json()
    port = body.get("port", 50052)
    current_rpc_proc = start_rpc_server(port=port)
    return {"running": current_rpc_proc is not None}


@app.post("/api/rpc/stop")
async def api_rpc_stop():
    """停止本地 rpc-server。"""
    global current_rpc_proc
    if current_rpc_proc:
        stop_process(current_rpc_proc)
        current_rpc_proc = None
    return {"stopped": True}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket: 实时推送集群状态。"""
    await ws.accept()
    ws_clients.add(ws)
    try:
        # 立即推送一次状态
        status = await get_cluster_status()
        await ws.send_text(json.dumps({"type": "cluster_status", "data": status}, ensure_ascii=False))
        # 保持连接, 接收心跳
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)


# ============================================================================
# OpenAI API 透传
# ============================================================================

@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def api_proxy(path: str, request: Request):
    """透传 OpenAI API 请求到主节点的 llama-server。"""
    target = f"http://127.0.0.1:{os.environ.get('CLUSTER_DEPLOY_PORT', '8082')}/v1/{path}"
    body = await request.body()
    headers = dict(request.headers)
    headers.pop("host", None)
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.request(
            request.method, target,
            content=body, headers=headers,
            params=request.query_params,
        )
    return JSONResponse(resp.json(), status_code=resp.status_code)


# ============================================================================
# 启动 & 关闭
# ============================================================================

@app.on_event("startup")
async def startup():
    """启动 mDNS 发现 + 状态广播。"""
    global discovery, MY_IP
    MY_IP = get_best_interface_ip()

    discovery = ClusterDiscovery(
        node_id=NODE_ID,
        port=AGENT_PORT,
        properties={
            "llama_cpp": str(os.path.exists(os.path.join(LLAMA_CPP_DIR, "llama-server"))),
            "rpc_capable": str(os.path.exists(os.path.join(LLAMA_CPP_DIR, "llama-rpc-server"))),
        },
    )
    discovery.start()
    logger.info(f"Cluster agent started: {NODE_ID} @ {MY_IP}:{AGENT_PORT}")

    # 启动状态广播
    asyncio.create_task(status_broadcast_loop())


@app.on_event("shutdown")
async def shutdown():
    """清理。"""
    if discovery:
        discovery.stop()
    if current_server_proc:
        stop_process(current_server_proc)
    if current_rpc_proc:
        stop_process(current_rpc_proc)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
