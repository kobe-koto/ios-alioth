#!/usr/bin/env python3
"""Read, on this machine, what the K40 (alioth) has that the GPU driver needs before a run.

usage:
  alioth.py dt PATH        a device tree: a .dtb (the phone's, or Mu-Silicium's), a .dts,
                           or a directory (adb pull /sys/firmware/devicetree/base)
  alioth.py gmu PATH       a650_gmu.bin, from /vendor/firmware
  alioth.py sqe PATH       a650_sqe.fw
  alioth.py zap PATH       a650_zap.mdt (a650_zap.b02 is read beside it if there)
  alioth.py check DIR      all four by name, in one directory

What it answers, without the phone and without the kernel:
  dt   where reserved-memory puts the zap shader (the driver's adreno_zap_mem=; the K40's node is
       pil_gpu_region), the chip id, the GPU's speeds per speed bin and their RPMh levels
       (qcom,gpu-pwrlevels-N, qcom,level or Linux's OPP table), the SMMU's streams, and which
       Wi-Fi chip there is and on which bus
  gmu  whether the firmware is the block file Linux and this driver take, where each block goes,
       how much memory it asks for and whether that fits the driver's limit (0x100000 per
       request), and whether every block with data lands in a region the file asked for -- the
       check that fails on the phone, before anything is written, if they disagree
  sqe  the microcode's version word (the a650 needs 0.95 or newer) and its size
  zap  whether the .mdt is the ELF header TrustZone takes (one page: header, program headers,
       then the hashes), and how big the .b02 that goes with it is

Nothing here is flashed, and nothing is written to the device.
"""
import os
import re
import shutil
import struct
import sys
import tempfile

PAGE = 4096
GMU_ITCM = 0x00000000
GMU_DTCM = 0x10004000
GMU_TCM_SIZE = 0x4000
GMU_VERSION_WORD = GMU_DTCM + 0xFF8 * 4          # where the firmware's versions are (a6xx_gmu_fw_load)
DRIVER_REQUEST_LIMIT = 0x100000                  # redwood_adreno.c: block.value > 0x100000 is refused
GMU_NEEDS = (1, 7)                               # block types without data: "I need N bytes here"
# The K40's vendor device tree (like many) has no qcom,level: these are Linux's sm8250 OPP levels
# (RPMH_REGULATOR_LEVEL_*, qcom-rpmpd.h), by MHz. The driver's alioth_speeds[] holds the same pairs.
A650_LEVELS = { 670: 320, 587: 256, 525: 224, 490: 192, 441: 144, 400: 128, 305: 64, 0: 0 }

failures = 0


def fail(what):
    global failures
    failures += 1
    print("FAIL: %s" % what)


def in_tcm(address):
    return (GMU_ITCM <= address < GMU_ITCM + GMU_TCM_SIZE or
            GMU_DTCM <= address < GMU_DTCM + GMU_TCM_SIZE)


