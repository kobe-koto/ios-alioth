#!/usr/bin/env python3
"""Join a650_hwcg_regs (symbol->value) with a6xx_reg.h (symbol->offset) to emit
a C table of {GPU_WORD offset, value} pairs for redwood_adreno.c. Read-only over
the vendor tree; paths passed as args."""
import re
import sys

gpulist, reg_h = sys.argv[1], sys.argv[2]

# symbol -> offset (word index)
off = {}
for line in open(reg_h, encoding="utf-8", errors="replace"):
    m = re.match(r"#define\s+(A6XX_\w+)\s+(0[xX][0-9a-fA-F]+)", line)
    if m:
        off[m.group(1)] = int(m.group(2), 16)

# extract a650_hwcg_regs body
src = open(gpulist, encoding="utf-8", errors="replace").read()
m = re.search(r"a650_hwcg_regs\[\]\s*=\s*\{(.*?)\};", src, re.S)
if m is None:
    sys.exit("a650_hwcg_regs[] not found in " + gpulist)
body = m.group(1)
rows = re.findall(r"\{\s*(A6XX_\w+)\s*,\s*(0[xX][0-9a-fA-F]+)\s*\}", body)

GPU_BASE = 0x03d00000
GMU_DELTA = 0x1a800  # (gmu_base - gpu_base)/4
print(f"// generated from vendor kgsl: {len(rows)} rows")
for sym, val in rows:
    if sym not in off:
        print(f"// MISSING OFFSET: {sym}", file=sys.stderr)
        continue
    o = off[sym]
    note = ""
    if o >= GMU_DELTA:
        note = f"  // GMU-side: GMU_WORD(0x{o - GMU_DELTA:04x})"
    print(f"\t{{ 0x{o:04x}, {val.upper().replace('0X','0x')} }},{note}  // {sym}")
