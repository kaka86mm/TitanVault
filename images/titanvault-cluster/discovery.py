"""
discovery.py — mDNS 自动发现 (zeroconf)

通过 mDNS 广播自己 + 发现局域网/USB4 直连的其他 TitanVault Cluster 节点。
服务类型: _titanvault-cluster._tcp.local.
"""
import socket
import threading
import time
import logging
from typing import Callable, Optional
from dataclasses import dataclass, field
from zeroconf import Zeroconf, ServiceInfo
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

logger = logging.getLogger("cluster.discovery")

SERVICE_TYPE = "_tv-cluster._tcp.local."
BROWSE_INTERVAL = 5  # 秒, 定期重新扫描


@dataclass
class PeerNode:
    """发现的对端节点信息。"""
    node_id: str
    ip: str
    port: int
    hostname: str
    properties: dict = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)

    @property
    def is_stale(self) -> bool:
        """超过 30 秒未更新视为过期。"""
        return time.time() - self.last_seen > 30

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "ip": self.ip,
            "port": self.port,
            "hostname": self.hostname,
            "properties": self.properties,
            "last_seen": self.last_seen,
            "online": not self.is_stale,
        }


def get_best_interface_ip() -> str:
    """获取最佳网络接口 IP (优先 USB4/thunderbolt link-local, 其次局域网)。

    USB4 直连会创建 thunderbolt0 接口, IP 在 169.254.x.x 段。
    如果没有 USB4 直连, 回退到局域网 IP。
    """
    # 优先查找 thunderbolt / usb4 接口的 link-local 地址
    try:
        import subprocess
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            # 格式: "2: thunderbolt0: <BROADCAST...> mtu 1500 ... inet 169.254.1.1/16 ..."
            parts = line.split()
            if len(parts) < 4:
                continue
            iface = parts[1]
            # 优先 thunderbolt/usb4 接口
            if "thunderbolt" in iface or "usb" in iface:
                for i, p in enumerate(parts):
                    if p == "inet" and i + 1 < len(parts):
                        ip = parts[i + 1].split("/")[0]
                        if ip.startswith("169.254."):
                            logger.info(f"Using USB4/TB interface {iface}: {ip}")
                            return ip
    except Exception:
        pass

    # 回退: 获取能连外网的 IP (局域网)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        logger.info(f"Using LAN interface IP: {ip}")
        return ip
    except Exception:
        return "127.0.0.1"


