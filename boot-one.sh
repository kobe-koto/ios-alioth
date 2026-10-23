#!/usr/bin/env bash
# One run of HackiOS on the phone: boot the loader from RAM, put the iOS system image and the payload
# into RAM, run the kernel, take screenshots, copy the log out, and go back to Android.
# Nothing is written to a partition: "fastboot boot" and "stage" are RAM only.
#
# This package already contains everything the boot needs (see boot/): the UEFI, the loader, the
# kernel payload, the iOS system image and the GPU firmware (inside root.apfs). firmware/ holds the
# Apple IPSW, which is only the input for rebuilding system.apfs; if it is missing or corrupt,
# fetch-firmware.sh downloads it and checks size + MD5 (SKIP_FIRMWARE=1 skips that check).
#
# usage (Git Bash):  bash boot-one.sh
#   SECS=60 bash boot-one.sh        # let the kernel run longer before the screenshot
#   SHOTS=3 GAP=5 bash boot-one.sh  # three screenshots, 5 s apart
#   SYS= bash boot-one.sh           # kernel only: skip staging the 2.5 GB system image
#   KEEP=1 bash boot-one.sh         # stay in the loader afterwards instead of rebooting
#   PAYLOAD=... IMG=...             # override the payload / loader image
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOT="$ROOT/boot"
for p in "/d/Android/Sdk/platform-tools" "$LOCALAPPDATA/Android/Sdk/platform-tools"; do
	[ -d "$p" ] && PATH="$p:$PATH"
done
export MSYS_NO_PATHCONV=1

SECS=${SECS:-45}
SHOTS=${SHOTS:-3}
GAP=${GAP:-5}
IMG=${IMG:-$BOOT/alioth-boot.img}
SYS=${SYS-$BOOT/system.apfs}     # SYS= (set but empty) means none; ${SYS:-...} would not allow that
PAYLOAD=${PAYLOAD:-$BOOT/run-payload.bin}
TAG=${TAG:-run$(date +%H%M%S)}
SERIAL=${SERIAL:-}
OUT=${OUT:-$ROOT/runs}
mkdir -p "$OUT"
LOG=$OUT/$TAG.log
RAW=$OUT/$TAG.raw
PNG=$OUT/$TAG.png

say() { printf '\n== %s\n' "$*"; }

# Every fastboot call is bounded: with no device in fastboot mode it waits forever ("< waiting for
# any device >"), which looks exactly like the script hanging while the phone sits in Android.
FB=${FB:-fastboot}
fb() { timeout "${FB_T:-30}" "$FB" "$@"; }

say "what this package needs (and does not)"
[ -f "$IMG" ] || { echo "boot-one: missing loader image: $IMG" >&2; exit 1; }
[ -f "$PAYLOAD" ] || { echo "boot-one: missing payload: $PAYLOAD" >&2; exit 1; }
if [ -n "$SYS" ] && [ ! -f "$SYS" ]; then
	echo "boot-one: system image not found: $SYS"
	echo "boot-one: booting the kernel only (the payload's own root.apfs is the root)."
	echo "boot-one: for the full iOS desktop, restore boot/system.apfs or rebuild it from an IPSW"
	echo "          with src/hackios-xnu-userland-main/ios165/fetch.sh + userland/build.sh."
	SYS=
fi
if [ -n "$SYS" ]; then
	echo "images: $(basename "$IMG"), $(basename "$PAYLOAD"), $(basename "$SYS") -- no firmware download needed"
else
	echo "images: $(basename "$IMG"), $(basename "$PAYLOAD") -- kernel-only (no system image)"
fi

say "firmware (rebuild input; not needed for this boot)"
if [ "${SKIP_FIRMWARE:-0}" = 1 ]; then
	echo "skipped (SKIP_FIRMWARE=1)"
elif [ -f "$ROOT/fetch-firmware.sh" ]; then
	if ! bash "$ROOT/fetch-firmware.sh"; then
		echo "boot-one: 固件缺失/校验失败，不影响本次启动，继续。" >&2
	fi
else
	echo "no fetch-firmware.sh; skipping firmware check"
fi

say "phone state"
adb devices | tail -3
if [ -z "$SERIAL" ]; then
	# more than one device makes "adb reboot bootloader" fail ("more than one device/emulator"),
	# and the phone then stays in Android while the fastboot loop runs -- pick the one device.
	serials=$(adb devices | awk '$2 == "device" { print $1 }')
	count=$(printf '%s\n' "$serials" | grep -c .)
	if [ "$count" -ne 1 ]; then
		echo "boot-one: expected one Android device, found $count: $(echo $serials); set SERIAL=<serial>" >&2
		exit 1
	fi
	SERIAL=$serials
