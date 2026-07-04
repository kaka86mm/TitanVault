# Agent Reach — AI Agent 互联网能力层

[Agent Reach](https://github.com/Panniantong/Agent-Reach) 给 AI agent 装上读推特/Reddit/YouTube/小红书/B站等 15 个平台的能力。
本工作站通过 mihomo 代理访问国外平台,deep-research 集成了 Jina Reader 作为网页阅读后端。

## 已安装渠道

| 渠道 | 后端 | 状态 | 说明 |
|------|------|------|------|
| 全网语义搜索 | Exa (mcporter) | ✅ 可用 | 免费,无需 API key |
| 任意网页 | Jina Reader | ✅ 可用 | deep-research 已集成 (JS 渲染页面) |
| YouTube | yt-dlp | ✅ 可用 | 视频信息+字幕 |
| V2EX | 公开 API | ✅ 可用 | 节点/主题/回复 |
| RSS/Atom | feedparser | ✅ 可用 | 订阅源 |
| B站 | 搜索 API | ✅ 可用 | 仅搜索 |
| 小红书 | xiaohongshu-mcp | ⚠️ 需扫码 | systemd 服务 :18060,首次需扫码登录 |
| Twitter/X | twitter-cli | ⚠️ 需 cookie | twitter-cli v0.8.5,需 TWITTER_AUTH_TOKEN + TWITTER_CT0 |

## 安装位置 (1.7)

```
agent-reach venv:     /data/agent-reach-venv
agent-reach skill:    /home/matri/.agents/skills/agent-reach/
twitter-cli:          ~/.local/bin/twitter (pipx)
mcporter:             /usr/bin/mcporter (npm global)
mcporter config:      ~/config/mcporter.json
xiaohongshu-mcp:      /data/xhs-mcp/xiaohongshu-mcp-linux-amd64
xiaohongshu systemd:  xiaohongshu-mcp.service (:18060)
```

## 常用命令

```bash
# 体检 (看各渠道状态)
source /data/agent-reach-venv/bin/activate
agent-reach doctor
agent-reach doctor --json   # 机器可读

# Exa 语义搜索
mcporter call 'exa.web_search_exa(query: "Vulkan LLM", numResults: 5)'

# 小红书 (需先扫码登录)
mcporter call 'xiaohongshu.check_login_status()' --timeout 120000
mcporter call 'xiaohongshu.get_login_qrcode()' --timeout 120000
mcporter call 'xiaohongshu.search_feeds(keyword: " query")' --timeout 120000

# Twitter (需 cookie)
twitter feed -n 20              # 时间线
twitter tweet URL_OR_ID         # 读推文
twitter user-posts @user -n 20  # 用户时间线
```

## 解锁需登录的渠道

### Twitter/X

需要从浏览器提取 cookie:

1. 用 Chrome 登录 x.com
2. F12 → Application → Cookies → `https://x.com`
3. 找 `auth_token` 和 `ct0` 两个 cookie 的值
4. 写入环境变量:

```bash
# 临时
export TWITTER_AUTH_TOKEN="你的auth_token值"
export TWITTER_CT0="你的ct0值"

# 持久 (写入 ~/.bashrc)
echo 'export TWITTER_AUTH_TOKEN="xxx"' >> ~/.bashrc
echo 'export TWITTER_CT0="yyy"' >> ~/.bashrc
```

验证: `twitter status` 应返回 `ok: true`

### 小红书

xiaohongshu-mcp 服务已跑在 :18060 (systemd 管理),需扫码登录:

```bash
# 获取二维码 (SSH 终端会显示字符画二维码, 或在桌面环境直接看)
mcporter call 'xiaohongshu.get_login_qrcode()' --timeout 120000

# 用小红书 App 扫码
# 登录后 cookies 保存在 /data/xhs-mcp/cookies.json, 重启不丢
```

> SSH 远程扫码不便时:在本地电脑跑 xiaohongshu-login 登录后,
> 把生成的 `cookies.json` 复制到 `/data/xhs-mcp/cookies.json`,重启服务即可。

## deep-research 集成

deep-research 已集成 **Jina Reader** (任意网页渠道):
- JS 重度站点 (twitter/reddit/medium/zhihu/b站) → 直接走 Jina Reader
- 普通站点 trafilatura 失败 → fallback Jina Reader
- visit/verify_url 走 mihomo 代理访问国外页面

Exa/Twitter/小红书 作为 agent-reach skill 能力,供 **Hermes agent** (宿主直接跑) 使用。
deep-research 不直接集成它们 (需 MCP 桥接, 边际价值低于 SearXNG+Jina 组合)。

## 代理

所有渠道通过 mihomo 代理 (host 模式 :7890) 访问国外平台:

```bash
export https_proxy=http://localhost:7890
export http_proxy=http://localhost:7890
```

已写入 `~/.bashrc`。mihomo 配置见 `config/mihomo/config.yaml.tpl`。
