#!/usr/bin/env python3
"""Check the two SoCs' rows in the GPU driver (struct adreno_soc, bsd/dev/redwood_adreno.c).

usage: test_tables.py PATH/TO/redwood_adreno.c

The rows are the only things that differ between the redwood and the K40, and a wrong number in
one of them is a register write the phone may not survive. This reads them out of the source and
checks them against the values the trees and Linux give (recorded in the driver's comments):
the chip ids, the fuses, the speeds and their RPMh levels, GMEM, UBWC's bank bit, and the
invariants the driver's own loops rely on (a speed table long enough for its count, levels in
order, a default inside it, a fuse mask that fits its cell). It needs no phone and no compiler.
"""
import re
import sys

failures = 0
checks = 0


def check(ok, what):
    global checks, failures
    checks += 1
    if not ok:
        failures += 1
        print("FAIL: %s" % what)


def number(text):
    """A field's value: a hex or decimal number, possibly an arithmetic expression of them."""
    text = text.strip().rstrip(",")
    text = re.sub(r"[uUlL]+$", "", text)          # 0x8b71a000ull
    if not re.fullmatch(r"[0-9a-fA-FxX+*() <>\-]+", text):
        return None
    try:
        return eval(text, {"__builtins__": {}}, {})
    except Exception:
        return None


def soc_block(source, name):
    match = re.search(r"static const struct adreno_soc soc_%s = \{(.*?)\n\};" % name, source, re.S)
    return match.group(1) if match else None


def field(block, name):
    match = re.search(r"\.%s\s*=\s*([^,\n]+)" % name, block)
    return match.group(1).strip() if match else None


def speeds(source, name):
    match = re.search(r"static const struct adreno_speed %s\[\] = \{(.*?)\};" % name, source, re.S)
    if not match:
        return None
    pairs = re.findall(r"\{\s*(\d+)\s*,\s*(\d+)\s*\}", match.group(1))
    return [(int(khz), int(level)) for khz, level in pairs]


def check_soc(source, name, want):
    block = soc_block(source, name)
    if block is None:
        check(False, "there is no soc_%s" % name)
        return
    check(True, "soc_%s is there" % name)

    for key, expected in want.items():
        if key in ("speeds", "speed_count", "default_speed"):
            continue
        raw = field(block, key)
        if isinstance(expected, str):
            check(raw == expected, "soc_%s.%s is %r, not %r" % (name, key, raw, expected))
        elif isinstance(expected, bool):
            check(raw == ("true" if expected else "false"), "soc_%s.%s is %r, not %r" % (name, key, raw, expected))
        else:
            got = number(raw or "")
            check(got == expected, "soc_%s.%s is %r, not %r" % (name, key, got, expected))

    table_name = field(block, "speeds")
    table = speeds(source, table_name) if table_name else None
    check(table is not None, "soc_%s's speed table %r is not there" % (name, table_name))
    if table is None:
        return
    count = number(field(block, "speed_count") or "")
    default = number(field(block, "default_speed") or "")
    check(len(table) == count, "soc_%s says %r speeds, its table has %d" % (name, count, len(table)))
    check(default is not None and 0 <= default < len(table), "soc_%s's default speed %r is not in its table" % (name, default))
    check(table == want["speeds"], "soc_%s's speeds are %r, not %r" % (name, table, want["speeds"]))
    check(table[0][0] == 0 and table[0][1] == 0, "soc_%s's speed table does not start with 0/0" % name)
    for i in range(1, len(table)):
        check(table[i][0] > table[i - 1][0], "soc_%s's speed %d is not faster than the one before" % (name, i))
        check(table[i][1] > table[i - 1][1], "soc_%s's level %d is not above the one before" % (name, i))

    bank = number(field(block, "highest_bank_bit") or "")
    check(bank is not None and bank >= 13, "soc_%s's highest bank bit %r is below 13" % (name, bank))
    mask = number(field(block, "speed_bin_mask") or "")
    shift = number(field(block, "speed_bin_shift") or "")
    width = number(field(block, "speed_bin_bytes") or "")
    if None not in (mask, shift, width):
        check(mask < (1 << (width * 8 - shift)), "soc_%s's fuse mask %#x does not fit %d bytes from bit %d" % (name, mask, width, shift))
    zap = number(field(block, "zap_memory") or "")
    check(zap is not None and (zap == 0 or (zap & 4095) == 0), "soc_%s's zap memory %r is neither unknown nor page-aligned" % (name, zap))
    check(got_ok(block, name), "soc_%s's firmware names are not its own" % name)


def got_ok(block, name):
    images = [field(block, key) for key in ("gmu_firmware", "sqe_firmware", "zap_mdt", "zap_b02")]
    return all(image and image.strip('"').startswith(name + "_") for image in images)


def main():
    source = open(sys.argv[1]).read()

    # the redwood: unchanged since the driver was written for it
    check_soc(source, "a660", {
        "name": '"a660"', "chip_id": 0x06030500, "gpu_name": '"642L"', "name_by_bin": True,
        "speed_bin_fuse": 0x4000 + 0x1e9, "raw_speed_bin_fuse": 0x1e9,
        "speed_bin_bytes": 2, "speed_bin_shift": 5, "speed_bin_mask": 0xff,
        "gaming_bin_fuse": 0x4000 + 0x1f5, "gmem": 512 * 1024, "highest_bank_bit": 14,
        "cp_lpac_fifo": True, "cp_chicken_dbg": True,
        "pc_dbg_eco": 0x00200200, "rb_dbg_eco": 0x04100000,
        "default_speed": 3, "zap_memory": 0x8b71a000,
        "speeds": [(0, 0), (315000, 64), (450000, 128), (550000, 192)],
    })

    # the K40: from the trees and Linux (the driver's comments name every source)
    check_soc(source, "a650", {
        "name": '"a650"', "chip_id": 0x06050002, "gpu_name": '"650"', "name_by_bin": False,
        "speed_bin_fuse": 0x4000 + 0x19b, "raw_speed_bin_fuse": 0,
        "speed_bin_bytes": 1, "speed_bin_shift": 5, "speed_bin_mask": 0x7,
        "gaming_bin_fuse": 0, "gmem": 1024 * 1024 + 128 * 1024, "highest_bank_bit": 16,
        "cp_lpac_fifo": False, "cp_chicken_dbg": False,
        "pc_dbg_eco": 0x00300200, "rb_dbg_eco": 0x04100000,
        "default_speed": 5, "zap_memory": 0x8681a000,
        "speeds": [(0, 0), (305000, 64), (400000, 128), (441600, 144), (490000, 192),
                   (525000, 224), (587000, 256), (670000, 320)],
    })

    # the two rows differ where they must
    a660, a650 = soc_block(source, "a660"), soc_block(source, "a650")
    check(number(field(a660, "chip_id")) != number(field(a650, "chip_id")), "the two SoCs have one chip id")
    check(number(field(a660, "gmem")) != number(field(a650, "gmem")), "the two SoCs have one GMEM size")
    check(number(field(a660, "highest_bank_bit")) != number(field(a650, "highest_bank_bit")), "the two SoCs have one bank bit")

    print("gpu-tables: %d checks, %d failures" % (checks, failures))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
