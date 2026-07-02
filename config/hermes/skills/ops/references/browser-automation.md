# browser-use 浏览器自动化 (数字员工能力)

## 架构

```
Hermes (cron/skill 编排)
  └─ browser toolset → browser-use (browser-harness 0.1.4)
                       └─ CDP 连接 → Chrome headless (chrome-cdp.service :9222)
                                     └─ 操作页面: 点击/填表/导航/截图/JS
```

- **chrome-cdp.service**: Google Chrome 150 headless + CDP remote-debugging (:9222)
- **browser-use**: 装在 Hermes venv (/opt/hermes/.venv), 经 CDP 连接 Chrome
- **profile 持久化**: /data/browser-use/chrome-profile (cookie/localStorage 跨重启保留, 内部系统登录态)

## 关键环境变量

```bash
BH_CHROME_PATH=/usr/bin/google-chrome-stable  # 必须用 .deb 版, snap chromium 不兼容 CDP
```

## 运维命令

```bash
# Chrome CDP 状态
sudo systemctl status chrome-cdp
curl -sf http://127.0.0.1:9222/json/version  # 应返回 Chrome 版本 JSON

# browser-use 诊断
BH_CHROME_PATH=/usr/bin/google-chrome-stable /opt/hermes/.venv/bin/browser-use --doctor

# 手动测试浏览器操作 (导航 + 读标题)
BH_CHROME_PATH=/usr/bin/google-chrome-stable /opt/hermes/.venv/bin/browser-use <<'PY'
new_tab("https://example.com")
wait_for_load()
print(page_info().get("title"))
PY

# 让 Hermes 直接操作浏览器
hermes -p ops -z "用 browser-use 导航到 http://内部系统地址，截图" --cli
```

## browser-use API (注入到 heredoc 的函数)

| 函数 | 用途 |
|---|---|
| `new_tab(url)` | 打开新标签页导航到 url |
| `goto_url(url)` | 当前标签页导航 |
| `page_info()` | 读页面信息 (title/url/尺寸) |
| `click_at_xy(x, y)` | 点击坐标 |
| `type_text(text)` | 输入文字 (需先点击输入框) |
| `press_key(key)` | 按键 (Enter/Tab/Escape 等) |
| `fill_input(selector, text)` | 填表 (CSS selector) |
| `js(code)` | 执行 JavaScript |
| `capture_screenshot(path=None, full=False, max_dim=None)` | 截图,返回 PNG 文件路径(非 base64!) |
| `wait_for_load()` | 等页面加载 |
| `wait_for_element(...)` | 等元素出现 |
| `scroll(dx, dy)` | 滚动 |
| `list_tabs()` / `switch_tab(tab_dict)` | 标签页管理 (多 tab 时先 switch_tab 再操作) |

### 截图 + 视觉识别 (验证码/页面理解)

`capture_screenshot` 返回文件路径,需手动读文件转 base64 发给 Qwen3.6:

```python
import base64, json, urllib.request
# 全页截图 (full=True 包含滚动区域外的内容)
shot = capture_screenshot(path="/tmp/page.png", full=True)
with open(shot, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

# 发给 Qwen3.6 视觉识别 (经 LiteLLM)
payload = {"model":"Qwen3.6-35B-A3B","messages":[{"role":"user","content":[
    {"type":"text","text":"读这张验证码图片上的文字"},
    {"type":"image_url","image_url":{"url":f"data:image/png;base64,{b64}"}}
]}],"max_tokens":50}
# POST 到 http://litellm:4000/v1/chat/completions (容器内) 或 http://localhost:4000 (宿主)
```

**viewport 注意**: headless Chrome 默认 viewport 可能小于页面(如 780×493),
固定布局的右侧表单可能不在截图内。用 `full=True` 截全页解决;或用 `js()`
读元素坐标后 `click_at_xy` 直接操作(不依赖截图可见)。

## 典型场景: 操作内部系统

用 Hermes cron 定时 + skill 封装:

```bash
# 示例: 每天登录 OA 系统下载考勤报表
hermes cron add "每天 9:00 登录 OA 系统下载考勤报表" --channel webhook
# Hermes 会自动: 用 browser-use 导航→登录(复用 profile cookie)→点击下载→保存文件→通知
```

## 常见问题

- **"chrome running [FAIL]"**: chrome-cdp.service 没起, `sudo systemctl start chrome-cdp`
- **snap chromium 冲突**: snap 版 chromium 不兼容 CDP, 必须用 google-chrome-stable (.deb)
- **登录态丢失**: 检查 /data/browser-use/chrome-profile 目录权限和持久化
- **页面渲染慢**: headless Chrome 无 GPU, 复杂页面可能慢; 增加 wait_for_load() 等待
