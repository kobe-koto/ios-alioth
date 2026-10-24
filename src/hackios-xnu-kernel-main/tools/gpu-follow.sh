#!/bin/bash
# gpu-follow.sh — run a kernel on the phone and pull its log as fast as it can be pulled, for an
# experiment that is EXPECTED TO RESET THE PHONE (the Adreno step 20, SESSION-HANDOFF.md §9.5).
#
# Why this exists and not `xl run`:
#   * `xl enter` auto-retries `fastboot boot`. On a kernel that resets the SoC that turns into a
#     boot loop (a reset leaves the phone in fastboot/Android, xl boots it again, it resets again).
#     This script NEVER boots or retries. You put the phone in the resident loader yourself; if it
#     is not there, this prints how and exits.
#   * `xl`'s live-follow is in whole seconds (sleep 2). The fatal write to CP_SQE_CNTL resets the
#     phone within ~0.5–1 s, so a 2 s cadence rides straight over it. This polls every ~150 ms and
#     keeps every snapshot, so the last one before the reset is the state just before it.
#   * The reset takes the whole SoC, so USB vanishes mid-command. The instant the loader stops
#     answering this STOPS — no retry, no "waiting for the watchdog" — reports the last good
#     snapshot, and tells you to cold-boot the phone by hand.
#
# usage:
#   tools/gpu-follow.sh                 # build payload from XL_CMDLINE/XL_RAMDISK, upload, run, follow
#   tools/gpu-follow.sh --payload P.bin # run an already-built payload instead of building one
# env:
#   XL_CMDLINE   kernel boot-args for the run (default: the §9.5 GPU step-20 bisect line below)
#   XL_RAMDISK   ramdisk image (default: boot/root.apfs next to this repo, which carries a650 fw)
#   XL_SECS      loader_return_after seconds (default 25)
#   GAP_MS       milliseconds between log pulls (default 150)
#   OUT          directory for the snapshots (default logs/gpu-follow)
#
# Nothing here writes a partition: only `fastboot stage` (RAM), `oem run`, `oem log`, `get_staged`.
set -u
INVOCATION_DIR=$PWD                                         # where the user ran us (for --payload paths)
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1          # the kernel tree root (tools/ is under it)

K=xnu-src/xnu-8796.121.2/BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837
[ -f "$K" ] || K=prebuilt/mach.development.bcm2837
PHONE=${XDG_RUNTIME_DIR:-/tmp}/hackios-phone
OUT=${OUT:-logs/gpu-follow}
GAP_MS=${GAP_MS:-150}
# keep the gap a sub-second millisecond value (the sleep below is 0.NNN); clamp anything silly
case "$GAP_MS" in ''|*[!0-9]*) GAP_MS=150 ;; esac
[ "$GAP_MS" -lt 20 ] && GAP_MS=20
[ "$GAP_MS" -gt 999 ] && GAP_MS=999
XL_SECS=${XL_SECS:-25}
# Default: GPU step 20, the a6xx_start bisect — HWCG only, protect/bicubic off (adjust as you go).
XL_CMDLINE=${XL_CMDLINE:-"bootcpu=7 cpus=8 adreno_soc=a650 adreno=20 adreno_direct=1 adreno_watch=15 adreno_fullstart=1 adreno_protect=0 adreno_bicubic=0"}
XL_RAMDISK=${XL_RAMDISK:-$(readlink -f ../../boot/root.apfs 2>/dev/null || echo userland/root.apfs)}

