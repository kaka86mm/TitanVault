# 贡献指南

感谢你对 TitanVault / TitanVault 的兴趣！本文档说明如何参与贡献。

## 环境要求

- AMD Ryzen AI Max+ 395 机器（开发/测试需要真实硬件）
- Ubuntu 24.04 / 26.04 LTS
- Docker 24+ / Docker Compose v2
- git

## 开发流程

1. **Fork & Clone**
   ```bash
   git clone https://github.com/<your-fork>/TitanVault.git
   cd TitanVault
   ```

2. **创建分支**
   ```bash
   git checkout -b feat/your-feature
   ```

3. **本地测试**
   ```bash
   # 改完后, 清服务层重装验证
   bash install.sh --resume 5   # 只跑 Phase 5 (快)
   # 或全量重装 (慢, 但最严格)
   bash install.sh
   ```

4. **提交 PR**
   - PR 标题用 conventional commits 格式：`feat: ...` / `fix: ...` / `docs: ...`
   - 描述改了什么、为什么改、怎么测的
   - 如果改了 install.sh, 请说明在 1.7 机器上验证过

## 代码规范

### install.sh
- 6 Phase 结构不动（Phase 0-6），新逻辑加到对应 Phase
- 所有操作幂等（重跑不报错、不重复创建）
- 用 `log()` / `warn()` / `err()` 输出，不裸 echo
- 密码用 `openssl rand -hex` 生成，不硬编码

### compose 文件
- 每个服务必须标 `profiles: [...]`（不能裸跑）
- 日志用 `logging: *id001`（复用文件的 YAML 锚点）
- volume 用 `${DATA_DIR:-/data}/<service>/...` 格式
- 新增服务加到对应分层文件（infra/gateway/ai-capability/...）

### 配置模板
- `.tpl` 文件用 `envsubst` 渲染的变量必须 `load_env` + `load_hardware` 后才导出
- Caddyfile 用 Caddy 原生 `{$VAR}` 语法（不用 envsubst）

## 硬件限制

本发行版**仅支持 AMD Ryzen AI Max+ 395 (gfx1151)**。不要提交 NVIDIA/Intel/其它 AMD GPU 的支持——这会让安装器变复杂且无法测试。如果你有其它硬件的需求，欢迎开 issue 讨论。

## 报告 Bug

开 issue 时请附：
1. 硬件型号（确认是 395）
2. Ubuntu 版本
3. `bash install.sh` 的完整输出（或出错段）
4. `journalctl -u <服务名>` 的错误日志
5. 哪个 Phase 失败的

## 许可证

提交的代码遵循 Apache-2.0（见 [LICENSE](LICENSE)）。
