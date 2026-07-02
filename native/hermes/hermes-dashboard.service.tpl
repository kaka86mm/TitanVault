# native/hermes/hermes-dashboard.service.tpl
# Hermes Agent Dashboard (Web UI, :9119)
#
# install.sh Phase 5 用 envsubst 渲染: ${DEPLOY_USER} 来自 .env。
# 原生 systemd 服务 (非容器), Hermes 拥有完整宿主机能力 (docker/systemctl/网络)。
#
# 为什么原生: Hermes 是运维 agent, 需直接管理 Docker 容器、读文件系统、
# 访问宿主机网络。容器化需挂 docker.sock 等绕路, 原生天然拥有全部能力。
[Unit]
Description=Hermes Agent Dashboard (:9119)
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
# HOME 指向 hermes 数据目录 (config.yaml/skills/memories 都在这)
Environment=HOME=${DATA_DIR}/hermes
# browser-use (browser-harness) 需要 BH_CHROME_PATH 指向 .deb 版 Chrome (非 snap)
Environment=BH_CHROME_PATH=/usr/bin/google-chrome-stable
WorkingDirectory=${DATA_DIR}/hermes
ExecStart=/opt/hermes/.venv/bin/hermes dashboard --host 0.0.0.0 --port 9119 --no-open --insecure
Restart=always
RestartSec=5
# dashboard 启动需加载 skills/memories, 给足时间
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