PAYLOAD=
case "${1:-}" in
	--payload)
		[ -n "${2:-}" ] || { echo "gpu-follow: --payload needs a file"; exit 1; }
		# resolve against the directory the user ran us from, not the kernel tree we cd'd into
		case "$2" in
			/*) PAYLOAD=$2 ;;
			*)  PAYLOAD=$INVOCATION_DIR/$2 ;;
		esac
		[ -f "$PAYLOAD" ] || { echo "gpu-follow: payload not found: $2 (looked at $PAYLOAD)"; exit 1; }
		;;
	"") ;;
	*) echo "usage: $0 [--payload FILE]"; exit 1 ;;
esac

fb()  { flock -w 90 "$PHONE.lock" timeout "${FB_TIMEOUT:-8}" fastboot "$@" 2>&1; }
is_loader() { fastboot devices 2>/dev/null | grep -q fastboot && fb getvar product 2>/dev/null | grep -q 'product: xnuloader'; }

# --- 1. the loader must already be up; we do not boot it (that is the boot-loop trap) -------------
if ! is_loader; then
	cat >&2 <<EOF
gpu-follow: the phone is not in the resident HackiOS loader.
  This script will NOT boot it for you (auto-retrying a boot on a kernel that resets the phone is
  exactly what loops it). Bring the loader up yourself, once:

      fastboot boot <alioth-boot.img>        # e.g. the mini package's boot/alioth-boot.img
      fastboot getvar product                # should say: xnuloader

  Then run this again. After a run that resets the phone, cold-boot it back to Android by hand
  (hold power), do not let anything re-boot the kernel in a loop.
EOF
	exit 1
fi

mkdir -p "$OUT"
stamp=$(date +%H%M%S)
base="$OUT/gpu-$stamp"
echo "gpu-follow: loader is up (version $(fb getvar version 2>/dev/null | sed -n 's/^version: //p'))"

# --- 2. build the payload unless one was given ----------------------------------------------------
if [ -z "$PAYLOAD" ]; then
	[ -f "$K" ] || { echo "gpu-follow: no kernel at $K (build it first)"; exit 1; }
	[ -f "$XL_RAMDISK" ] || { echo "gpu-follow: ramdisk $XL_RAMDISK not found"; exit 1; }
	PAYLOAD="$base.payload.bin"
	CMDLINE="loader_return_after=$XL_SECS epoch=$(date +%s) $XL_CMDLINE"
	xnuloader/mkpayload.py -o "$PAYLOAD" "kernel=$K" "ramdisk=$XL_RAMDISK" --cmdline "$CMDLINE" >/dev/null \
		|| { echo "gpu-follow: mkpayload failed"; exit 1; }
	echo "gpu-follow: built $PAYLOAD"
	echo "  cmdline: $CMDLINE"
fi

# --- 3. upload (RAM) and start the run ------------------------------------------------------------
echo "gpu-follow: staging payload (RAM only): $PAYLOAD"
stage_out=$(FB_TIMEOUT=40 fb stage "$PAYLOAD")
echo "$stage_out" | grep -q OKAY || { echo "gpu-follow: upload failed:"; echo "$stage_out" | sed 's/^/  /'; exit 1; }
echo "gpu-follow: oem run — the phone may reset during step 20; that is expected"
FB_TIMEOUT=10 fb oem run | grep -q OKAY || { echo "gpu-follow: oem run was refused"; exit 1; }

# --- 4. follow: pull the live log every GAP_MS, keep each snapshot, stop the instant USB drops ----
# A reset takes the whole SoC: fastboot calls start failing. We treat the FIRST failure after the
# run began as the reset and stop — no retry, no bootloop.
echo "gpu-follow: following every ${GAP_MS} ms (Ctrl-C to stop); snapshots at $base.live.N"
deadline=$(( $(date +%s) + XL_SECS + 20 ))
n=0; last_ok=
while :; do
	# refresh the staged buffer with the running kernel's log, then pull it
	if ! FB_TIMEOUT=4 fb oem log | grep -q OKAY; then
		echo "gpu-follow: the loader stopped answering (oem log) — the phone has most likely RESET."
		break
	fi
	snap="$base.live.$n"
	if FB_TIMEOUT=4 fb get_staged "$snap.raw" >/dev/null && [ -s "$snap.raw" ]; then
		tr -d '\0' < "$snap.raw" > "$snap"; rm -f "$snap.raw"
		last_ok="$snap"
		# has the run ended on its own (kernel returned to loader)?
		res=$(FB_TIMEOUT=4 fb getvar result 2>/dev/null | sed -n 's/^result: //p')
		case "$res" in
			""|*running*) ;;
			*) echo "gpu-follow: run ended, result: $res"; break ;;
		esac
	else
		echo "gpu-follow: get_staged failed — the phone has most likely RESET."
		break
	fi
	n=$((n + 1))
	[ "$(date +%s)" -ge "$deadline" ] && { echo "gpu-follow: deadline reached, stopping"; break; }
	sleep "0.$(printf '%03d' "$GAP_MS")"
done

# --- 5. report ------------------------------------------------------------------------------------
echo
if [ -n "$last_ok" ]; then
	full="$base.last.log"; cp "$last_ok" "$full"
	echo "gpu-follow: last good snapshot: $full ($(wc -c < "$full") bytes, snapshot #$n-ish)"
	echo "gpu-follow: the tail of it (the last thing the kernel got to say before the reset):"
	echo "------------------------------------------------------------------------"
	tail -n 25 "$full"
	echo "------------------------------------------------------------------------"
else
	echo "gpu-follow: NO log was captured — the reset beat the first poll."
	echo "  Try a larger pre-write pause in the driver (layer 2) so the state is pulled before the"
	echo "  fatal write, or lower GAP_MS."
fi
if ! is_loader; then
	echo
	echo "gpu-follow: the phone is no longer in the loader. Cold-boot it back to Android BY HAND"
	echo "  (hold power until it restarts). Do not let anything re-boot the kernel in a loop."
fi
