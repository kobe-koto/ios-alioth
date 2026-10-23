#!/usr/bin/env python3
"""check-constants.py -- 源码里的 alioth 常量必须等于设备树/ABL 里写的东西。

这是一台 Windows 上没法编译的机器上唯一能做的"编译期"检查：把 #if defined(PLATFORM_ALIOTH)
块里的每个地址、每个 GPIO 号，和真实设备树（k40-dump/fdt.txt，由 tools/fdt_dump.py 从
/sys/firmware/fdt 转出）以及 ABL 的内存图（k40-dump/xbl_a.img 里的 AddMem 表）逐条对账。
改错一个数字就该当场红，而不是等开机黑屏。

用法:
  python tools/check-constants.py                     # 用 ../k40-dump（工作区默认位置）
  python tools/check-constants.py --dump D:/k40-dump

返回码: 0 全对，1 有不一致，2 缺输入文件。
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # hackios-xnu-kernel-main
DEV = os.path.join(ROOT, "xnu", "files", "bsd", "dev")
LOADER = os.path.join(ROOT, "xnuloader", "loader.c")

ok_all = True


def report(name, want, got, note=""):
    global ok_all
    same = want == got
    if not same:
        ok_all = False
    print("  %-4s %-18s 设备树/ABL %-12s 源码 %-12s %s" %
          ("OK" if same else "FAIL", name, hexv(want), hexv(got), note))
    return same


def hexv(v):
    if v is None:
        return "-"
    if isinstance(v, str):
        return v
    return "0x%X" % v


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def fdt_node(text, path):
    """返回 {属性名: [值...]}；值是 int 列表（字符串属性给字符串）。"""
    m = re.search(r"^%s \{\n(.*?)^\}" % re.escape(path), text, re.M | re.S)
    if not m:
        return None
    props = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        mm = re.match(r"(\S+)\s+(.*)$", line)
        if not mm:
            continue
        name, rest = mm.group(1), mm.group(2).strip()
        if rest.startswith("<"):
            vals = []
            for tok in rest.strip("<>").split(">"):
                for t in tok.replace("<", " ").split():
                    vals.append(int(t, 16))
            props[name] = vals
        elif rest.startswith('"'):
            props[name] = re.findall(r'"([^"]*)"', rest)
        else:
            props[name] = rest
    return props


def src_defines(path, only_alioth=True):
    """解析一个文件里的 #define，只看 PLATFORM_ALIOTH 分支（有的话）。"""
    text = read(path)
    lines = text.splitlines()
    greedy = {}
    alioth = {}
    depth = []                                   # 每层是否 alioth 分支
    for ln in lines:
        s = ln.strip()
        m = re.match(r"#\s*if\s+defined\(\s*PLATFORM_ALIOTH\s*\)", s)
        if m:
            depth.append(True)
            continue
        if re.match(r"#\s*if", s):
            depth.append(False)
            continue
        if re.match(r"#\s*else", s):
            if depth:
                depth[-1] = not depth[-1]          # 进 #else 就离开 alioth 分支
            continue
        if re.match(r"#\s*endif", s):
            if depth:
                depth.pop()
            continue
        d = re.match(r"#define\s+(\w+)\s+(.+?)\s*(/\*.*)?$", s)
        if not d:
            continue
        name, val = d.group(1), d.group(2).strip()
        try:
            num = int(re.sub(r"[uUlL]+$", "", val.strip("()")), 0)   # 0x0f000000UL
        except ValueError:
            continue
        greedy.setdefault(name, num)
        if any(depth):
            alioth[name] = num
    # 共享常量（GCC_PHYS、SE_SIZE 之类）在 #if 外面，用 greedy 里的值补上
    merged = dict(greedy)
    merged.update(alioth)
    return merged, greedy


