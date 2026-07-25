"""
node.py — 节点状态收集

收集本机的 GPU 型号/显存、模型列表、llama.cpp 服务状态等信息。
"""
import os
import re
import subprocess
import socket
import glob
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("cluster.node")

MODEL_DIR = os.environ.get("MODEL_DIR", "/data/models")
LLAMA_CPP_DIR = os.environ.get("LLAMA_CPP_DIR", "/opt/llama.cpp")
LLAMA_RPC_BIN = os.path.join(LLAMA_CPP_DIR, "llama-rpc-server")
LLAMA_SERVER_BIN = os.path.join(LLAMA_CPP_DIR, "llama-server")


@dataclass
class NodeStatus:
    """节点完整状态。"""
    node_id: str
    hostname: str
    ip: str
    port: int

    # GPU 信息
    gpu_name: str = ""
    gpu_driver: str = ""
    vram_total_gb: float = 0.0
    vram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    ram_used_gb: float = 0.0

    # llama.cpp
    llama_cpp_available: bool = False
    rpc_server_available: bool = False
    llama_server_running: bool = False
    rpc_server_running: bool = False

    # 角色
    role: str = "idle"  # idle / master / worker
    role_detail: str = ""  # e.g. "master, serving Qwen3.6-35B-A3B"

    # 模型
    local_models: list = field(default_factory=list)  # [{name, path, size_gb}]

    # 元数据
    last_updated: str = ""
    is_self: bool = False  # 在 cluster 视图中标记是否是自己

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "hostname": self.hostname,
            "ip": self.ip,
            "port": self.port,
            "gpu_name": self.gpu_name,
            "vram_total_gb": round(self.vram_total_gb, 1),
            "vram_used_gb": round(self.vram_used_gb, 1),
            "vram_free_gb": round(self.vram_total_gb - self.vram_used_gb, 1),
            "ram_total_gb": round(self.ram_total_gb, 1),
            "ram_used_gb": round(self.ram_used_gb, 1),
            "llama_cpp_available": self.llama_cpp_available,
            "rpc_server_available": self.rpc_server_available,
            "llama_server_running": self.llama_server_running,
            "rpc_server_running": self.rpc_server_running,
            "role": self.role,
            "role_detail": self.role_detail,
            "local_models": self.local_models,
            "last_updated": self.last_updated,
            "is_self": self.is_self,
        }


def get_gpu_info() -> tuple[str, str, float, float]:
    """获取 GPU 信息: (name, driver, vram_total_gb, vram_used_gb)。

    尝试 rocm-smi, 回退到读取 sysfs/llama.cpp 报告。
    """
    # 尝试 rocm-smi
    try:
        result = subprocess.run(
            ["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            gpu = data.get("card0", data.get("GPU0", {}))
            name = gpu.get("Card series", gpu.get("Device Name", "AMD GPU"))
            vram_total = int(gpu.get("VRAM Total Memory (B)", 0)) / 1024**3
            vram_used = int(gpu.get("VRAM Total Used Memory (B)", 0)) / 1024**3
            driver = "ROCm"
            if vram_total == 0:
                # GTT 统一内存场景: rocm-smi 可能报 512MB
                # 回退到读取 amdgpu sysfs
                vram_total = _read_gtt_vram()
            return name.strip(), driver, vram_total, vram_used
    except Exception:
        pass

    # 尝试读取 sysfs (amdgpu)
    try:
        name_path = "/sys/class/drm/card0/device/product_name"
        vram_path = "/sys/class/drm/card0/device/mem_info_vram_total"
        used_path = "/sys/class/drm/card0/device/mem_info_vram_used"
        name = "Unknown GPU"
        vram_total = 0.0
        vram_used = 0.0
        if os.path.exists(name_path):
            with open(name_path) as f:
                name = f.read().strip()
        if os.path.exists(vram_path):
            with open(vram_path) as f:
                vram_total = int(f.read().strip()) / 1024**3
        if os.path.exists(used_path):
            with open(used_path) as f:
                vram_used = int(f.read().strip()) / 1024**3
        if vram_total > 0:
            return name, "amdgpu", vram_total, vram_used
    except Exception:
        pass

    # GTT 统一内存: 尝试 /proc/meminfo 的 MemTotal 作为近似
    try:
        import psutil
        mem = psutil.virtual_memory()
        # Strix Halo 统一内存: MemTotal ≈ 显存总量
        return "AMD APU (Unified Memory)", "GTT", mem.total / 1024**3, (mem.total - mem.available) / 1024**3
    except Exception:
        pass

    return "Unknown", "", 0.0, 0.0


def _read_gtt_vram() -> float:
    """读取 GTT 统一内存大小 (Strix Halo 128GB)。

    通过 /proc/meminfo 估算, 因为 GTT 显存 = 系统内存 (统一内存架构)。
    """
    try:
        import psutil
        return psutil.virtual_memory().total / 1024**3
    except Exception:
        return 128.0  # 默认值


def get_ram_info() -> tuple[float, float]:
    """获取 RAM 信息: (total_gb, used_gb)。"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        return mem.total / 1024**3, (mem.total - mem.available) / 1024**3
    except Exception:
        return 0.0, 0.0


def check_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """检查端口是否开放 (服务是否在运行)。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def check_process_running(pattern: str) -> bool:
    """检查包含指定模式的进程是否在运行。"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, timeout=2
        )
        return result.returncode == 0
    except Exception:
        return False


def scan_local_models() -> list[dict]:
    """扫描本地 GGUF 模型文件。

    返回 [{name, path, size_gb}] 列表, 按大小降序。
    """
    models = []
    search_paths = [
        os.path.join(MODEL_DIR, "**", "*.gguf"),
        "/data/models/**/*.gguf",
    ]
    seen = set()
    for pattern in search_paths:
        for path in glob.glob(pattern, recursive=True):
            if path in seen:
                continue
            seen.add(path)
            try:
                size = os.path.getsize(path) / 1024**3
                name = os.path.basename(path)
                # 清理文件名: 去掉 .gguf 后缀
                if name.endswith(".gguf"):
                    name = name[:-5]
                models.append({
                    "name": name,
                    "path": path,
                    "size_gb": round(size, 1),
                })
            except Exception:
                continue
    models.sort(key=lambda m: m["size_gb"], reverse=True)
    return models


def collect_node_status(node_id: str, port: int, my_ip: str = "") -> NodeStatus:
    """收集本节点完整状态。"""
    gpu_name, gpu_driver, vram_total, vram_used = get_gpu_info()
    ram_total, ram_used = get_ram_info()

    # 检查 llama.cpp 二进制
    llama_available = os.path.exists(LLAMA_SERVER_BIN)
    rpc_available = os.path.exists(LLAMA_RPC_BIN)

    # 检查服务运行状态
    server_running = check_port_open(8082) or check_process_running("llama-server")
    rpc_running = check_port_open(50052) or check_process_running("llama-rpc-server")

    # 扫描本地模型
    models = scan_local_models()

    return NodeStatus(
        node_id=node_id,
        hostname=socket.gethostname(),
        ip=my_ip or "127.0.0.1",
        port=port,
        gpu_name=gpu_name,
        gpu_driver=gpu_driver,
        vram_total_gb=vram_total,
        vram_used_gb=vram_used,
        ram_total_gb=ram_total,
        ram_used_gb=ram_used,
        llama_cpp_available=llama_available,
        rpc_server_available=rpc_available,
        llama_server_running=server_running,
        rpc_server_running=rpc_running,
        local_models=models,
        last_updated=datetime.now().isoformat(),
        is_self=True,
    )
