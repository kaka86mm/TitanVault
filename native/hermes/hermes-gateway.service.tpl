# native/hermes/hermes-gateway.service.tpl
# Hermes Agent Gateway API Server — Ops Profile (运维 agent, :8642)
#
# 双 agent 架构: ops (运维, :8642) + default (通用, :8643)
# ops agent: 管理容器/systemd/故障排查, approvals=off 全自动
# -p ops 指定使用 ops profile (独立 SOUL.md/skills/config)
[Unit]
Description=Hermes Agent Gateway - Ops (运维, :8642)
After=network.target hermes-dashboard.service chrome-cdp.service

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
Environment=HOME=${DATA_DIR}/hermes
# browser-use (browser-harness) 需要 BH_CHROME_PATH 指向 .deb 版 Chrome (非 snap)
# 否则 snap chromium 优先被找到, CDP 不通, browser toolset 报错
Environment=BH_CHROME_PATH=/usr/bin/google-chrome-stable
WorkingDirectory=${DATA_DIR}/hermes
ExecStart=/opt/hermes/.venv/bin/hermes -p ops gateway run --replace
Restart=always
RestartSec=5
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