def abl_addmem(xbl_path):
    """从 xbl 镜像里抓 ABL 的 AddMem 表：[(addr, size, name)]。"""
    with open(xbl_path, "rb") as f:
        data = f.read()
    out = []
    for m in re.finditer(rb"0x([0-9A-Fa-f]{8}), 0x([0-9A-Fa-f]{6,8}), \"([^\"]{1,24})\"", data):
        out.append((int(m.group(1), 16), int(m.group(2), 16), m.group(3).decode()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=os.path.join(os.path.dirname(ROOT), "k40-dump"))
    a = ap.parse_args()

    fdt_txt = os.path.join(a.dump, "fdt.txt")
    xbl = os.path.join(a.dump, "xbl_a.img")
    if not os.path.isfile(fdt_txt):
        print("缺 %s（先跑 tools/fdt_dump.py 把 fdt.dtb 转成文本）" % fdt_txt)
        return 2
    fdt = read(fdt_txt)

    # --- 触摸 -----------------------------------------------------------------------------------
    print("触摸（redwood_goodix.c vs 设备树）")
    d, _ = src_defines(os.path.join(DEV, "redwood_goodix.c"))
    tlmm = fdt_node(fdt, "/soc/pinctrl@f000000") or {}
    gcc = fdt_node(fdt, "/soc/qcom,gcc@100000") or {}
    se = fdt_node(fdt, "/soc/spi@990000") or {}
    ts = fdt_node(fdt, "/soc/spi@990000/focaltech@0") or {}
    if tlmm:
        report("TLMM_PHYS", tlmm["reg"][0], d.get("TLMM_PHYS"))
        report("TLMM_SIZE", tlmm["reg"][1], d.get("TLMM_SIZE"))
    if gcc:
        report("GCC_PHYS", gcc["reg"][0], d.get("GCC_PHYS"))
    if se:
        report("SE_PHYS", se["reg"][0], d.get("SE_PHYS"))
        report("SE_SIZE", se["reg"][1], d.get("SE_SIZE"))
    if ts:
        report("PIN_RESET", ts["focaltech,reset-gpio"][1], d.get("PIN_RESET"))
        report("PIN_INT", ts["focaltech,irq-gpio"][1], d.get("PIN_INT"))
        # display-coords = <0 0 W H>，芯片给的是 8 倍像素
        report("TOUCH_MAX_X", ts["focaltech,display-coords"][2], d.get("TOUCH_MAX_X"))
        report("TOUCH_MAX_Y", ts["focaltech,display-coords"][3], d.get("TOUCH_MAX_Y"))
    # SPI 的四根线：pinctrl 里 gpio8/9/10 + 独立 cs gpio11，源码引脚号必须都在里面
    spi_pins = set()
    for line in fdt.splitlines():
        if line.strip().startswith("pins "):
            spi_pins.update(int(n) for n in re.findall(r"gpio(\d+)", line))
    want_pins = {d.get("PIN_MISO"), d.get("PIN_MOSI"), d.get("PIN_CLK"), d.get("PIN_CS")}
    missing = sorted(x for x in want_pins if x not in spi_pins)
    report("SPI 四线在 DTB 里", "都复用了" if not missing else "缺 %s" % missing,
           "都复用了", str(sorted(x for x in want_pins if x is not None)))

    # --- 按键 -----------------------------------------------------------------------------------
    print("按键（redwood_buttons.c vs 设备树）")
    b, _ = src_defines(os.path.join(DEV, "redwood_buttons.c"))
    pon_id = pin_id = None
    btn = read(os.path.join(DEV, "redwood_buttons.c"))
    m = re.search(r'peripheral pon = \{[^}]*\.id = (0x[0-9a-fA-F]+)', btn)   # 第一个 = PLATFORM_ALIOTH 分支
    pon_id = int(m.group(1), 16) if m else None
    m = re.search(r'peripheral pin = \{[^}]*\.id = (0x[0-9a-fA-F]+)', btn)
    pin_id = int(m.group(1), 16) if m else None
    pon_node = re.search(r"qcom,power-on@([0-9a-f]+)", fdt)
    gpio_blk = re.search(r"pinctrl@([0-9a-f]+) \{\n\s*compatible\s+\"qcom,spmi-gpio\"", fdt)
    if pon_node and pon_id is not None:
        report("PON 外设 id", int(pon_node.group(1), 16) >> 8, pon_id)
    if gpio_blk and pin_id is not None:
        # GPIO6 = 块基址 + 0x100 * (6-1)，外设 id 是它的高字节
        report("音量+ 外设 id", (int(gpio_blk.group(1), 16) + 0x100 * 5) >> 8, pin_id)

    # --- 马达 -----------------------------------------------------------------------------------
    print("马达（redwood_haptic.c vs 设备树）")
    h, _ = src_defines(os.path.join(DEV, "redwood_haptic.c"))
    if tlmm:
        report("TLMM_PHYS", tlmm["reg"][0], h.get("TLMM_PHYS"))
    aw = fdt_node(fdt, "/soc/i2c@a8c000/aw8697_haptic@5A") or {}
    if aw:
        report("PIN_RESET", aw["reset-gpio"][1], h.get("PIN_RESET"))
        report("PIN_INT", aw["irq-gpio"][1], h.get("PIN_INT"))

    # --- 平台参数 -------------------------------------------------------------------------------
    print("平台（loader.c / alioth.conf vs 设备树与 ABL 内存图）")
    loader = read(LOADER)
    m = re.search(r"platform_alioth = \{(.*?)\n\};", loader, re.S)
    pl = m.group(1) if m else ""
    gic = fdt_node(fdt, "/soc/interrupt-controller@17a00000") or {}
    if gic:
        report("gic_dist", gic["reg"][0], int(re.search(r"\.gic_dist = (0x[0-9A-Fa-f]+)", pl).group(1), 16))
        report("gic_redist", gic["reg"][2], int(re.search(r"\.gic_redist = (0x[0-9A-Fa-f]+)", pl).group(1), 16))
    splash = fdt_node(fdt, "/reserved-memory/cont_splash_region@9c000000") or {}
    if splash:
        report("fb_base", splash["reg"][1], int(re.search(r"\.fb_base = (0x[0-9A-Fa-f]+)", pl).group(1), 16),
               "cont_splash_region")
    epss = fdt_node(fdt, "/soc/qcom,cpufreq-hw") or {}
    if epss:
        c, _ = src_defines(os.path.join(DEV, "redwood_cpufreq.c"))
        report("EPSS_PHYS", epss["reg"][0], c.get("EPSS_PHYS"))
    ufs = fdt_node(fdt, "/soc/ufshc@1d84000") or {}
    if ufs:
        u, _ = src_defines(os.path.join(DEV, "redwood_ufshc.c"))
        report("UFSHC_PHYS", ufs["reg"][0], u.get("UFSHC_PHYS"))

    # --- ABL 内存图 -----------------------------------------------------------------------------
    if os.path.isfile(xbl):
        print("ABL 内存图（xbl_a.img）")
        table = {name: (addr, size) for addr, size, name in abl_addmem(xbl)}
        conf = read(os.path.join(ROOT, "common", "devices", "alioth.conf"))
        fd_base = int(re.search(r"^FD_BASE=(0x[0-9A-Fa-f]+)", conf, re.M).group(1), 16)
        fd_size = int(re.search(r"^FD_SIZE=(0x[0-9A-Fa-f]+)", conf, re.M).group(1), 16)
        if "UEFI FD" in table:
            report("FD_BASE", table["UEFI FD"][0], fd_base, "ABL \"UEFI FD\"")
            report("FD_SIZE", table["UEFI FD"][1], fd_size, "ABL \"UEFI FD\"")
        payload = int(re.search(r"^PAYLOAD_BASE=(0x[0-9A-Fa-f]+)", conf, re.M).group(1), 16)
        clash = [n for n, (ad, sz) in table.items() if ad <= payload < ad + sz]
        report("PAYLOAD_BASE 不撞保留区", "无" if not clash else "撞 " + ",".join(clash),
               "无" if not clash else "撞 " + ",".join(clash), hexv(payload))
    else:
        print("（没有 %s，跳过 ABL 内存图对账）" % xbl)

    print()
    print("结论：" + ("全部一致" if ok_all else "有 FAIL，见上"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
