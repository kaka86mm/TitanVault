# native/chrome-cdp/chrome-cdp.service.tpl
# Google Chrome headless + CDP remote debugging (供 browser-use / Hermes 浏览器自动化)。
#
# 为什么原生而非容器: browser-use (browser-harness) 经 CDP 连接本机 Chrome,
# 容器化收益为负 (Chrome 需访问宿主网络/内部系统, 容器网络隔离反而碍事)。
# Hermes 作为 browser-use 的调用方, 直接调宿主机 Chrome 最干净。
#
# install.sh Phase 5 用 envsubst 渲染: ${DEPLOY_USER} / ${DATA_DIR}
# 端口 9222: browser-use daemon 经 http://127.0.0.1:9222 连接 Chrome DevTools。
[Unit]
Description=Google Chrome Headless (CDP :9222, 供 browser-use 浏览器自动化)
After=network.target

[Service]
Type=simple
User=${DEPLOY_USER}
Group=${DEPLOY_USER}
Environment=BH_CHROME_PATH=/usr/bin/google-chrome-stable
# 清 SingletonLock: Chrome 非正常退出后遗留锁文件, 下次启动检测到就拒绝 (exit 21)
# 手动 browser-use daemon 启动的 Chrome 也会留锁。ExecStartPre 每次启动前清掉。
ExecStartPre=/bin/rm -f ${DATA_DIR}/browser-use/chrome-profile/SingletonLock
# --headless=new    新版 headless 模式 (Chrome 112+, 支持 CDP)
# --remote-debugging-port=9222  CDP 端口 (browser-use daemon 连此)
# --no-sandbox      headless 无需 sandbox (非 root 用户下 Chrome 要求)
# --disable-gpu     headless 不需要 GPU (页面渲染走 SwiftShader)
# --user-data-dir   持久化 profile (cookie/localStorage, 内部系统登录态保留)
ExecStart=/usr/bin/google-chrome-stable \
    --headless=new \
    --remote-debugging-port=9222 \
    --remote-debugging-address=127.0.0.1 \
    --no-sandbox \
    --disable-gpu \
    --disable-dev-shm-usage \
    --window-size=1280,1024 \
    --user-data-dir=${DATA_DIR}/browser-use/chrome-profile \
    about:blank
Restart=always
RestartSec=5
# Chrome headless 内存占用适中 (~500MB), 不需特殊超时
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
