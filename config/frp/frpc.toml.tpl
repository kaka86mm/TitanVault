# config/frp/frpc.toml.tpl
# frp 客户端配置骨架。install.sh Phase 1 用 FRP_SERVER_ADDR / FRP_TOKEN 渲染。
#
# 留空 (无 FRP_SERVER_ADDR) 时, frpc 连不上 server 但 loginFailExit=false 让它
# 静默重试 (不刷屏日志/不死循环 exit), 不影响其余服务。
# 需启用穿透时填 .env 的 FRP_SERVER_ADDR/FRP_TOKEN。
# loginFailExit=false: server 不可达时 frpc 不退出, 持续重试 (适合 frp server 偶尔离线)。
loginFailExit = false
serverAddr = "${FRP_SERVER_ADDR}"
serverPort = 7000

# frp v2 TOML: auth 用 dotted key (不是 [[auth]] table array, 那会解析失败)
auth.method = "token"
auth.token = "${FRP_TOKEN}"

# 默认穿透 Caddy (HTTP 门户)
[[proxies]]
name = "mozin-web"
type = "tcp"
localIP = "127.0.0.1"
localPort = 80
remotePort = 8080

# 按需追加更多穿透 (示例: Gitea SSH)
# [[proxies]]
# name = "mozin-git-ssh"
# type = "tcp"
# localIP = "127.0.0.1"
# localPort = 2222
# remotePort = 2222
