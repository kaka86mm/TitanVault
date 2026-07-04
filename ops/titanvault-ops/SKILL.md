---
name: titanvault-ops
description: "Operate and troubleshoot the TitanVault deployment (health, repair, update). Low-risk actions only."
version: 1.0.0
author: TitanVault
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [Ops, DevOps, Docker, Troubleshooting, Monitoring, TitanVault]
---

# TitanVault Operations — Hermes Skill

Operate and troubleshoot the TitanVault (AMD Ryzen AI Max+ 395 AI workstation).
**Permission model: low-risk execution only.** Read anything; run safe healing; escalate
destructive changes (image updates, config edits) to the human.

## Architecture Recap (what you're operating)

- **GPU native**: `llama-main` (port 8082) + `llama-embed` (8084) run as **systemd**, not Docker.
- **Docker compose**: 7 layered files under `compose/`, gated by profiles (infra/gateway/...).
- **Shared infra**: one `postgres` (pgvector) + `redis` + `qdrant`, reused by dify/gitea/litellm/etc.
- **LLM core**: all LLM traffic flows through `litellm` → native llama.cpp.
- Repo root: `$TITANVAULT_REPO` (the workstation checkout, e.g. `/home/<user>/TitanVault`).

## The Golden Rule: Prefer the deterministic scripts

**Do NOT invent shell commands for ops.** The repo ships idempotent ops scripts — use them.
They handle edge cases you'd miss (postgres logical backup consistency, profile mapping, etc.).

```
terminal(command="bash $TITANVAULT_REPO/scripts/ops.sh status",   workdir="$TITANVAULT_REPO")   # health
terminal(command="bash $TITANVAULT_REPO/scripts/ops.sh heal",      workdir="$TITANVAULT_REPO")   # low-risk self-heal
terminal(command="bash $TITANVAULT_REPO/scripts/ops.sh report",    workdir="$TITANVAULT_REPO")   # ops summary
terminal(command="bash $TITANVAULT_REPO/scripts/health-check.sh --json", workdir="$TITANVAULT_REPO")  # machine-readable
```

## Permission Matrix — what you may and may not do

| Action | Allowed? | How |
|---|---|---|
| Read logs / `ops.sh status` / `report` / `health-check` | ✅ Always | scripts above, `docker logs`, `journalctl -u llama-main` |
| Restart a crashed/exited container | ✅ low-risk | `ops.sh heal` (or `docker compose start <svc>`) |
| Clean disk (`ops.sh cleanup`, prune images) | ✅ low-risk | `ops.sh cleanup` |
| Run a backup | ✅ low-risk | `ops.sh backup` (non-destructive) |
| Restart `llama-main`/`llama-embed` systemd | ⚠️ with reason | `sudo systemctl restart llama-main` — only if 8082/8084 down and heal didn't fix |
| **Update images** (`ops.sh update`) | ❌ escalate | **Tell the human**; requires `--yes`, causes service interruption |
| **Edit config / `.env` / compose** | ❌ escalate | **Propose the diff to the human**, don't apply |
| **Delete data / volumes** | ❌ escalate | Never. Propose restore/rollback to the human |

When you escalate, state: what's wrong, evidence (log lines), the exact command you'd run, and the risk.

## Troubleshooting Workflow

When asked to investigate an issue (or `health-check` shows critical):

1. **Get structured status first** — always start here:
   ```
   terminal(command="bash $TITANVAULT_REPO/scripts/health-check.sh", workdir="$TITANVAULT_REPO")
   ```
2. **For the failing component, read recent logs**:
   - Docker service: `docker compose logs --tail=80 <svc>`
   - Native llama: `journalctl -u llama-main --since "1 hour ago"`
3. **Consult the knowledge base** for known patterns — read `ops/knowledge/`:
   - `ops/knowledge/triage.md` — symptom → likely cause → fix
   - `docs/troubleshooting.md` — full manual
4. **Apply only low-risk fixes** (see matrix). Heal via `ops.sh heal`.
5. **Re-check status** to confirm recovery, then report.

## Common scenarios

### "Something is down" / health-check critical
```
ops.sh status → identify the ❌ line → logs of that svc → ops/knowledge/triage.md → heal or escalate
```

### "Disk almost full"
`ops.sh cleanup` (prunes images + old backups). If still full, report what's large (`du -sh $DATA_DIR/*`) and escalate (don't delete data).

### "Container in restart loop"
Read `docker logs <svc>` → usually a missing env var, bad config, or dependency down.
- Missing `${VAR}` → that var must be in `.env` (escalate: propose the fix, don't edit).
- Dependency down → heal the dependency first (postgres/redis), then restart the svc.

### "llama.cpp slow / not using GPU"
`journalctl -u llama-main | grep -i vulkan` — expect "Found 1 Vulkan devices". If missing GPU, see `docs/troubleshooting.md` GPU section; this is usually a driver/GRUB issue (escalate).

## Daily/weekly reports (cron-driven)

When invoked on a schedule (Hermes cron), produce a concise report:
1. `ops.sh report` for the raw summary.
2. Add a 2-3 sentence natural-language assessment (anything degraded? disk trend? recent restarts?).
3. Deliver to the configured channel. Only alert urgently on **critical** status.

## Remember
- The scripts are the source of truth for safe operations — don't bypass them.
- When unsure whether an action is low-risk, **escalate**. False caution > broken production.
- Record any novel failure+fix you discover into `ops/knowledge/` so next time it's faster.
