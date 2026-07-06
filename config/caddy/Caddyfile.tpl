# config/caddy/Caddyfile.tpl
# Caddy 统一网关 — 监听 :80 (0.0.0.0, 所有子网可达)。
#
# 三类路由:
#
# A. /api-guide — 静态 API 指南页 (端点定义 + 调用示例 + 一键测试 + 健康检查)
#    caddy file_server 直接托管, 无需容器。
#
# B. 有 web UI 的服务 — /go/<name> 跳转到 http://{host}:端口
#    静态资源用绝对路径, 子路径反代会 404 白屏, 直接端口跳转最干净。
#    {host} 是 caddy 内置占位符, 多子网下自动跟随。
#
# C. 门户门面 (homepage SPA) — 兜底默认路由。
#
# caddy 走 bridge(mozin) 网络, 故:
#   - bridge 网络容器: 用服务名 DNS (sensevoice:9991 等)
#   - 宿主机原生 llama.cpp: 经 host-gateway (extra_hosts 已配)
:80 {
	# === A. API 指南 (api-discover 动态服务: 自动发现 + 健康检查 + 测试) ===
	handle /api-guide {
		redir /api-guide/ permanent
	}
	handle_path /api-guide/* {
		reverse_proxy api-discover:8098
	}

	# === B. 有 web UI 的服务 (/go/<name> → http://{host}:端口) ===
	redir /go/litellm     http://{host}:4000/ui/ permanent
	redir /go/gitea       http://{host}:3002 permanent
	redir /go/files       http://{host}:8085 permanent
	redir /go/search      http://{host}:8087 permanent
	redir /go/comfyui     http://{host}:8188 permanent
	redir /go/asr         http://{host}:9991/docs permanent
	redir /go/tts         http://{host}:8081/docs permanent
	redir /go/notebook    http://{host}:8088 permanent
	redir /go/kuma        http://{host}:3001 permanent
	redir /go/glances     http://{host}:61208 permanent
	redir /go/hermes      http://{host}:9119/login permanent
	redir /go/opensquilla http://{host}:18791/control/ permanent
	redir /go/mineru      http://{host}:8090 permanent
	redir /go/aham        http://{host}:8765 permanent
	redir /go/design      http://{host}:7456 permanent
	redir /go/draw        http://{host}:4733 permanent

	# Fast Research (QUEST-9B 深度研究 web 应用)
	handle_path /research/* {
		reverse_proxy fast-research:8099
	}

	# MetacubeXd — mihomo 代理管理面板 (Nuxt/Nitro server)
	# 用 handle (不剥前缀): Nitro 设了 NUXT_APP_BASE_URL=/metacube/, 需保留前缀匹配路由。
	# 面板连接 mihomo API 时, 后端地址填: http://<host-ip>:9090 + secret
	handle /metacube/* {
		reverse_proxy metacubexd:80
	}
	# /metacube (无尾斜杠) → /metacube/
	redir /metacube /metacube/ permanent

	# Hermes gateway API — ops agent (:8642, 运维 agent)
	# TitanVault AI 助手专用: 管理 docker/systemctl/故障排查, approvals=off
	# 通用对话用户自己开 dashboard (http://<host>:9119)
	# caddy 注入 hermes key, 前端无需自己管鉴权
	handle_path /hermes/* {
		reverse_proxy host-gateway:8642 {
			header_up Authorization "Bearer {$HERMES_API_SERVER_KEY}"
		}
	}
	# LiteLLM API (TitanVault AI 助手对话 + InfPanel 用量数据)
	# titanvault caddy 注入 master key, 前端无需自己管鉴权
	handle_path /llm/* {
		reverse_proxy litellm:4000 {
			header_up Authorization "Bearer {$LITELLM_MASTER_KEY}"
		}
	}
	# 用量统计 (token-usage-api)
	handle_path /usage/* {
		reverse_proxy token-usage-api:8090
	}
	# llama.cpp 指标 (/metrics Prometheus + /slots 缓存状态), 门户 dashboard 用
	handle_path /llm-stats/* {
		reverse_proxy host-gateway:8082
	}
	# Reranker: litellm cohere provider 发 /rerank/v2/rerank, llama.cpp 只有 /v1/rerank
	# caddy 把任意 /rerank/* 重写为 /v1/rerank, 转给宿主机 llama.cpp rerank 服务
	handle /rerank/* {
		rewrite * /v1/rerank
		reverse_proxy host-gateway:8083
	}
	# Glances API 子路径反代 (TitanVault 前端拉真实资源数据用, 避免 CORS)
	handle_path /glances/* {
		reverse_proxy host-gateway:61208
	}

	# === C. 门户门面 ===
	# TitanVault (React 门户, 替代 gethomepage): 兜底默认路由, 所有未匹配的路径走这里。
	# titanvault 容器内 caddy 托管静态文件 + SPA fallback。
	handle {
		reverse_proxy titanvault:3000
	}
}
