// 服务数据 + 图标 + 配置数据
// 彩色品牌图标: { color: 背景色, svg: 白色图标 }
// 有官方 logo 的用真实品牌形状+品牌色; 其余用功能性彩色图标

export const svgIcons = {
  mineru: { color: "#E8554E", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/></svg>` },
  aham: { color: "#9B59D0", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="19" x2="12" y2="22"/></svg>` },
  comfyui: { color: "#7C3AED", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><path d="M10 6.5h4M6.5 10v4M17.5 10v4M10 17.5h4"/></svg>` },
  gitea: { color: "#609926", svg: `<svg viewBox="0 0 24 24" fill="#fff"><path d="M4.209 4.603c-.247 0-.525.02-.84.088-.333.07-1.28.283-2.054 1.027C-.403 7.25.035 9.685.089 10.052c.065.446.263 1.687 1.21 2.768 1.749 2.141 5.513 2.092 5.513 2.092s.462 1.103 1.168 2.119c.955 1.263 1.936 2.248 2.89 2.367 2.406 0 7.212-.004 7.212-.004s.458.004 1.08-.394c.535-.324 1.013-.893 1.013-.893s.492-.527 1.18-1.73c.21-.37.385-.729.538-1.068 0 0 2.107-4.471 2.107-8.823-.042-1.318-.367-1.55-.443-1.627-.156-.156-.366-.153-.366-.153s-4.475.252-6.792.306c-.508.011-1.012.023-1.512.027v4.474l-.634-.301c0-1.39-.004-4.17-.004-4.17-1.107.016-3.405-.084-3.405-.084s-5.399-.27-5.987-.324c-.187-.011-.401-.032-.648-.032zm.354 1.832h.111s.271 2.269.6 3.597C5.549 11.147 6.22 13 6.22 13s-.996-.119-1.641-.348c-.99-.324-1.409-.714-1.409-.714s-.73-.511-1.096-1.52C1.444 8.73 2.021 7.7 2.021 7.7s.32-.859 1.47-1.145c.395-.106.863-.12 1.072-.12zm8.33 2.554c.26.003.509.127.509.127l.868.422-.529 1.075a.686.686 0 0 0-.614.359.685.685 0 0 0 .072.756l-.939 1.924a.69.69 0 0 0-.66.527.687.687 0 0 0 .347.763.686.686 0 0 0 .867-.206.688.688 0 0 0-.069-.882l.916-1.874a.667.667 0 0 0 .237-.02.657.657 0 0 0 .271-.137 8.826 8.826 0 0 1 1.016.512.761.761 0 0 1 .286.282c.073.21-.073.569-.073.569-.087.29-.702 1.55-.702 1.55a.692.692 0 0 0-.676.477.681.681 0 1 0 1.157-.252c.073-.141.141-.282.214-.431.19-.397.515-1.16.515-1.16.035-.066.218-.394.103-.814-.095-.435-.48-.638-.48-.638-.467-.301-1.116-.58-1.116-.58s0-.156-.042-.27a.688.688 0 0 0-.148-.241l.516-1.062 2.89 1.401s.48.218.583.619c.073.282-.019.534-.069.657-.24.587-2.1 4.317-2.1 4.317s-.232.554-.748.588a1.065 1.065 0 0 1-.393-.045l-.202-.08-4.31-2.1s-.417-.218-.49-.596c-.083-.31.104-.691.104-.691l2.073-4.272s.183-.37.466-.497a.855.855 0 0 1 .35-.077z"/></svg>` },
  appgrid: { color: "#8B5CF6", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>` },
  filebrowser: { color: "#3B82F6", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>` },
  searxng: { color: "#3050FF", svg: `<svg viewBox="0 0 24 24" fill="#fff"><path d="m13.716 17.261 6.873 6.582L24 20.282l-6.824-6.536a9.11 9.11 0 0 0 1.143-4.43c0-5.055-4.105-9.159-9.16-9.159S0 4.261 0 9.316c0 5.055 4.104 9.159 9.159 9.159a9.11 9.11 0 0 0 4.557-1.214ZM9.159 2.773a6.546 6.546 0 0 1 6.543 6.543 6.545 6.545 0 0 1-6.543 6.542 6.545 6.545 0 0 1-6.542-6.542 6.545 6.545 0 0 1 6.542-6.543ZM7.26 5.713a4.065 4.065 0 0 1 4.744.747 4.064 4.064 0 0 1 .707 4.749l1.157.611a5.376 5.376 0 0 0-.935-6.282 5.377 5.377 0 0 0-6.274-.987l.601 1.162Z"/></svg>` },
  notebook: { color: "#0891B2", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><polyline points="9 7 12 10 9 13"/></svg>` },
  kuma: { color: "#5CDD8B", svg: `<svg viewBox="0 0 24 24" fill="#fff"><path d="M11.759.955c-4.071 0-7.93 2.265-10.06 5.774l-.16.263-.116.284c-1.81 4.44-2.188 9.118.621 12.459 2.67 3.174 6.221 3.328 9.477 3.308 3.256-.02 6.323-.482 8.995-2.032C22.75 19.714 24 16.917 24 14.53c0-2.388-.724-4.698-1.882-7.343l-.112-.257-.148-.238C19.683 3.2 15.83.955 11.758.955Zm0 3.868c2.919 0 5.19 1.305 6.816 3.914 2.076 4.747 2.076 7.724 0 8.929-3.116 1.808-11.234 2.359-13.57-.42-1.558-1.853-1.558-4.69 0-8.51 1.584-2.608 3.835-3.913 6.754-3.913z"/></svg>` },
  glances: { color: "#D9C38C", svg: `<svg viewBox="0 0 24 24" fill="#fff"><path d="M2.77 0A2.763 2.763 0 0 0 0 2.77v18.46A2.763 2.763 0 0 0 2.77 24h18.46A2.763 2.763 0 0 0 24 21.23V2.77A2.763 2.763 0 0 0 21.23 0Zm.922 1.846h5.539c1.023 0 1.846.824 1.846 1.846v16.616a1.842 1.842 0 0 1-1.846 1.846H3.692a1.842 1.842 0 0 1-1.846-1.846V3.692c0-1.022.824-1.846 1.846-1.846zm11.077 0h5.539c1.022 0 1.846.824 1.846 1.846v5.539a1.842 1.842 0 0 1-1.846 1.846h-5.539a1.842 1.842 0 0 1-1.846-1.846V3.692c0-1.022.823-1.846 1.846-1.846zm1.226 1.846-.946.961h2.964c.148 0 .29-.005.423-.012a.78.78 0 0 0 .312-.089L14.77 8.528l.725.703 3.923-3.941a1.031 1.031 0 0 0-.1.322 3.265 3.265 0 0 0-.023.38v3.071l1.014-1.004V3.692Zm-1.226 9.231h5.539c1.022 0 1.846.823 1.846 1.846v5.539a1.842 1.842 0 0 1-1.846 1.846h-5.539a1.842 1.842 0 0 1-1.846-1.846v-5.539c0-1.023.823-1.846 1.846-1.846z"/></svg>` },
  hermes: { color: "#0091CD", svg: `<svg viewBox="0 0 24 24" fill="#fff"><path d="m21.818 4.516-1.05 4.148h2.175L24 4.516M19.41 14.04h2.17l1.04-4.08h-2.178m-2.41 9.523h2.154l1.056-4.147h-2.16m.193-5.377H5.55v.92l3.341 3.161h9.349m2.41-9.525H0v1.116l3.206 3.032H19.6m-8.372 7.58 3.43 3.24h2.205l1.05-4.147h-6.685"/></svg>` },
  opensquilla: { color: "#F59E0B", svg: `<svg viewBox="0 0 24 24" fill="#fff"><path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 16.8 5.8 21.3l2.4-7.4L2 9.4h7.6z"/></svg>` },
  opendesign: { color: "#EC4899", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18"/><circle cx="12" cy="12" r="3.5" fill="#fff" stroke="none"/></svg>` },
  nextdraw: { color: "#06B6D4", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17.5C5 15 8 13 12 13s7 2 9 4.5"/><path d="M3 12.5C5 10 8 8 12 8s7 2 9 4.5"/><path d="M3 7.5C5 5 8 3 12 3s7 2 9 4.5"/></svg>` },
  litellm: { color: "#10B981", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L3 7v10l9 5 9-5V7z"/><path d="M12 2v20M3 7l9 5 9-5"/></svg>` },
  homepage: { color: "#64748B", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>` },
  api: { color: "#6366F1", svg: `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 18 23 12 17 6"/><polyline points="7 6 1 12 7 18"/><line x1="14" y1="4" x2="10" y2="20"/></svg>` },
};

export const services = [
  { name: 'MinerU Web',  icon: 'mineru',    desc: 'PDF 解析',                  port: 8090,  url: '/go/mineru',  status: 'up', cat: 'AI' },
  { name: 'Aham Voice',  icon: 'aham',      desc: '录音转写+会议纪要',          port: 8765,  url: '/go/aham',   status: 'up', cat: 'AI' },
  { name: 'ComfyUI',     icon: 'comfyui',   desc: 'SD 图像生成',                port: 8188,  url: '/go/comfyui', status: 'up', cat: 'AI' },
  { name: 'Gitea',       icon: 'gitea',     desc: '自托管 Git',                 port: 3002,  url: '/go/gitea',  status: 'up', cat: 'App' },
  { name: 'Filebrowser', icon: 'filebrowser', desc: '文件管理',                 port: 8085,  url: '/go/files',  status: 'up', cat: 'App' },
  { name: 'SearXNG',     icon: 'searxng',   desc: '元搜索',                     port: 8087,  url: '/go/search', status: 'up', cat: 'App' },
  { name: 'Open Notebook', icon: 'notebook', desc: '知识库',                   port: 8088,  url: '/go/notebook', status: 'up', cat: 'App' },
  { name: 'uptime-kuma', icon: 'kuma',      desc: '服务监控+告警',              port: 3001,  url: '/go/kuma',   status: 'up', cat: 'Ops' },
  { name: 'Glances',     icon: 'glances',   desc: '系统监控',                   port: 61208, url: '/go/glances', status: 'up', cat: 'Ops' },
  { name: 'Hermes',      icon: 'hermes',    desc: 'AI agent (Nous)',            port: 9119,  url: '/go/hermes', status: 'up', cat: 'Agent' },
  { name: 'OpenSquilla', icon: 'opensquilla', desc: 'token 高效 agent',        port: 18791, url: '/go/opensquilla', status: 'up', cat: 'Agent' },
  { name: 'Open Design', icon: 'opendesign', desc: '设计工具',                  port: 7456,  url: '/go/design', status: 'up', cat: 'Agent' },
  { name: 'Next AI Draw',icon: 'nextdraw',  desc: 'AI 画图',                    port: 4733,  url: '/go/draw',   status: 'up', cat: 'Agent' },
  { name: 'LiteLLM',     icon: 'litellm',   desc: 'LLM 网关',                   port: 4000,  url: '/go/litellm', status: 'up', cat: 'AI' },
  { name: 'API 指南',    icon: 'api',       desc: 'API 端点+调用示例+健康检查',  port: 0,     url: '/api-guide/', status: 'up', cat: 'AI' },
];

// 分类元数据: cls 决定分类色系 (ai蓝/app紫/ops青/agent橙)
export const categoryMeta = {
  AI:    { label: 'AI 服务',    cls: 'ai' },
  App:   { label: '应用',       cls: 'app' },
  Ops:   { label: '监控与运维', cls: 'ops' },
  Agent: { label: 'Agent',      cls: 'agent' },
};

export const catOrder = ['AI', 'App', 'Ops', 'Agent'];

export const llmModels = [
  { name: 'Qwen3.6-35B-A3B', provider: 'llama.cpp (Vulkan)', type: 'local', status: 'active', ctx: '256K / 槽', rpm: 0, tpm: 0 },
  { name: 'bge-m3', provider: 'llama.cpp (Vulkan)', type: 'embed', status: 'active', ctx: '8K', rpm: 0, tpm: 0 },
];

export const knowledgeBase = [
  { title: '运维手册', q: '重启某个服务? 查看日志?', a: '使用 docker compose restart <service>。日志: docker compose logs -f <service>' },
  { title: '硬件能力', q: 'GPU 显存多少? 能跑多大模型?', a: 'Radeon 8060S, 96GB 可分配显存, 可跑 Qwen3.6-35B 4槽并发' },
];
