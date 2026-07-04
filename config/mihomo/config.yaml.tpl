# config/mihomo/config.yaml.tpl
# mihomo 代理配置骨架。
#
# 无订阅时 = 直连模式: mihomo 仅作透明代理, 所有流量走 DIRECT, 不影响其余服务。
# 有订阅时: install.sh Phase 1 用 MIHOMO_SUBSCRIBE_URL 拉取订阅, 替换下面 proxies/rules。
mixed-port: 7890
allow-lan: false
mode: rule
log-level: info

# RESTful API (供 metacubexd 面板管理)。
# mihomo 是 host 网络模式, 0.0.0.0:9090 直接监听宿主端口, 内网/bridge 容器可访问。
external-controller: 0.0.0.0:9090
# API 鉴权密钥 (install.sh 自动生成), metacubexd 连接时需填此 secret。
secret: "${MIHOMO_API_SECRET}"

# 订阅内容由 install.sh 填充 (取消下面注释并替换 URL):
# proxy-providers:
#   subscribe:
#     type: http
#     url: ${MIHOMO_SUBSCRIBE_URL}
#     interval: 86400
#     path: ./proxy-provider.yaml
#     health-check:
#       enable: true
#       url: https://www.gstatic.com/generate_204
#       interval: 300

# 无订阅: 直连模式
proxies: []
proxy-groups:
  - name: DIRECT-ONLY
    type: select
    proxies:
      - DIRECT
rules:
  - MATCH,DIRECT-ONLY