def cells(raw):
    """A property of big-endian 32-bit cells."""
    return list(struct.unpack(">%dI" % (len(raw) // 4), raw[:len(raw) // 4 * 4]))


def strings(raw):
    return [part.decode("utf-8", "replace") for part in raw.rstrip(b"\0").split(b"\0") if part]


# ---- device tree ------------------------------------------------------------------------------

def dt_cells(node, name):
    try:
        with open(os.path.join(node, name), "rb") as file:
            return cells(file.read())
    except FileNotFoundError:
        return []


def dt_strings(node, name):
    try:
        with open(os.path.join(node, name), "rb") as file:
            return strings(file.read())
    except FileNotFoundError:
        return []


def dt_find(root, pattern, first=True):
    found = []
    for path, dirs, files in os.walk(root):
        if re.search(pattern, os.path.basename(path)):
            found.append(path)
            if first:
                break
    return found[0] if first and found else (found if not first else None)


def dt_reg(node):
    """reg as (base, size), for the two shapes a device tree writes a one-entry reg in."""
    values = dt_cells(node, "reg")
    if len(values) == 4:
        return (values[0] << 32 | values[1], values[2] << 32 | values[3])
    if len(values) == 2:
        return (values[0], values[1])
    return None


def dtb_nodes(path):
    """A .dtb as nested nodes {"name", "props": {name: raw bytes}, "children"}, or None."""
    data = open(path, "rb").read()
    if len(data) < 40 or struct.unpack_from(">I", data)[0] != 0xD00DFEED:
        fail("%s is not a device tree blob (magic %#x)" %
             (path, struct.unpack_from(">I", data)[0] if len(data) >= 4 else 0))
        return None
    total, off_struct, off_strings, _, _, _, _, size_strings = struct.unpack_from(">IIIIIIII", data, 4)
    size_struct = struct.unpack_from(">I", data, 36)[0]
    if total > len(data) or off_struct + size_struct > len(data) or off_strings + size_strings > len(data):
        fail("%s is truncated: the header says %#x bytes, the file has %#x" % (path, total, len(data)))
        return None
    names = data[off_strings:off_strings + size_strings]

    def property_name(at):
        end = names.find(b"\0", at)
        return names[at:end].decode("utf-8", "replace") if end >= 0 else ""

    root = {"name": "", "props": {}, "children": []}
    stack, at = [root], off_struct
    while at + 4 <= off_struct + size_struct:
        token = struct.unpack_from(">I", data, at)[0]
        at += 4
        if token == 1:                                  # FDT_BEGIN_NODE
            end = data.find(b"\0", at)
            if end < 0:
                fail("%s ends inside a node's name" % path)
                return None
            node = {"name": data[at:end].decode("utf-8", "replace"), "props": {}, "children": []}
            stack[-1]["children"].append(node)
            stack.append(node)
            at = (end + 4) & ~3
        elif token == 2:                                # FDT_END_NODE
            if len(stack) == 1:
                fail("%s has an end of node without a node" % path)
                return None
            stack.pop()
        elif token == 3:                                # FDT_PROP
            length, name_at = struct.unpack_from(">II", data, at)
            at += 8
            stack[-1]["props"][property_name(name_at)] = data[at:at + length]
            at = (at + length + 3) & ~3
        elif token == 4:                                # FDT_NOP
            continue
        elif token == 9:                                # FDT_END
            break
        else:
            fail("%s has an unknown token %#x at %#x" % (path, token, at - 4))
            return None
    if len(stack) != 1:
        fail("%s ends with %d nodes still open" % (path, len(stack) - 1))
        return None
    return root


def dtb_write(node, directory):
    os.makedirs(directory, exist_ok=True)
    for name, value in node["props"].items():
        with open(os.path.join(directory, name.replace("/", "_")), "wb") as file:
            file.write(value)
    for child in node["children"]:
        dtb_write(child, os.path.join(directory, child["name"] or ""))


def dt_blob(path):
    """.dtb: put it in the shape of /sys/firmware/devicetree/base and read it as that."""
    root = dtb_nodes(path)
    if root is None:
        return False
    work = tempfile.mkdtemp(prefix="alioth-dt-")
    try:
        dtb_write(root, work)
        return dt_directory(work, path)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def dt_directory(root, shown=None):
    print("device tree: %s" % (shown or root))
    zap = dt_find(root, r"gpu_micro_code|zap|pil_gpu_region")
    if zap:
        reg = dt_reg(zap)
        print("  zap shader: %s" % os.path.relpath(zap, root))
        print("    reg: base %s size %s" % ("%#x" % reg[0] if reg else "?", "%#x" % reg[1] if reg else "?"))
        if not reg:
            fail("the zap shader's node has no reg this tool understands")
        elif reg[1] < 2 * PAGE:
            fail("the zap shader's reserved region is %#x bytes, under two pages" % reg[1])
        else:
            print("    driver: adreno_zap_mem=%#x" % reg[0])
    else:
        fail("no reserved-memory node for the zap shader (gpu_micro_code)")

    gpu = dt_find(root, r"kgsl-3d0")
    if gpu:
        chip = dt_cells(gpu, "qcom,chipid")
        print("  GPU: %s" % os.path.relpath(gpu, root))
        if chip:
            print("    qcom,chipid: %#x%s" % (chip[0], "" if chip[0] == 0x06050002 else "  (not the a650's 0x06050002)"))
        if dt_strings(gpu, "compatible"):
            print("    compatible: %s" % ", ".join(dt_strings(gpu, "compatible")))
    else:
        fail("no qcom,kgsl-3d0 node")

    speeds = dt_find(root, r"qcom,gpu-pwrlevels(-\d+)?$", first=False)
    if speeds:
        bins = [path for path in speeds if re.search(r"qcom,gpu-pwrlevels-\d+$", os.path.basename(path))]
        flat = [path for path in speeds if path not in bins]
        rows_by_bin = []
        for node in sorted(bins, key=lambda path: int(re.search(r"-(\d+)$", os.path.basename(path)).group(1))):
            rows = []
            for child in sorted(os.listdir(node)):
                level_node = os.path.join(node, child)
                if not os.path.isdir(level_node):
                    continue
                hz, level = dt_cells(level_node, "qcom,gpu-freq"), dt_cells(level_node, "qcom,level")
                if hz:
                    rows.append((hz[0] // 1000, level[0] if level else None))
            rows.sort()
            rows_by_bin.append((os.path.basename(node), rows))
        for node in flat:
            rows = []
            for hz, level in zip(dt_cells(node, "qcom,gpu-freq"), dt_cells(node, "qcom,level")):
                rows.append((hz // 1000, level))
            rows_by_bin.append((os.path.basename(node), sorted(rows)))

        print("  speeds (qcom,gpu-pwrlevels, one table per fuse speed bin):")
        missing_levels = False
        for name, rows in rows_by_bin:
            if not rows:
                print("    %s: no qcom,gpu-freq in its levels" % name)
                continue
            shown = []
            for khz, level in rows:
                if level is None:
                    level = A650_LEVELS.get(khz // 1000)
                    missing_levels |= level is None
                shown.append("%u MHz/%s" % (khz // 1000, level if level is not None else "?"))
            print("    %s: %s" % (name, ", ".join(shown)))
        if missing_levels:
            print("    (a '?' is a speed with no qcom,level in the device tree and none known for the a650)")
        elif any(level is None for _, rows in rows_by_bin for _, level in rows):
            print("    levels not in the device tree: from Linux's sm8250 OPP table (RPMH levels, qcom-rpmpd.h)")
        maxima = [max(khz for khz, _ in rows) for _, rows in rows_by_bin if rows]
        if maxima:
            print("    driver: adreno_soc=a650; alioth_speeds[] holds the union; the default is %u MHz, the "
                  "fastest the slowest of these bins is fused for" % (min(maxima) // 1000))
        else:
            print("    driver: adreno_soc=a650; alioth_speeds[] holds the union")
    else:
        print("  speeds: none found (a device-tree dump may keep them in qcom,gpu-pwrlevels-N)")

    smmu = dt_find(root, r"kgsl-smmu")
    if smmu:
        print("  SMMU: %s" % os.path.relpath(smmu, root))
        for child in sorted(os.listdir(smmu)):
            node = os.path.join(smmu, child)
            if not os.path.isdir(node):
                continue
            streams = dt_cells(node, "qcom,stream-id-range")
            if streams:
                print("    %s: stream ids %#x..%#x" % (child, streams[0], streams[0] + streams[1] - 1))
    else:
        fail("no kgsl-smmu node")

    wifi = []
    for path, dirs, files in os.walk(root):
        for compatible in dt_strings(path, "compatible"):
            if re.search(r"wcn|ath11k|cnss|qca", compatible):
                wifi.append((os.path.relpath(path, root), compatible))
    if wifi:
        print("  Wi-Fi:")
        for path, compatible in wifi:
            print("    %s: %s" % (path, compatible))
    else:
        print("  Wi-Fi: no wcn/ath11k/cnss node (check the node name and its compatible)")

    for node in dt_find(root, r"pcie@1c00000", first=False):
        status = dt_strings(node, "status")
        print("  pcie@1c00000: %s" % (", ".join(status) if status else "no status"))
    return zap is not None


def dt_text(path):
    source = open(path, errors="replace").read()
    print("device tree: %s" % path)
    found = False
    for match in re.finditer(r"(gpu_micro_code[^{]*|zap[^{]*)\{(.*?)\};", source, re.S):
        cells_found = re.search(r"reg\s*=\s*<([^>]+)>", match.group(2))
        if cells_found:
            values = [int(part, 0) for part in cells_found.group(1).split()]
            base, size = (values[0] << 32 | values[1], values[2] << 32 | values[3]) if len(values) == 4 else values[:2]
            print("  zap shader: base %#x size %#x" % (base, size))
            print("    driver: adreno_zap_mem=%#x" % base)
            found = True
            break
    if not found:
        fail("no reserved-memory node for the zap shader in the .dts")

    chip = re.search(r"qcom,chipid\s*=\s*<([^>]+)>", source)
    if chip:
        print("  qcom,chipid: %#x" % int(chip.group(1).split()[0], 0))

    levels = re.search(r"qcom,gpu-pwrlevels\s*\{(.*?)\n\s*\};", source, re.S)
    if levels:
        pairs = re.findall(r"qcom,gpu-freq\s*=\s*<([^>]+)>", levels.group(1))
        rlevels = re.findall(r"qcom,level\s*=\s*<([^>]+)>", levels.group(1))
        print("  speeds:")
        for i, freq in enumerate(pairs):
            level = rlevels[i].split()[0] if i < len(rlevels) else "?"
            print("    %6u MHz, RPMh level %s" % (int(freq.split()[0], 0) // 1000000, level))
    for node in re.finditer(r"pcie@1c00000\s*\{(.*?)\n\s*\};", source, re.S):
        status = re.search(r"status\s*=\s*\"([^\"]*)\"", node.group(1))
        print("  pcie@1c00000: %s" % (status.group(1) if status else "no status"))
    for compatible in re.findall(r"compatible\s*=\s*\"([^\"]*(?:wcn|ath11k|cnss|qca)[^\"]*)\"", source):
        print("  Wi-Fi: %s" % compatible)
    return True


# ---- GMU firmware -----------------------------------------------------------------------------

def gmu(path):
    data = open(path, "rb").read()
    blocks, at = [], 0
    while at + 16 <= len(data):
        address, size, kind, value = struct.unpack_from("<IIII", data, at)
        if at + 16 + size > len(data):
            fail("the file ends inside a block (%#x bytes of %#x at %#x)" % (len(data) - at - 16, size, at))
            break
        blocks.append((address, size, kind, value, data[at + 16:at + 16 + size]))
        at += 16 + size
    if at != len(data):
        fail("the file has %#x bytes after its last block" % (len(data) - at))
    if not blocks:
        fail("no block at all (the file may be an older, plain image)")
        return False

    print("GMU firmware: %s, %#x bytes, %d blocks" % (path, len(data), len(blocks)))
    requests, payloads = [], []
    for address, size, kind, value, body in blocks:
        if size == 0:
            if kind in GMU_NEEDS:
                requests.append((address, value))
            continue
        payloads.append((address, size, body))
        if in_tcm(address) and not in_tcm(address + size - 1):
            fail("a block at %#x crosses out of the GMU's own memory" % address)

    print("  memory the firmware asks for:")
    made = []                       # the ones the driver makes memory for
    for address, size in requests:
        if in_tcm(address):
            # The GMU's own 16K of code and 16K of data: written through registers, not memory of ours
            print("    %#010x  %#8x bytes  in the GMU's own memory (through its registers)" % (address, size))
            continue
        note = ""
        if address % PAGE:
            note += "  NOT PAGE-ALIGNED"
        if size > DRIVER_REQUEST_LIMIT:
            note += "  OVER THE DRIVER'S 0x100000 LIMIT"
        print("    %#010x  %#8x bytes%s" % (address, size, note))
        if address % PAGE:
            fail("a request at %#x is not page-aligned" % address)
        if size > DRIVER_REQUEST_LIMIT:
            fail("a request of %#x bytes is more than the driver makes" % size)
        made.append((address, size))
    for i in range(1, len(made)):
        if made[i][0] < made[i - 1][0] + made[i - 1][1]:
            fail("two requests overlap: %#x and %#x" % (made[i - 1][0], made[i][0]))

    print("  blocks with data:")
    for address, size, body in payloads:
        if in_tcm(address):
            base, register = (GMU_ITCM, 0x0C00) if address < GMU_DTCM else (GMU_DTCM, 0x1C00)
            at = register + (address - base) // 4
            print("    %#010x  %#8x  the GMU's own memory: registers %#x..%#x" % (address, size, at, at + size // 4 - 1))
            if size % 4:
                fail("a block of %#x bytes into the GMU's own memory is not a whole number of words" % size)
            continue
        holder = [r for r in made if r[0] <= address and address + size <= r[0] + r[1]]
        if holder:
            print("    %#010x  %#8x  in the request at %#x" % (address, size, holder[0][0]))
        else:
            print("    %#010x  %#8x  NOWHERE: it asked for no memory here" % (address, size))
            fail("a block with data lands where the firmware asked for no memory")
    for i in range(1, len(payloads)):
        if not in_tcm(payloads[i][0]) and payloads[i][0] < payloads[i - 1][0] + payloads[i - 1][1]:
            fail("two blocks with data overlap: %#x and %#x" % (payloads[i - 1][0], payloads[i][0]))

    for address, size, body in payloads:
        if address <= GMU_VERSION_WORD < address + size:
            words = struct.unpack_from("<5I", body, GMU_VERSION_WORD - address)
            print("  versions the file carries: core %#x, power %#x, HFI %#x" % (words[0], words[2], words[4]))
            break

    itcm = sum(size for address, size, body in payloads if GMU_ITCM <= address < GMU_ITCM + GMU_TCM_SIZE)
    dtcm = sum(size for address, size, body in payloads if GMU_DTCM <= address < GMU_DTCM + GMU_TCM_SIZE)
    print("  through the GMU's registers: %#x bytes of code, %#x of data (16K each at most)" % (itcm, dtcm))
    if itcm > GMU_TCM_SIZE or dtcm > GMU_TCM_SIZE:
        fail("more than 16K into the GMU's code or data memory")
    return True


# ---- SQE microcode ----------------------------------------------------------------------------

def sqe(path):
    data = open(path, "rb").read()
    if len(data) < 8:
        fail("%s is %#x bytes: not a microcode file" % (path, len(data)))
        return False
    # The first word is not microcode and not the version: Linux's adreno_fw_create_bo copies the
    # image from offset 4 (a6xx_ucode_check_version then reads buf[0], the file's word 1), and this
    # driver copies from offset 4 as well. The real files start with 0x00000000.
    version = struct.unpack_from("<I", data, 4)[0]
    print("SQE microcode: %s, %#x bytes" % (path, len(data)))
    print("  version word (offset 4) %#x: bits 0..11 are %#x (the a650 needs %#x or newer)" %
          (version, version & 0xfff, 0x095))
    if (version & 0xfff) < 0x095:
        fail("that microcode is older than 0.95")
    print("  the driver copies %#x bytes from offset 4" % (len(data) - 4))
    return True


# ---- zap shader -------------------------------------------------------------------------------

def zap(path):
    data = open(path, "rb").read()
    print("zap shader header: %s, %#x bytes" % (path, len(data)))
    if len(data) < 52 + 2 * 32:
        fail("too short for an ELF header and two program headers")
        return False
    if data[:5] != b"\x7fELF\x01":
        fail("not a 32-bit ELF")
        return False
    segments = struct.unpack_from("<H", data, 44)[0]
    print("  ELF, %d segments, program headers at 52 (%d bytes each)" % (segments, 32))
    if segments < 2:
        fail("fewer than two segments")
        return False
    for i in range(segments):
        kind, offset, vaddr, paddr, filesz, memsz, flags, align = struct.unpack_from("<8I", data, 52 + 32 * i)
        print("    segment %d: type %d, file offset %#x, vaddr %#x, paddr %#x, %#x bytes in file, %#x in memory" %
              (i, kind, offset, vaddr, paddr, filesz, memsz))
    hashes = struct.unpack_from("<I", data, 52 + 32 + 16)[0]
    print("  the second segment carries %#x bytes; the file is the header (%#x) and those" % (hashes, 52 + 32 * segments))
    if 52 + 32 * segments + hashes != len(data):
        fail("the file is not the header followed by the hashes alone")
    pages = (len(data) + PAGE - 1) // PAGE
    if pages > 1:
        # The K40's header is 0x1acc bytes: two pages. zap_header() in the driver allocates
        # round_page(size) for it; a header of more than one page is not a fault.
        print("  it spans %d pages (%#x bytes); the driver allocates exactly that many" % (pages, len(data)))
    b02 = path[:-4] + ".b02" if path.endswith(".mdt") else None
    if b02 and os.path.exists(b02):
        print("  the data that goes with it: %s, %#x bytes" % (os.path.basename(b02), os.path.getsize(b02)))
    else:
        print("  no .b02 beside it: the driver will stop at step 19 asking for one")
    return True


def check(directory):
    print("checking %s" % directory)
    for name, reader in (("a650_gmu.bin", gmu), ("a650_sqe.fw", sqe), ("a650_zap.mdt", zap)):
        path = os.path.join(directory, name)
        print()
        if not os.path.exists(path):
            fail("%s is not there" % name)
            continue
        reader(path)
    print()
    print("%d failures" % failures)
    return failures == 0


def main(argv):
    if len(argv) < 3 or argv[1] not in ("dt", "gmu", "sqe", "zap", "check"):
        print(__doc__)
        return 2
    what, path = argv[1], argv[2]
    if what == "dt":
        if path.endswith(".dtb"):
            ok = dt_blob(path)
        else:
            ok = dt_directory(path) if os.path.isdir(path) else dt_text(path)
    elif what == "gmu":
        ok = gmu(path)
    elif what == "sqe":
        ok = sqe(path)
    elif what == "zap":
        ok = zap(path)
    else:
        return 0 if check(path) else 1
    if what in ("dt", "gmu", "sqe", "zap"):
        print("%d failures" % failures)
        return 0 if ok and failures == 0 else 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
