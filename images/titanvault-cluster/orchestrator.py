"""
orchestrator.py — RPC 编排: 计算层分配, 远程启动 rpc-server, 启动主 llama-server
"""
import os
import re
import time
import logging
import subprocess
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger("cluster.orchestrator")

LLAMA_CPP_DIR = os.environ.get("LLAMA_CPP_DIR", "/opt/llama.cpp")
LLAMA_RPC_BIN = os.path.join(LLAMA_CPP_DIR, "llama-rpc-server")
LLAMA_SERVER_BIN = os.path.join(LLAMA_CPP_DIR, "llama-server")
RPC_PORT = int(os.environ.get("CLUSTER_RPC_PORT", "50052"))
DEPLOY_PORT = int(os.environ.get("CLUSTER_DEPLOY_PORT", "8082"))


@dataclass
class DeploymentPlan:
    """模型部署方案。"""
    model_path: str
    model_name: str
    total_layers: int
    master_node_id: str
    master_ip: str
    # worker 节点: [{node_id, ip, rpc_endpoint, layers, tensor_split}]
    workers: list
    # 主节点的本地层数 (主节点 GPU 也参与计算)
    master_local_layers: int
    # 完整的 --rpc 参数
    rpc_endpoints: str
    # tensor split 参数 (-ts)
    tensor_split: str
    # ngl 总数
    ngl: int

    def to_dict(self) -> dict:
        return {
            "model_path": self.model_path,
            "model_name": self.model_name,
            "total_layers": self.total_layers,
            "master_node_id": self.master_node_id,
            "master_ip": self.master_ip,
            "workers": self.workers,
            "master_local_layers": self.master_local_layers,
            "rpc_endpoints": self.rpc_endpoints,
            "tensor_split": self.tensor_split,
            "ngl": self.ngl,
        }


def plan_deployment(
    model_path: str,
    model_name: str,
    total_layers: int,
    nodes: list[dict],  # [{node_id, ip, port, vram_free_gb, is_self}]
) -> DeploymentPlan:
    """计算部署方案: 按节点可用 VRAM 分配层数。

    nodes 中 is_self=True 的节点是主节点 (也参与 GPU 计算)。
    """
    # 找主节点
    master = next((n for n in nodes if n.get("is_self")), nodes[0])
    workers = [n for n in nodes if n != master]

    # 按 VRAM 比例分配 tensor split
    all_nodes = [master] + workers
    total_vram = sum(n.get("vram_free_gb", 1) for n in all_nodes)
    if total_vram == 0:
        total_vram = len(all_nodes)  # 平均分配

    splits = []
    for n in all_nodes:
        ratio = n.get("vram_free_gb", 1) / total_vram
        splits.append(max(1, round(ratio * 10)))  # 用整数比例

    # RPC endpoints (不含主节点, 主节点是本地 GPU)
    rpc_endpoints = ",".join(f"{w['ip']}:{RPC_PORT}" for w in workers)

    # tensor split: 主节点 + 各 worker
    tensor_split = ",".join(str(s) for s in splits)

    # workers 详情 (层分配: 按比例分, 主节点拿剩余, 保证不出现负数)
    worker_details = []
    remaining = total_layers
    for i, w in enumerate(workers):
        if i == len(workers) - 1:
            # 最后一个 worker 拿剩余 (避免四舍五入误差)
            worker_layers = max(0, remaining - max(1, total_layers - remaining))
        else:
            worker_layers = max(1, round(total_layers * splits[i + 1] / sum(splits)))
        remaining -= worker_layers
        worker_details.append({
            "node_id": w["node_id"],
            "ip": w["ip"],
            "rpc_endpoint": f"{w['ip']}:{RPC_PORT}",
            "layers": worker_layers,
            "tensor_split": splits[i + 1],
            "vram_free_gb": w.get("vram_free_gb", 0),
        })

    master_layers = max(1, total_layers - sum(wd["layers"] for wd in worker_details))

    return DeploymentPlan(
        model_path=model_path,
        model_name=model_name,
        total_layers=total_layers,
        master_node_id=master["node_id"],
        master_ip=master["ip"],
        workers=worker_details,
        master_local_layers=master_layers,
        rpc_endpoints=rpc_endpoints,
        tensor_split=tensor_split,
        ngl=total_layers,
    )


def start_rpc_server(port: int = RPC_PORT, host: str = "0.0.0.0") -> Optional[subprocess.Popen]:
    """在本地启动 llama-rpc-server。

    返回 subprocess.Popen 对象, 失败返回 None。
    """
    if not os.path.exists(LLAMA_RPC_BIN):
        logger.error(f"llama-rpc-server not found: {LLAMA_RPC_BIN}")
        return None

    cmd = [LLAMA_RPC_BIN, "--host", host, "--port", str(port)]
    logger.info(f"Starting rpc-server: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={**os.environ, "LD_LIBRARY_PATH": LLAMA_CPP_DIR},
            start_new_session=True,  # 独立进程组, stop 时 kill 整组
        )
        # 等待启动
        time.sleep(2)
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode()[:500] if proc.stderr else ""
            logger.error(f"rpc-server failed to start: {stderr}")
            return None
        logger.info(f"rpc-server started (PID={proc.pid}, port={port})")
        return proc
    except Exception as e:
        logger.error(f"Failed to start rpc-server: {e}")
        return None


def start_distributed_server(
    model_path: str,
    rpc_endpoints: str,
    tensor_split: str,
    ngl: int,
    port: int = DEPLOY_PORT,
    model_alias: str = "",
    extra_args: list = None,
) -> Optional[subprocess.Popen]:
    """启动主 llama-server (带 --rpc 分布式推理)。

    在主节点上运行, 连接各 worker 的 rpc-server。
    """
    if not os.path.exists(LLAMA_SERVER_BIN):
        logger.error(f"llama-server not found: {LLAMA_SERVER_BIN}")
        return None

    cmd = [
        LLAMA_SERVER_BIN,
        "-m", model_path,
        "--host", "0.0.0.0",
        "--port", str(port),
        "--rpc", rpc_endpoints,
        "-ts", tensor_split,
        "-ngl", str(ngl),
        "-c", "32768",
        "--no-mmap",
    ]
    if model_alias:
        cmd += ["--alias", model_alias]
    if extra_args:
        cmd += extra_args

    logger.info(f"Starting distributed llama-server: {' '.join(cmd[:6])}... --rpc {rpc_endpoints}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env={**os.environ, "LD_LIBRARY_PATH": LLAMA_CPP_DIR},
            start_new_session=True,  # 独立进程组
        )
        time.sleep(3)
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode()[:500] if proc.stderr else ""
            logger.error(f"llama-server failed to start: {stderr}")
            return None
        logger.info(f"Distributed llama-server started (PID={proc.pid}, port={port})")
        return proc
    except Exception as e:
        logger.error(f"Failed to start llama-server: {e}")
        return None


def stop_process(proc: Optional[subprocess.Popen]) -> bool:
    """停止一个进程及其整个进程组。"""
    if proc is None:
        return True
    try:
        import signal
        # kill 整个进程组 (start_new_session=True 创建的独立会话)
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
        logger.info(f"Process stopped (PID={proc.pid})")
        return True
    except Exception:
        try:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=2)
            return True
        except Exception:
            return False
