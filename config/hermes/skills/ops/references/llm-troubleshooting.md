# LLM 推理故障排查

## llama.cpp (Vulkan 后端)

本机使用 Vulkan 后端适配 Radeon 8060S (非 ROCm, 因 gfx1151 暂不支持)。

### 检查推理服务
```bash
# llama.cpp 健康
curl http://localhost:8082/health

# 模型列表
curl http://localhost:8082/v1/models

# 测试推理
curl http://localhost:8082/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3.6-35B-A3B","messages":[{"role":"user","content":"hi"}]}'
```

### GPU 未被利用
```bash
# 检查 Vulkan 是否识别 GPU
vulkaninfo --summary 2>/dev/null | grep -A2 "GPU"

# 检查 llama.cpp 日志中的 GPU 信息
docker logs $(docker ps -q --filter name=llama) 2>&1 | grep -i "vulkan\|gpu\|device"
```

### 推理速度慢 / OOM
- 统一内存机器: GPU 显存 = 系统内存的一部分, 不是独立显存
- 检查 mem-bw: `glances` 看 GPU mem 占用
- 减少并发槽位: 编辑 llama.cpp 启动参数 `--parallel`
- 上下文太长会占满 KV cache: 检查 `--ctx-size` vs `--parallel`

## LiteLLM 网关

### 检查网关
```bash
# LiteLLM 健康
curl http://localhost:4000/health

# 模型路由
curl http://localhost:4000/v1/models \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# LiteLLM 日志
docker logs $(docker ps -q --filter name=litellm) --tail 50
```

### 401 鉴权错误
- LiteLLM 需要 master key: 检查 `.env` 里的 `LITELLM_MASTER_KEY`
- Caddy 反代会自动注入 key (header_up Authorization)

### 模型路由失败 (no_provider)
- LiteLLM config 里 model 名称必须和 llama.cpp 暴露的名称一致
- 检查: `~/TitanVault/config/litellm/config.yaml`
