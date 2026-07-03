import { useState, useEffect, useRef, useCallback } from "react";
import { svgIcons, services, categoryMeta, catOrder, llmModels, knowledgeBase } from "./data.js";

// =============================================================
// Header
// =============================================================
function Header({ theme, onToggleTheme, onLogoClick, uptime }) {
  return (
    <header className="header">
      <div className="header-inner">
        <div className="header-left">
          <a className="logo-wrap" href="#" onClick={(e) => { e.preventDefault(); onLogoClick(); }}>
            <div className="logo-mark">
              <svg viewBox="0 0 28 32" fill="none" xmlns="http://www.w3.org/2000/svg">
                <defs>
                  <linearGradient id="forgeGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#fbbf24" /><stop offset="50%" stopColor="#f59e0b" /><stop offset="100%" stopColor="#b45309" />
                  </linearGradient>
                  <filter id="forgeGlow" x="-50%" y="-50%" width="200%" height="200%">
                    <feDropShadow dx="0" dy="1" stdDeviation="2.5" floodColor="#f59e0b" floodOpacity="0.4" />
                  </filter>
                </defs>
                <path d="M14 2L2 8v6c0 7 5 12 12 16 7-4 12-9 12-16V8L14 2z" fill="url(#forgeGrad)" filter="url(#forgeGlow)" />
                <path d="M14 9l-4 7h3v5l5-8h-3l1-4z" fill="#fff" opacity="0.9" />
              </svg>
            </div>
            <div className="hostname-block">
              <div className="hostname">TitanVault 天铸</div>
              <div className="hostname-sub">AMD AI MAX 395 · 个人工作站</div>
            </div>
          </a>
        </div>
        <div className="header-right">
          <span className="status-badge">
            <span className="dot"></span>
            <span className="label-text">All systems · {uptime}</span>
          </span>
          <button className="theme-btn" onClick={onToggleTheme} aria-label="切换主题">{theme === "dark" ? "🌙" : "☀️"}</button>
        </div>
      </div>
    </header>
  );
}