fi
echo "serial: $SERIAL"
ADB="adb -s $SERIAL"
$ADB shell true >/dev/null 2>&1 || { echo "boot-one: $SERIAL is not answering adb" >&2; exit 1; }

say "to the bootloader"
$ADB reboot bootloader >/dev/null 2>&1
fbdev=
for i in $(seq 1 30); do
	if fb devices 2>/dev/null | grep -q fastboot; then fbdev=1; break; fi
	sleep 1
done
if [ -z "$fbdev" ]; then
	echo "boot-one: $SERIAL never reached the bootloader (still in Android); giving up instead of hanging" >&2
	exit 1
fi
fb devices | tail -1

say "boot the loader (fastboot boot: RAM only)"
fb boot "$IMG" 2>&1 | tail -2
up=
for i in $(seq 1 40); do
	if fb getvar product 2>&1 | grep -q "product: *xnuloader"; then up=1; break; fi
	sleep 1
done
[ -n "$up" ] || { echo "boot-one: the loader did not come up (is this still the bootloader?)" >&2; exit 1; }
echo "the loader is up"

# SYS= (empty): no system image -- the payload's own ramdisk (root.apfs) is then the root, which
# is all a kernel-only run (adreno=..., adreno_return=1) needs, and it saves staging 2.5 GB.
if [ -n "$SYS" ]; then
	say "resident buffer for the system image, then the image itself"
	fb oem ramdisk 2>&1 | tail -1
	time timeout 900 "$FB" stage "$SYS" 2>&1 | tail -1
else
	say "no system image: the payload's ramdisk is the root"
	fb oem ramdisk none 2>&1 | tail -1
fi

say "the payload"
timeout 300 "$FB" stage "$PAYLOAD" 2>&1 | tail -1

say "run, then $SECS s of the kernel"
fb oem run 2>&1 | tail -1
sleep "$SECS"

say "screenshot"
shot() { # shot NAME
	local name=$1 geom
	geom=$(fb getvar screen 2>&1 | sed -n 's/^screen: //p')
	if [ -z "$geom" ] || ! fb oem screenshot 2>&1 | grep -q OKAY; then
		echo "no screen geometry or no screenshot"
		return 0
	fi
	fb get_staged "$name.raw" >/dev/null 2>&1
	[ -s "$name.raw" ] || return 0
	local python_bin=${PY:-}
	if [ -z "$python_bin" ]; then
		python_bin=$(command -v python3 || command -v python || true)
	fi
	[ -n "$python_bin" ] || { echo "no python (set PY=/path/to/python)"; return 0; }
	"$python_bin" - "$name.raw" "$name.png" $geom <<'PY'
import struct, sys, zlib
raw, out, width, height, stride = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:6])
data = open(raw, 'rb').read()
rows = bytearray()
for y in range(height):
    line = data[y * stride:y * stride + width * 4]
    rows.append(0)
    rgb = bytearray(width * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
    rows += rgb
def chunk(t, d):
    c = t + d
    return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
png = (b'\x89PNG\r\n\x1a\n'
       + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
       + chunk(b'IDAT', zlib.compress(bytes(rows), 6))
       + chunk(b'IEND', b''))
open(out, 'wb').write(png)
print("PNG %s: %d x %d, %d bytes" % (out, width, height, len(png)))
PY
	rm -f "$name.raw"
}
shot "$TAG"
i=1
while [ "$i" -lt "$SHOTS" ]; do
	sleep "$GAP"
	shot "$TAG-$i"
	i=$((i + 1))
done

say "log"
fb oem log 2>&1 | tail -1
fb get_staged "$LOG" >/dev/null 2>&1
if [ -s "$LOG" ]; then
	tr -d '\0' < "$LOG" > "$LOG.txt"
	echo "log: $LOG.txt ($(wc -c < "$LOG.txt") bytes)"
fi

if [ "${KEEP:-0}" = 1 ]; then
	echo
	echo "left in the loader (KEEP=1): 'fastboot reboot' when done"
else
	say "back to Android"
	fb reboot >/dev/null 2>&1
	for i in $(seq 1 90); do
		$ADB devices 2>/dev/null | grep -q "device$" && break
		sleep 1
	done
	$ADB devices | tail -2
fi