class ClusterDiscovery:
    """mDNS 节点发现服务。

    用法:
        discovery = ClusterDiscovery(node_id="node-1", port=8094, properties={"role": "worker"})
        discovery.start()  # 注册自己 + 开始监听
        peers = discovery.get_peers()  # 获取已发现的节点
        discovery.stop()
    """

    def __init__(
        self,
        node_id: str,
        port: int,
        hostname: Optional[str] = None,
        properties: Optional[dict] = None,
        on_peer_found: Optional[Callable[[PeerNode], None]] = None,
        on_peer_lost: Optional[Callable[[str], None]] = None,
    ):
        self.node_id = node_id
        self.port = port
        self.hostname = hostname or socket.gethostname()
        self.properties = properties or {}
        self.on_peer_found = on_peer_found
        self.on_peer_lost = on_peer_lost

        self._zeroconf: Optional[AsyncZeroconf] = None
        self._service_info: Optional[ServiceInfo] = None
        self._browser: Optional[AsyncServiceBrowser] = None
        self._peers: dict[str, PeerNode] = {}  # node_id -> PeerNode
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._ready: Optional[threading.Event] = None
        self._running = False
        self._cleanup_thread: Optional[threading.Thread] = None
        self._my_ip: Optional[str] = None

    def start(self):
        """启动发现服务: 注册 mDNS 服务 + 开始浏览。

        在独立线程中运行 zeroconf (它有自己的事件循环, 跟 FastAPI asyncio 不兼容)。
        """
        if self._running:
            return

        self._my_ip = get_best_interface_ip()

        # _running 必须在启动线程前设为 True, 否则线程的事件循环会立即退出
        self._running = True
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)

        # 启动清理线程
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def _run_in_thread(self):
        """zeroconf 在自己的线程 + 事件循环里运行。"""
        import asyncio

        async def _init():
            loop = asyncio.get_running_loop()

            # 注册自己的服务
            self._zeroconf = AsyncZeroconf(ip_version="IPv4")

            props = {k: str(v) for k, v in self.properties.items()}
            props["node_id"] = self.node_id
            props["hostname"] = self.hostname

            self._service_info = ServiceInfo(
                type_=SERVICE_TYPE,
                name=f"tv-{self.node_id[-10:]}.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(self._my_ip)],
                port=self.port,
                properties=props,
            )
            await self._zeroconf.async_register_service(self._service_info)
            logger.info(f"mDNS registered: {self.node_id} @ {self._my_ip}:{self.port}")

            # 开始浏览 (AsyncServiceBrowser 需要底层 Zeroconf 对象)
            self._browser = AsyncServiceBrowser(self._zeroconf.zeroconf, SERVICE_TYPE, self)
            logger.info("mDNS browsing started")
            self._ready.set()

            # 保持事件循环运行
            while self._running:
                await asyncio.sleep(1)

            # 清理: 注销服务 + 关闭 zeroconf
            if self._browser:
                self._browser.cancel()
            if self._service_info and self._zeroconf:
                await self._zeroconf.async_unregister_service(self._service_info)
            if self._zeroconf:
                await self._zeroconf.async_close()

        try:
            asyncio.run(_init())
        except Exception as e:
            logger.error(f"Discovery thread error: {e}")
            self._ready.set()

    def stop(self):
        """停止发现服务: 清理 mDNS 注册 + 关闭 zeroconf + join 线程。"""
        self._running = False
        # 等线程退出 (它会在下一次 asyncio.sleep(1) 后检测到 _running=False)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("mDNS discovery stopped")

    def get_peers(self) -> list[PeerNode]:
        """获取当前已发现的非过期对端节点列表。"""
        with self._lock:
            return [p for p in self._peers.values() if not p.is_stale]

    def get_all_peers(self) -> list[PeerNode]:
        """获取所有节点 (含过期)。"""
        with self._lock:
            return list(self._peers.values())

    # --- AsyncServiceBrowser 回调 ---

    async def add_service(self, zeroconf, type_: str, name: str):
        """发现新服务时调用 (async)。"""
        try:
            from zeroconf.asyncio import AsyncServiceInfo
            info = AsyncServiceInfo(type_, name)
            await info.async_request(zeroconf, timeout=3000)
            if not info.info_from_cache() and not info.addresses:
                return

            # 解析 IP
            if info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
            else:
                return

            # 跳过自己
            if ip == self._my_ip and info.port == self.port:
                return

            # 提取 node_id
            props = {}
            if info.properties:
                for k, v in info.properties.items():
                    props[k.decode() if isinstance(k, bytes) else k] = (
                        v.decode() if isinstance(v, bytes) else v
                    )

            peer_id = props.get("node_id", name.split(".")[0])
            peer_hostname = props.get("hostname", peer_id)

            peer = PeerNode(
                node_id=peer_id,
                ip=ip,
                port=info.port,
                hostname=peer_hostname,
                properties=props,
                last_seen=time.time(),
            )

            with self._lock:
                is_new = peer_id not in self._peers
                self._peers[peer_id] = peer

            if is_new:
                logger.info(f"Peer discovered: {peer_id} @ {ip}:{info.port} ({peer_hostname})")
                if self.on_peer_found:
                    self.on_peer_found(peer)

        except Exception as e:
            logger.error(f"Error in add_service for {name}: {e}")

    async def update_service(self, zeroconf, type_: str, name: str):
        """服务更新时调用 (刷新 last_seen)。"""
        await self.add_service(zeroconf, type_, name)

    async def remove_service(self, zeroconf, type_: str, name: str):
        """服务消失时调用。"""
        peer_id = name.split(".")[0]
        with self._lock:
            if peer_id in self._peers:
                del self._peers[peer_id]
        logger.info(f"Peer lost: {peer_id}")
        if self.on_peer_lost:
            self.on_peer_lost(peer_id)

    def _cleanup_loop(self):
        """定期清理过期节点 (mDNS 可能不触发 remove_service)。"""
        while self._running:
            time.sleep(10)
            with self._lock:
                stale = [pid for pid, p in self._peers.items() if p.is_stale]
                for pid in stale:
                    del self._peers[pid]
                    logger.info(f"Peer expired (cleanup): {pid}")
                    if self.on_peer_lost:
                        self.on_peer_lost(pid)
