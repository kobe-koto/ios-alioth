"""Turn the addresses in a panic log back into names, using the kernel's own symbol table.

    python3 symbolize.py <kernel-image> <text-base> <addr> [addr ...]

Every address the panic prints is absolute; the log also says "Kernel text base", so what identifies
a function is addr - base, which is the symbol's value in the image (the loader puts the kernel
exactly where the image says, so there is no slide).
"""
import bisect
import subprocess
import sys


def symbols(image):
    out = subprocess.run(["llvm-nm", "-n", "--defined-only", image],
                         capture_output=True, text=True, check=True).stdout
    table = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[1] not in "tT":
            continue
        try:
            table.append((int(parts[0], 16), parts[2]))
        except ValueError:
            pass
    table.sort()
    return table


def main():
    image, base = sys.argv[1], int(sys.argv[2], 0)
    table = symbols(image)
    keys = [v for v, _ in table]
    # the symbols are the image's own absolute addresses (it is linked at the base the loader uses),
    # so an address from the log is looked up as it stands
    for text in sys.argv[3:]:
        addr = int(text, 0)
        i = bisect.bisect_right(keys, addr) - 1
        if i < 0:
            print("%#x: before the first symbol (is the base %#x right?)" % (addr, base))
            continue
        value, name = table[i]
        print("%#x -> %s+%#x" % (addr, name, addr - value))


main()