// =============================================================
// Spec Modal
// =============================================================
function SpecModal({ open, onClose }) {
  if (!open) return null;
  const specs = [
    { icon: "cpu", label: "处理器", value: "AMD AI MAX 395", detail: "16 核 / 32 线程 · Zen 5 架构" },
    { icon: "gpu", label: "图形处理器", value: "Radeon 8060S", detail: "RDNA 3.5 · 40 CU · 可分配 96GB 显存" },
    { icon: "ram", label: "统一内存", value: "128 GB", detail: "LPDDR5X-8000 · 96GB 可分配显存" },
    { icon: "disk", label: "存储", value: "4 TB", detail: "NVMe PCIe 5.0 SSD" },
    { icon: "net", label: "网络", value: "2.5 GbE + Wi-Fi 7", detail: "有线 · 无线双网接入" },
    { icon: "svc", label: "已部署服务", value: "16+ 个服务", detail: "AI / 应用 / 监控 / Agent · 全部运行中" },
  ];
  return (
    <div className="modal-overlay open" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-box">
        <div className="modal-head">
          <div className="modal-head-left">
            <div className="modal-head-logo">
              <svg viewBox="0 0 28 32" fill="none"><path d="M14 2L2 8v6c0 7 5 12 12 16 7-4 12-9 12-16V8L14 2z" fill="#f59e0b" /><path d="M14 9l-4 7h3v5l5-8h-3l1-4z" fill="#fff" /></svg>
            </div>
            <div className="modal-head-text">
              <div className="modal-head-title">TitanVault 天铸</div>
              <div className="modal-head-sub">AMD AI MAX 395 · 个人 AI 工作站</div>
            </div>
          </div>
          <button className="modal-close-btn" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div className="spec-grid">
            {specs.map((s) => (
              <div className="spec-card" key={s.label}>
                <div className={"spec-card-icon " + s.icon}></div>
                <div className="spec-card-label">{s.label}</div>
                <div className="spec-card-value">{s.value}</div>
                <div className="spec-card-detail">{s.detail}</div>
              </div>
            ))}
            <div className="spec-card full">
              <div className="spec-card-label">操作系统 & 运行时</div>
              <div className="spec-card-value">Ubuntu 26.04 LTS</div>
              <div className="spec-card-detail" style={{ marginTop: 4 }}>Docker · llama.cpp Vulkan · LiteLLM · Python 3.14 · ROCm 7.2</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================
// Resource Strip (CPU/GPU/RAM/Disk + LLM trigger)
// =============================================================
function ResourceStrip({ resources, infOpen, onToggleInf }) {
  const gauges = [
    { key: "cpu", label: "CPU", val: resources.cpu + "%", pct: resources.cpu, cls: "accent", icon: "cpu" },
    { key: "gpu", label: "GPU", val: resources.gpu + "%", pct: resources.gpu, cls: "purple", icon: "gpu" },
    { key: "ram", label: "RAM", val: resources.ramUsed + " GB", pct: resources.ramPct, cls: "success", icon: "ram" },
    { key: "disk", label: "Disk", val: resources.diskUsed + " TB", pct: resources.diskPct, cls: "warn", icon: "disk" },
  ];
  const fillCls = (pct, base) => (pct > 85 ? "danger" : pct > 70 ? "warn" : base);
  return (
    <section className="resource-strip">
      {gauges.map((g) => (
        <div className="res-gauge" key={g.key}>
          <div className={"res-gauge-icon " + g.icon}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              {g.key === "cpu" && <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M20 9h3M1 15h3M20 15h3" /></>}
              {g.key === "gpu" && <><rect x="2" y="5" width="20" height="14" rx="2" /><circle cx="12" cy="12" r="3" /><path d="M16 12h4M4 12h2" /></>}
              {g.key === "ram" && <><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M7 9v6M12 9v6M17 9v6" /></>}
              {g.key === "disk" && <><ellipse cx="12" cy="12" rx="10" ry="10" /><path d="M12 6v6l4 2" /></>}
            </svg>
          </div>
          <div className="res-gauge-body">
            <div className="res-gauge-top"><span className="res-gauge-label">{g.label}</span><span className="res-gauge-val">{g.val}</span></div>
            <div className="res-gauge-track"><div className={"res-gauge-fill " + fillCls(g.pct, g.cls)} style={{ width: g.pct + "%" }}></div></div>
          </div>
        </div>
      ))}
      <div className={"res-gauge llm-trigger" + (infOpen ? " open" : "")} onClick={onToggleInf}>
        <div className="res-gauge-icon" style={{ background: "var(--accent-subtle)", color: "var(--accent)" }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 6v4l3 3" /></svg>
        </div>
        <div className="res-gauge-body">
          <div className="res-gauge-top"><span className="res-gauge-label">LiteLLM 网关</span><span className="res-gauge-val" style={{ color: "var(--accent)" }}>{resources.llmModels} 模型</span></div>
          <div className="llm-preview"><span><span className="num">{resources.llmReqs}</span> / 日</span><span><span className="num">{resources.llmTokens}</span> tok/日</span></div>
        </div>
      </div>
    </section>
  );
}

// =============================================================
// Inference Panel (LLM model table)
// =============================================================
function InfPanel({ open, onClose }) {
  const [data, setData] = useState({ models: [], totals: {}, breakdown: [] });
  const [engine, setEngine] = useState(null);

  useEffect(() => {
    if (!open) return;
    const fetchData = async () => {
      const key = localStorage.getItem("mozin_key") || "";
      try {
        const mr = await fetch("/llm/v1/models", { headers: { Authorization: "Bearer " + key } });
        const md = await mr.json();
        const modelIds = (md.data || []).map((m) => m.id);
        const ur = await fetch("/usage/api/usage");
        const ud = await ur.json();
        const totals = ud.totals || {};
        const breakdown = ud.breakdown || [];
        const usageMap = {};
        breakdown.forEach((b) => {
          const name = (b.group || "").replace(/^openai\//, "").replace(/^deepseek\//, "");
          if (!usageMap[name]) usageMap[name] = { tokens: 0, requests: 0 };
          usageMap[name].tokens += b.total_tokens || 0;
          usageMap[name].requests += b.requests || 0;
        });
        const models = modelIds.map((id) => {
          const u = usageMap[id] || { tokens: 0, requests: 0 };
          const isEmbed = id.toLowerCase().includes("embed");
          return { name: id, provider: isEmbed ? "llama.cpp" : "LiteLLM", type: "local", status: "active", tokens: u.tokens, requests: u.requests };
        });
        setData({ models, totals, breakdown });
      } catch (e) {}
      // llama.cpp 引擎指标
      try {
        const sr = await fetch("/llm-stats/slots");
        const slots = await sr.json();
        const mr2 = await fetch("/llm-stats/metrics");
        const metricsText = await mr2.text();
        const metrics = {};
        metricsText.split("\n").forEach((line) => {
          const m = line.match(/^([a-zA-Z0-9_:]+)\s+([\d.]+)/);
          if (m) metrics[m[1]] = parseFloat(m[2]);
        });
        const busy = slots.filter((s) => s.is_processing).length;
        const totalPrompt = slots.reduce((a, s) => a + (s.n_prompt_tokens || 0), 0);
        const cached = slots.reduce((a, s) => a + (s.n_prompt_tokens_cache || 0), 0);
        const processed = slots.reduce((a, s) => a + (s.n_prompt_tokens_processed || 0), 0);
        setEngine({
          prefillTps: Math.round(metrics["llamacpp:prompt_tokens_seconds"] || 0),
          decodeTps: Math.round(metrics["llamacpp:predicted_tokens_seconds"] || 0),
          promptTotal: Math.round(metrics["llamacpp:prompt_tokens_total"] || 0),
          predictedTotal: Math.round(metrics["llamacpp:tokens_predicted_total"] || 0),
          busySlots: busy,
          totalSlots: slots.length,
          maxCtx: Math.round(metrics["llamacpp:n_tokens_max"] || 0),
          cacheHitRate: totalPrompt > 0 ? Math.round((cached / totalPrompt) * 100) : 0,
          avgBusy: (metrics["llamacpp:n_busy_slots_per_decode"] || 0).toFixed(2),
        });
      } catch (e) {}
    };
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [open]);

  if (!open) return null;
  const t = data.totals;
  const fmt = (n) => n == null ? "—" : n >= 1000000 ? (n / 1000000).toFixed(1) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);
  return (
    <div className="llm-panel open"><div className="llm-panel-inner">
      <div className="llm-panel-header">
        <div className="llm-panel-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 6v4l3 3" /></svg>
          LiteLLM 模型网关 <span className="badge">实时</span>
        </div>
        <button className="llm-panel-close" onClick={onClose}>✕</button>
      </div>
      <div className="llm-summary">
        <div className="llm-summary-item"><div className="value">{data.models.length}</div><div className="label">可用模型</div></div>
        <div className="llm-summary-item"><div className="value">{fmt(t.requests)}</div><div className="label">总请求</div></div>
        <div className="llm-summary-item"><div className="value">{fmt(t.total_tokens)}</div><div className="label">总 Tokens</div></div>
        <div className="llm-summary-item"><div className="value">{fmt(t.completion_tokens)}</div><div className="label">生成 Tokens</div></div>
        <div className="llm-summary-item"><div className="value">{fmt(t.failed_requests)}</div><div className="label">失败请求</div></div>
      </div>
      {engine && (
        <div className="llm-engine-stats">
          <div className="llm-engine-title">⚡ llama.cpp 引擎</div>
          <div className="llm-engine-grid">
            <div className="llm-engine-item"><div className="value" style={{ color: "var(--accent)" }}>{engine.prefillTps}</div><div className="label">prefill tok/s</div></div>
            <div className="llm-engine-item"><div className="value" style={{ color: "var(--accent)" }}>{engine.decodeTps}</div><div className="label">decode tok/s</div></div>
            <div className="llm-engine-item"><div className="value" style={{ color: engine.cacheHitRate > 50 ? "var(--success)" : "var(--fg-muted)" }}>{engine.cacheHitRate}%</div><div className="label">缓存命中</div></div>
            <div className="llm-engine-item"><div className="value">{engine.busySlots}/{engine.totalSlots}</div><div className="label">并发 slot</div></div>
            <div className="llm-engine-item"><div className="value">{engine.avgBusy}</div><div className="label">平均并发</div></div>
            <div className="llm-engine-item"><div className="value">{fmt(engine.promptTotal)}</div><div className="label">累计 prompt</div></div>
            <div className="llm-engine-item"><div className="value">{fmt(engine.predictedTotal)}</div><div className="label">累计生成</div></div>
            <div className="llm-engine-item"><div className="value">{fmt(engine.maxCtx)}</div><div className="label">峰值上下文</div></div>
          </div>
        </div>
      )}
      <div className="llm-table-wrap">
        <table className="llm-table">
          <thead><tr><th>模型</th><th>提供方</th><th>状态</th><th style={{ textAlign: "right" }}>总请求</th><th style={{ textAlign: "right" }}>总 Tokens</th></tr></thead>
          <tbody>
            {data.models.map((m) => (
              <tr key={m.name}>
                <td><span className="model-name">{m.name}<span style={{ fontSize: 10, background: "var(--success-dim)", color: "var(--success)", padding: "1px 6px", borderRadius: 4, marginLeft: 4 }}>本地</span></span></td>
                <td style={{ color: "var(--fg-muted)", fontSize: "var(--text-xs)" }}>{m.provider}</td>
                <td><span className="model-status"><span className="mdot active"></span>在线</span></td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>{m.requests || "—"}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--font-mono)" }}>{fmt(m.tokens)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div></div>
  );
}

// =============================================================
// Search Section
// =============================================================
function SearchBar({ query, setQuery, count }) {
  return (
    <section className="search-section">
      <div className="search-wrap">
        <svg className="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" /></svg>
        <input className="search-input" type="text" placeholder="搜索服务... 名称 / 描述 / 分类 / 端口" autoComplete="off" spellCheck="false" value={query} onChange={(e) => setQuery(e.target.value)} />
        <span className="search-kbd"><kbd>⌘</kbd> <kbd>K</kbd></span>
      </div>
      <div className="search-meta"><span className="count">{query ? `找到 ${count} 个服务` : `${services.length} 个服务`}</span><span style={{ opacity: 0.3 }}>·</span><span>全部正常运行</span></div>
    </section>
  );
}

// =============================================================
// Service Grid
// =============================================================
function ServiceGrid({ query }) {
  const q = query.toLowerCase().trim();
  const filterFn = (s) => !q || s.name.toLowerCase().includes(q) || s.desc.toLowerCase().includes(q) || s.cat.toLowerCase().includes(q) || String(s.port).includes(q);
  return (
    <section className="service-section">
      {catOrder.map((c) => {
        const catServices = services.filter((s) => s.cat === c && filterFn(s));
        if (!catServices.length) return null;
        const meta = categoryMeta[c];
        return (
          <div className="service-category" key={c}>
            <div className="cat-head">
              <div className={"cat-icon " + meta.cls} style={{ background: svgIcons[meta.cls === "ops" ? "kuma" : meta.cls === "app" ? "appgrid" : meta.cls === "agent" ? "hermes" : "comfyui"].color }} dangerouslySetInnerHTML={{ __html: svgIcons[meta.cls === "ops" ? "kuma" : meta.cls === "app" ? "appgrid" : meta.cls === "agent" ? "hermes" : "comfyui"].svg }} />
              <span className="cat-label">{meta.label}</span>
              <span className="cat-count">{catServices.length} 个服务</span>
            </div>
            <div className="service-grid">
              {catServices.map((s) => {
                const ic = svgIcons[s.icon] || svgIcons.homepage;
                return (
                <a className="service-card" key={s.name} href={s.url} target={s.url.startsWith("/go/") || s.url.startsWith("/api-guide/") ? "" : "_blank"} rel="noopener">
                  <div className={"service-card-icon " + meta.cls} style={{ background: ic.color }} dangerouslySetInnerHTML={{ __html: ic.svg }} />
                  <div className="service-card-info">
                    <span className="service-card-name">{s.name}</span>
                    <span className="service-card-port">{s.port > 0 ? ":" + s.port : ""}</span>
                  </div>
                  <span className={"service-card-dot " + s.status}></span>
                </a>
                );
              })}
            </div>
          </div>
        );
      })}
    </section>
  );
}

// =============================================================
// Chat Window (AI Assistant)
// =============================================================
// =============================================================
// 轻量 Markdown 渲染 (无依赖, 防 XSS)
// 支持: 代码块/行内代码/粗体/斜体/标题/列表/链接/引用/换行
// =============================================================
function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function renderInline(text) {
  let s = escapeHtml(text);
  // 行内代码 `code`
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  // 粗体 **text** 或 __text__
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/__([^_]+)__/g, '<strong>$1</strong>');
  // 斜体 *text* 或 _text_ (避免误匹配粗体)
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>').replace(/(^|[^_])_([^_\n]+)_/g, '$1<em>$2</em>');
  // 链接 [text](url)
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  return s;
}
function renderMarkdown(md) {
  if (!md) return "";
  const lines = md.replace(/\r/g, "").split("\n");
  let html = "";
  let i = 0;
  let inList = false, inOl = false;
  const closeLists = () => { if (inList) { html += "</ul>"; inList = false; } if (inOl) { html += "</ol>"; inOl = false; } };
  while (i < lines.length) {
    let line = lines[i];
    // 代码块 ```
    if (/^```/.test(line)) {
      closeLists();
      const lang = line.replace(/^```/, "").trim();
      let code = "";
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) { code += lines[i] + "\n"; i++; }
      i++; // 跳过结束 ```
      html += '<pre data-lang="' + escapeHtml(lang) + '"><code>' + escapeHtml(code.replace(/\n$/, "")) + '</code></pre>';
      continue;
    }
    // 标题
    const hm = line.match(/^(#{1,4})\s+(.*)/);
    if (hm) { closeLists(); const lvl = hm[1].length; html += '<h' + lvl + '>' + renderInline(hm[2]) + '</h' + lvl + '>'; i++; continue; }
    // 引用 >
    if (/^>\s?/.test(line)) { closeLists(); html += '<blockquote>' + renderInline(line.replace(/^>\s?/, "")) + '</blockquote>'; i++; continue; }
    // 有序列表
    if (/^\d+\.\s+/.test(line)) { if (!inOl) { closeLists(); html += '<ol>'; inOl = true; } html += '<li>' + renderInline(line.replace(/^\d+\.\s+/, "")) + '</li>'; i++; continue; }
    // 无序列表 - * +
    if (/^[-*+]\s+/.test(line)) { if (!inList) { closeLists(); html += '<ul>'; inList = true; } html += '<li>' + renderInline(line.replace(/^[-*+]\s+/, "")) + '</li>'; i++; continue; }
    // 空行
    if (line.trim() === "") { closeLists(); i++; continue; }
    // 普通段落
    closeLists();
    html += '<p>' + renderInline(line) + '</p>';
    i++;
  }
  closeLists();
  return html;
}

const SYSTEM_PROMPT = "你是 TitanVault 工作站助手，由 Hermes Agent 驱动。本机搭载 AMD AI MAX 395 (128GB 统一内存)，运行 Qwen3.6-35B-A3B 模型。已部署服务: LiteLLM(LLM网关)、SenseVoice(ASR)、Kokoro(TTS)、MinerU(PDF解析)、ComfyUI(图像生成)、Hermes/OpenSquilla(Agent)、Gitea/SearXNG/Filebrowser 等。简洁专业地回答用户问题。";

function getAnswer(query, history) {
  // 调用 Hermes Agent (经 caddy /hermes/ 反代, caddy 自动注入 key)
  // Hermes 有知识库/工具/记忆能力, 比直连 LiteLLM 更强
  return fetch("/hermes/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "hermes-agent",
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        ...history.map((m) => ({ role: m.role === "ai" ? "assistant" : "user", content: m.text })),
        { role: "user", content: query },
      ],
      max_tokens: 2000,
    }),
  }).then((r) => {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then((d) => {
    return d.choices?.[0]?.message?.content || "（无回复）";
  }).catch((e) => "（Hermes 不可达: " + e.message + "）");
}

const CHAT_STORAGE_KEY = "titanvault_chat_messages";
const INITIAL_MSG = { role: "ai", text: "你好！我是 TitanVault 工作站助手，由 Hermes Agent 驱动。可以问我硬件配置、服务状态、运维操作等。" };

function loadMessages() {
  try {
    const saved = localStorage.getItem(CHAT_STORAGE_KEY);
    if (saved) {
      const arr = JSON.parse(saved);
      if (Array.isArray(arr) && arr.length) return arr;
    }
  } catch (e) {}
  return [INITIAL_MSG];
}

function ChatWindow({ open, onClose }) {
  const [messages, setMessages] = useState(loadMessages);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const bodyRef = useRef(null);

  // 持久化对话历史
  useEffect(() => {
    try { localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages)); } catch (e) {}
  }, [messages]);

  useEffect(() => { if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight; }, [messages, typing]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    setTyping(true);
    try {
      // 先把 user 消息加入, 再带完整历史请求
      const withUser = [...messages, { role: "user", text }];
      setMessages(withUser);
      const reply = await getAnswer(text, messages);
      setTyping(false);
      setMessages([...withUser, { role: "ai", text: reply }]);
    } catch (e) {
      setTyping(false);
      setMessages((m) => [...m, { role: "ai", text: "错误: " + e.message }]);
    }
  }, [input, messages]);

  if (!open) return null;
  return (
    <div className={"chat-window open" + (expanded ? " expanded" : "")}>
      <div className="chat-head">
        <div className="chat-head-left"><div className="chat-head-avatar">AI</div><div className="chat-head-info"><div className="chat-head-title">工作站助手</div><div className="chat-head-sub">AMD AI MAX 395 · 在线</div></div></div>
        <div className="chat-head-actions">
          {messages.length > 1 && (
            <button className="chat-clear-btn" onClick={() => { setMessages([INITIAL_MSG]); }} aria-label="清空对话" title="清空对话">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><line x1="10" y1="11" x2="10" y2="17" /><line x1="14" y1="11" x2="14" y2="17" /></svg>
            </button>
          )}
          <button className="chat-expand-btn" onClick={() => setExpanded((e) => !e)} aria-label="放大" title={expanded ? "缩小" : "放大"}>
            {expanded ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3" /></svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>
            )}
          </button>
          <button className="chat-close-btn" onClick={onClose}>✕</button>
        </div>
      </div>
      <div className="chat-body" ref={bodyRef}>
        {messages.map((m, i) => (
          <div className={"msg " + m.role} key={i}>
            <div className="msg-avatar">{m.role === "ai" ? "AI" : "U"}</div>
            <div className="msg-bubble markdown-body" dangerouslySetInnerHTML={{ __html: m.role === "ai" ? renderMarkdown(m.text) : escapeHtml(m.text) }} />
          </div>
        ))}
        {typing && <div className="msg ai"><div className="msg-avatar">AI</div><div className="msg-bubble"><div className="typing-indicator"><span></span><span></span><span></span></div></div></div>}
      </div>
      <div className="chat-foot">
        <input className="chat-input" type="text" placeholder="询问工作站能力..." value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <button className="chat-send" disabled={!input.trim()} onClick={send}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 2 11 13" /><path d="M22 2l-7 20-4-9-9-4 20-7z" /></svg></button>
      </div>
    </div>
  );
}

// =============================================================
// Main App
// =============================================================
export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("ai-station-theme") || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  const [query, setQuery] = useState("");
  const [specOpen, setSpecOpen] = useState(false);
  const [infOpen, setInfOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [resources, setResources] = useState({ cpu: 0, gpu: 0, ramPct: 0, ramUsed: "0", diskPct: 0, diskUsed: "0", llmModels: "—", llmReqs: "—", llmTokens: "—" });
  const [uptime, setUptime] = useState("—");

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); localStorage.setItem("ai-station-theme", theme); }, [theme]);
  useEffect(() => { document.body.classList.toggle("chat-open", chatOpen); }, [chatOpen]);

  // 从 Glances API 拉真实资源数据 (CPU/MEM/DISK/GPU) + LiteLLM 用量
  useEffect(() => {
    const fetchAll = async () => {
      // 资源数据
      try {
        const resp = await fetch("/glances/api/4/all");
        const d = await resp.json();
        const cpu = Math.round(d.cpu?.total || 0);
        const memPct = Math.round(d.mem?.percent || 0);
        const memUsed = ((d.mem?.used || 0) / 1073741824).toFixed(1);
        const fs = d.fs?.[0] || {};
        const diskPct = Math.round(fs.percent || 0);
        const diskUsed = ((fs.used || 0) / 1099511627776).toFixed(1);
        const gpu = d.gpu?.[0];
        const gpuPct = gpu ? (gpu.proc || gpu.mem || 0) : 0;
        setResources((prev) => ({ ...prev, cpu, gpu: gpuPct, ramPct: memPct, ramUsed: memUsed, diskPct, diskUsed }));
        // uptime: "5 days, 2:26:35" -> "5d 02:26"
        const up = d.uptime || "";
        const m = up.match(/(?:(\d+)\s*days?,?\s*)?(\d+):(\d+):(\d+)/);
        if (m) {
          const days = m[1] ? parseInt(m[1]) + "d " : "";
          const hh = String(m[2]).padStart(2, "0");
          const mm = String(m[3]).padStart(2, "0");
          setUptime(days + hh + ":" + mm);
        }
        else setUptime(up);
      } catch (e) {}
      // LiteLLM 用量
      try {
        const resp = await fetch("/usage/api/usage");
        const d = await resp.json();
        const t = d.totals || {};
        setResources((prev) => ({
          ...prev,
          llmReqs: t.requests != null ? t.requests : "—",
          llmTokens: t.total_tokens != null ? (t.total_tokens >= 1000000 ? (t.total_tokens / 1000000).toFixed(1) + "M" : t.total_tokens >= 1000 ? (t.total_tokens / 1000).toFixed(0) + "k" : t.total_tokens) : "—",
        }));
      } catch (e) {}
      // LiteLLM 模型数
      try {
        const resp = await fetch("/llm/v1/models", { headers: { Authorization: "Bearer " + (localStorage.getItem("mozin_key") || "") } });
        const d = await resp.json();
        setResources((prev) => ({ ...prev, llmModels: String(d.data?.length || 0) }));
      } catch (e) {}
    };
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, []);

  // 快捷键
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); document.querySelector(".search-input")?.focus(); }
      if (e.key === "Escape") { setSpecOpen(false); setChatOpen(false); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  return (
    <>
      <Header theme={theme} onToggleTheme={() => setTheme((t) => t === "dark" ? "light" : "dark")} onLogoClick={() => setSpecOpen(true)} uptime={uptime} />
      <SpecModal open={specOpen} onClose={() => setSpecOpen(false)} />
      <main className="app-shell">
        <SearchBar query={query} setQuery={setQuery} count={services.filter((s) => { const q = query.toLowerCase(); return !q || s.name.toLowerCase().includes(q) || s.desc.toLowerCase().includes(q); }).length} />
        <ResourceStrip resources={resources} infOpen={infOpen} onToggleInf={() => setInfOpen((o) => !o)} />
        <InfPanel open={infOpen} onClose={() => setInfOpen(false)} />
        <ServiceGrid query={query} />
      </main>
      <button className="fab-edge" onClick={() => setChatOpen(true)} aria-label="AI 助手"><span className="edge-indicator"></span><span className="edge-label">AI 助手</span></button>
      <ChatWindow open={chatOpen} onClose={() => setChatOpen(false)} />
    </>
  );
}
