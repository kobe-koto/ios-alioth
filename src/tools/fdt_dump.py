#!/usr/bin/env python3
"""最小 FDT(DTB) 解析器 —— 不依赖 dtc / pyfdt，只用标准库。

用法：
  python fdt_dump.py <file.dtb> [--node SUBSTR] [--prop NAME] [--rsv] [--quiet]

  --node SUBSTR      只打印路径里含 SUBSTR 的节点
  --prop NAME        只打印属性名含 NAME 的属性
  --rsv              只打印 memory reservation map
  --quiet            不打印头两行注释

输出：每个节点一段 "path {" + 缩进的属性；字符串用双引号，单元格用 <0x..>。
"""
import struct
import sys

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


class Fdt:
    def __init__(self, data):
        (self.magic, self.totalsize, self.off_struct, self.off_strings,
         self.off_rsvmap, self.version, self.last_comp, self.boot_cpuid,
         self.size_strings, self.size_struct) = struct.unpack_from(">10I", data, 0)
        if self.magic != FDT_MAGIC:
            raise SystemExit("not a DTB (magic %#x)" % self.magic)
        self.data = data
        self.strings = data[self.off_strings:self.off_strings + self.size_strings]

    def string(self, off):
        end = self.strings.find(b"\0", off)
        return self.strings[off:end].decode("utf-8", "replace")

    def rsvmap(self):
        out, off = [], self.off_rsvmap
        while True:
            addr, size = struct.unpack_from(">QQ", self.data, off)
            off += 16
            if addr == 0 and size == 0:
                return out
            out.append((addr, size))

    def nodes(self):
        """产出 (path, [(prop, value)])，每个节点的属性归自己。"""
        off = self.off_struct
        stack = [("", [])]          # (name, props)
        while True:
            tok, = struct.unpack_from(">I", self.data, off)
            off += 4
            if tok == FDT_BEGIN_NODE:
                end = self.data.index(b"\0", off)
                name = self.data[off:end].decode("utf-8", "replace")
                off = (end + 1 + 3) & ~3
                stack.append((name, []))
            elif tok == FDT_END_NODE:
                name, props = stack.pop()
                path = "/" + "/".join(n for n, _ in stack[1:] + [(name, [])] if n)
                yield path, props
            elif tok == FDT_PROP:
                length, nameoff = struct.unpack_from(">II", self.data, off)
                off += 8
                stack[-1][1].append((self.string(nameoff), self.data[off:off + length]))
                off = (off + length + 3) & ~3
            elif tok == FDT_NOP:
                continue
            elif tok == FDT_END:
                return
            else:
                raise SystemExit("bad token %#x at %#x" % (tok, off - 4))


def fmt_value(value):
    if not value:
        return ""
    if len(value) % 4 == 0:
        cells = struct.unpack(">%dI" % (len(value) // 4), value)
        return "<" + " ".join("%#x" % c for c in cells) + ">"
    if value.endswith(b"\0") and all(32 <= c < 127 or c == 0 for c in value):
        return '"' + '", "'.join(p.decode() for p in value.split(b"\0") if p) + '"'
    if len(value) <= 32:
        return "[" + " ".join("%02x" % b for b in value) + "]"
    return "[" + " ".join("%02x" % b for b in value[:32]) + " ... %d bytes]" % len(value)


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    path = args.pop(0)
    node_filter = prop_filter = None
    quiet = False
    rsv_only = False
    while args:
        a = args.pop(0)
        if a == "--node":
            node_filter = args.pop(0)
        elif a == "--prop":
            prop_filter = args.pop(0)
        elif a == "--rsv":
            rsv_only = True
        elif a == "--quiet":
            quiet = True
        else:
            raise SystemExit("unknown option %r" % a)

    f = Fdt(open(path, "rb").read())
    if rsv_only:
        for addr, size in f.rsvmap():
            print("%#012x .. %#012x  %6.2f MB" % (addr, addr + size, size / 1048576))
        return
    if not quiet:
        print("# %s: totalsize=%d version=%d boot_cpuid=%d" % (path, f.totalsize, f.version, f.boot_cpuid))
    for p, props in f.nodes():
        if node_filter and node_filter not in p:
            continue
        print("%s {" % p)
        for name, value in props:
            if prop_filter and prop_filter not in name:
                continue
            print("    %-28s %s" % (name, fmt_value(value)))
        print("}")


if __name__ == "__main__":
    main()
