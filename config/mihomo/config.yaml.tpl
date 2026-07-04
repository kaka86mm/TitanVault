# config/mihomo/config.yaml.tpl
# mihomo 代理配置骨架。
#
# 无订阅时 = 直连模式: 所有流量走 DIRECT。
# 有订阅时: install.sh Phase 1 用 MIHOMO_SUBSCRIBE_URL 渲染下面的 proxy-providers。
#
# 订阅格式: 此订阅返回完整 Clash 配置 (含 proxies/groups/rules),
# mihomo 的 proxy-providers 只提取其中的 proxies 节点列表, groups/rules 由本文件自建,
# 这样 metacubexd 面板能自由切换/测速, 且 external-controller 配置不被订阅覆盖。

mixed-port: 7890
# allow-lan=true 让 mihomo 监听 0.0.0.0, 使 docker bridge 容器 (searxng 等) 能通过
# host-gateway:7890 走代理。host 网络模式下无安全风险 (不暴露到物理网络)。
allow-lan: true
bind-address: "*"   # 监听所有接口
mode: rule
log-level: info
ipv6: false

# RESTful API (供 metacubexd 面板管理)。
# mihomo 是 host 网络模式, 0.0.0.0:9090 直接监听宿主端口, 内网/bridge 容器可访问。
external-controller: 0.0.0.0:9090
# API 鉴权密钥 (install.sh 自动生成), metacubexd 连接时需填此 secret。
secret: "${MIHOMO_API_SECRET}"

# ============================================================================
# 订阅节点 (proxy-providers)
# ============================================================================
# type: file 引用本地节点文件 (subscribe-provider.yaml)。
# 文件由 install.sh 用 MIHOMO_SUBSCRIBE_URL 拉取订阅后提取 proxies 段生成。
# 换订阅: 重新拉取订阅覆盖 subscribe-provider.yaml, mihomo 自动热加载。
proxy-providers:
  subscribe:
    type: file
    path: ./subscribe-provider.yaml
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 300

# ============================================================================
# 代理组
# ============================================================================
proxy-groups:
  # 主入口: 手动选择走哪个子组
  - name: 🚀 节点选择
    type: select
    proxies:
      - ♻️ 自动选择
      - 🇭🇰 香港
      - 🇯🇵 日本
      - 🇸🇬 新加坡
      - 🇨🇳 台湾
      - 🇺🇸 美国
      - DIRECT

  # 自动测速选最快 (按延迟)
  - name: ♻️ 自动选择
    type: url-test
    use:
      - subscribe
    url: https://www.gstatic.com/generate_204
    interval: 300
    tolerance: 50

  # 按地区分组 (filter 正则匹配节点名)
  - name: 🇭🇰 香港
    type: url-test
    use:
      - subscribe
    filter: "(?i)香港|HK|Hong Kong"
    url: https://www.gstatic.com/generate_204
    interval: 300

  - name: 🇯🇵 日本
    type: url-test
    use:
      - subscribe
    filter: "(?i)日本|JP|Japan"
    url: https://www.gstatic.com/generate_204
    interval: 300

  - name: 🇸🇬 新加坡
    type: url-test
    use:
      - subscribe
    filter: "(?i)新加坡|SG|Singapore"
    url: https://www.gstatic.com/generate_204
    interval: 300

  - name: 🇨🇳 台湾
    type: url-test
    use:
      - subscribe
    filter: "(?i)台湾|TW|Taiwan"
    url: https://www.gstatic.com/generate_204
    interval: 300

  - name: 🇺🇸 美国
    type: url-test
    use:
      - subscribe
    filter: "(?i)美国|US|United States"
    url: https://www.gstatic.com/generate_204
    interval: 300

# ============================================================================
# 分流规则 (从上到下匹配, 先到先得)
# ============================================================================
rules:
  # 本地/内网直连
  - IP-CIDR,127.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,10.0.0.0/8,DIRECT,no-resolve
  - IP-CIDR,172.16.0.0/12,DIRECT,no-resolve
  - IP-CIDR,192.168.0.0/16,DIRECT,no-resolve
  - IP-CIDR,100.64.0.0/10,DIRECT,no-resolve

  # 国内 IP/域名直连 (需要 geoip 数据库; 首次启动代理通了后由 mihomo 自动下载)
  # - GEOIP,CN,DIRECT,no-resolve

  # 其余走代理
  - MATCH,🚀 节点选择
