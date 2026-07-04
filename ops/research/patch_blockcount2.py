"""
patch_blockcount2.py — 二进制 patch QUEST-9B GGUF 的 block_count (33→32)

纯二进制查找, 不依赖 gguf 库。
"""
import sys
import struct

INPUT = sys.argv[1] if len(sys.argv) > 1 else "/data/models/llm/QUEST-9B-Q4_K_M.gguf"
NEW_VAL = 32

with open(INPUT, "rb") as f:
    content = f.read()

key_bytes = b"qwen35.block_count"
idx = content.find(key_bytes)
if idx < 0:
    print("文件里找不到 qwen35.block_count key")
    sys.exit(1)

print(f"找到 key @ offset {idx}")
# key 后面是 value_type (u32) 然后 value (u32)
val_type_offset = idx + len(key_bytes)
val_type = struct.unpack("<I", content[val_type_offset:val_type_offset+4])[0]
print(f"value_type = {val_type} (4=uint32)")
assert val_type == 4, "不是 uint32"

val_offset = val_type_offset + 4
val = struct.unpack("<I", content[val_offset:val_offset+4])[0]
print(f"value @ offset {val_offset} = {val}")

content = bytearray(content)
struct.pack_into("<I", content, val_offset, NEW_VAL)
with open(INPUT, "wb") as f:
    f.write(content)
print(f"patched: {val} -> {NEW_VAL}")
