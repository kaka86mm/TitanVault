# AMD AI MAX 395 硬件运维

## 统一内存架构 (关键!)

本机是**统一内存**架构: CPU 和 GPU 共享 128GB LPDDR5X-8000。
- 不是独立显卡 + 独立显存的传统模式
- GPU 可分配高达 96GB "显存" (从系统内存划拨)
- 分配比例由 BIOS UMA Frame Buffer 控制 (需重启进 BIOS 改)

## 查看 GPU 状态

```bash
# Vulkan 设备 (本机用 Vulkan, 非 ROCm)
vulkaninfo --summary

# GPU 利用率 (通过 Glances API)
curl -s http://localhost:61208/api/4/all | python3 -c "import sys,json; d=json.load(sys.stdin); print('GPU:', d.get('gpu'))"

# 实时监控
watch -n 2 'curl -s http://localhost:61208/api/4/gpu'
```

## 显存分配

BIOS 中 UMA Frame Buffer Size 决定 GPU 可用内存:
- `Auto` / `16G` → GPU 仅 16GB
- `96G` → GPU 可用 96GB (推荐, 能跑大模型)

检查当前分配:
```bash
# dmesg 看 amdgpu 驱动分配
dmesg | grep -i "amdgpu.*mem\|VRAM\|buffer"
```

## 温度监控

```bash
# CPU/GPU 温度
sensors 2>/dev/null | grep -i "tctl\|edge\|junction"

# 或通过 hwmon
cat /sys/class/hwmon/hwmon*/temp*_input 2>/dev/null | while read t; do echo "$((t/1000))°C"; done
```

## 注意事项

- gfx1151 (RDNA 3.5) **不支持 ROCm**, 必须用 Vulkan 后端
- llama.cpp 编译需启用 Vulkan: `-DGGML_VULKAN=ON`
- 不要安装 AMDPRO / ROCm 驱动, 用开源 Mesa Vulkan 驱动即可
