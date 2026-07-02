# native/opensquilla/opensquilla.service.tpl
# OpenSquilla Gateway Server (:18791)
#
# install.sh Phase 5 用 envsubst 渲染: ${DEPLOY_USER}/${DATA_DIR} 来自 .env。
# 原生 systemd 服务 (非容器), OpenSquilla 拥有完整宿主机能力 (git/build/文件系统)。
# 用于写代码/改项目源码: 能直接读写 ~/Mozin-workstation 等项目目录。
[Unit]
Description=OpenSquilla Agent Gateway (:18791)
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
# HOME 指向 opensquilla 数据目录 (config.toml/workspace 都在这)
Environment=HOME=${DATA_DIR}/opensquilla
WorkingDirectory=${DATA_DIR}/opensquilla
ExecStart=/opt/opensquilla/.venv/bin/opensquilla gateway run --port 18791
Restart=always
RestartSec=5
TimeoutStartSec=60

[Install]
WantedBy=multi-user.target
