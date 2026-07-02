# 运维自动化

TitanVault 采用**分层运维**: 确定性脚本处理 80% 固定流程, hermes agent 处理 20% 智能决策。这一层不只是"能查能手动修"，而是**真正的无人值守闭环**——故障自愈、告警推送、更新回滚、磁盘止血。

```
┌──────────────────────────────────────────────────────┐
│  第1层: 确定性自愈闭环 (bash + cron)                    │
│   restart:unless-stopped (容器挂自动起)                 │
│   health-check (critical→自动heal, 磁盘满→自动止血)     │
│   ops.sh: status/heal/update(回滚)/cleanup(WAL)/report │
│   setup-uptime-kuma: 复用其70+告警通道推送               │
│   setup-cron: 定时备份/自愈/更新                         │
├──────────────────────────────────────────────────────┤
│  第2层: hermes 智能层 (SKILL.md + cron)                 │
│   读 ops.sh 状态 → 根因分析 + 报告                      │
│   低风险自愈 (调 ops.sh heal)                           │
│   非标准故障 → 升级人工 (不直接改生产)                    │
└──────────────────────────────────────────────────────┘
```

## 快速上手

### 查看状态 (含性能)
```bash
bash scripts/ops.sh status          # 健康+性能 (容器/llama延迟/队列/GPU/磁盘)
bash scripts/ops.sh report          # 运维摘要
bash scripts/health-check.sh --json # 机器可读 (供监控集成)
```

### 配置告警 (复用 uptime-kuma, 必做!)
uptime-kuma 自带 Telegram/邮件/Webhook 等 70+ 告警通道, 复用它推送故障:
```bash
# 1. 浏览器打开 :3001 建 uptime-kuma 管理员账号
# 2. 设置 → API Keys → 生成 token
# 3. 注册监控项:
UPTIME_KUMA_TOKEN=xxx bash scripts/setup-uptime-kuma.sh
# 4. 在 UI 里给所有监控项绑定通知通道 (Telegram/邮件等)
```
⚠️ **必须手动做第4步**——完成通知绑定前, 故障不会推送到你。

### 安装定时任务
```bash
bash scripts/setup-cron.sh          # 安装默认调度
```
| 任务 | 时间 | 动作 |
|---|---|---|
| 健康检查 | 每小时 | `status` (critical 自动 heal, 磁盘满自动止血) |
| 备份 | 每天 3:00 | `backup` |
| 自愈+清理 | 每天 4:00 | `heal` + `cleanup` (含WAL回收) |
| 镜像更新 | 每周日 5:00 | `update --yes` (备份→更新→验证→失败回滚) |

## 闭环能力 (没人值守也能扛)

### 故障自愈链
```
容器挂/OOM/端口不通 → restart策略兜底 → 仍异常 → health-check检测critical
→ 自动 ops.sh heal (重启异常容器) → 复检 → 仍失败则告警(uptime-kuma)+升级hermes
```

### 磁盘止血 (防撑爆整机)
```
disk≥95% → health-check 立即触发 emergency-disk
→ docker system prune + postgres WAL回收 + 截断容器日志 + 删旧备份
→ 仍满则告警人工 (du -sh 查大文件)
```

### 更新回滚 (防上游 breaking change)
```
update --yes → 先备份(pre-update) → pull新镜像 → recreate → 等60s健康验证
→ 通过: 完成
→ 失败: 重启服务, 仍失败则报错 + 指向备份恢复 (bash scripts/restore.sh <pre-update>)
```

### LLM 性能监控 (不只看存活)
health-check 额外检查:
- `/slots` 队列堆积 (全满=过载)
- 推理延迟探测 (>30s 告警)
- GPU busy% (AMD sysfs)

## 手动操作
```bash
bash scripts/ops.sh heal              # 低风险自愈
bash scripts/ops.sh cleanup           # 清理+WAL回收+旧备份
bash scripts/ops.sh emergency-disk 90 # 手动触发磁盘止血 (阈值90)
bash scripts/ops.sh update --yes      # 闭环更新 (备份→验证→回滚)
```

## hermes 集成 (智能运维)
- `ops/mozin-ops/SKILL.md`: 权限矩阵 (低风险✅自动 / 高风险🚫升级人工)
- `ops/knowledge/triage.md`: 故障分诊表
- 装载: `ln -s $PWD/ops/mozin-ops ~/.hermes/skills/mozin-ops`

## 设计原则
1. **闭环优先**: 检测→止血→验证→回滚/告警, 不只记录等人看
2. **复用不造轮子**: 告警用 uptime-kuma (70+通道), 不自写推送
3. **低风险自动, 高风险人工**: 容器重启/WAL清理自动, 改配置/删数据需确认
4. **幂等**: 所有 ops 子命令可重跑

