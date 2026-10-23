#!/usr/bin/env bash
# Put the iOS 16.5 (20F66, iPhone10,3/10,6) IPSW into firmware/ and verify its MD5.
# The file is checked by size + MD5; a bad or partial file is removed and downloaded again.
# Downloads resume (.part) and retry, so a dropped connection does not restart 6.2 GB.
#
# CHECK_ONLY=1   verify only, do not download (exit 1 when missing/bad)
# FORCE=1        re-download even when the file is already good
# DIR=...        firmware directory (default: <package>/firmware)
#
# The IPSW is the input for rebuilding system.apfs; a plain "boot to iOS" uses boot/system.apfs
# and does not need it.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR=${DIR:-$ROOT/firmware}
NAME='iPhone10,3,iPhone10,6_16.5_20F66_Restore.ipsw'
SIZE=6165698198
MD5='f87b4bd6f3c86fb174ce017b5a5ca97b'
URL='https://updates.cdn-apple.com/2023SpringFCS/fullrestores/032-85130/6AB0D10A-8AF9-4F6C-8CF5-A1B315CABE88/iPhone10,3,iPhone10,6_16.5_20F66_Restore.ipsw'
TARGET="$DIR/$NAME"
PART="$TARGET.part"
MARKER="$DIR/.verified"

mkdir -p "$DIR"
size_of() { wc -c < "$1" | tr -d ' '; }
md5_of() { md5sum "$1" | awk '{print $1}'; }

check_file() { # check_file PATH -> 0 ok
	local p=$1 len
	[ -f "$p" ] || return 1
	len=$(size_of "$p")
	if [ "$len" != "$SIZE" ]; then
		echo "firmware: size $len != expected $SIZE"
		return 1
	fi
	if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$MD5 $SIZE" ]; then
		echo "firmware: already verified (marker)"
		return 0
	fi
	echo "firmware: checking MD5 (6.2 GB, a few seconds)..."
	local got
	got=$(md5_of "$p")
	if [ "$got" != "$MD5" ]; then
		echo "firmware: MD5 mismatch: $got"
		return 1
	fi
	printf '%s %s\n' "$MD5" "$SIZE" > "$MARKER"
	echo "firmware: MD5 OK"
	return 0
}

if [ "${FORCE:-0}" != 1 ] && check_file "$TARGET"; then
	exit 0
fi
if [ "${CHECK_ONLY:-0}" = 1 ]; then
	echo "firmware: missing or invalid: $TARGET" >&2
	exit 1
fi

command -v curl >/dev/null || { echo "firmware: curl is not installed" >&2; exit 1; }
command -v md5sum >/dev/null || { echo "firmware: md5sum is not installed" >&2; exit 1; }

rm -f "$TARGET" "$MARKER"
if [ -f "$PART" ] && [ "$(size_of "$PART")" -gt "$SIZE" ]; then
	rm -f "$PART"
fi

attempt=1
while [ "$attempt" -le 3 ]; do
	echo
	echo "firmware: download attempt $attempt/3 (6.2 GB, resumable)"
	curl -L --fail --retry 5 --retry-delay 3 -C - -o "$PART" "$URL" || echo "firmware: curl exit $?"
	if [ ! -f "$PART" ]; then
		attempt=$((attempt + 1))
		continue
	fi
	got_size=$(size_of "$PART")
	if [ "$got_size" != "$SIZE" ]; then
		echo "firmware: partial $got_size / $SIZE"
		attempt=$((attempt + 1))
		continue
	fi
	got_md5=$(md5_of "$PART")
	if [ "$got_md5" != "$MD5" ]; then
		echo "firmware: MD5 mismatch ($got_md5); starting over"
		rm -f "$PART"
		attempt=$((attempt + 1))
		continue
	fi
	mv "$PART" "$TARGET"
	printf '%s %s\n' "$MD5" "$SIZE" > "$MARKER"
	echo "firmware: downloaded and verified: $TARGET"
	exit 0
done

rm -f "$PART"
echo "firmware: download/verify failed after 3 attempts. Manual download: $URL -> $TARGET (MD5 $MD5)" >&2
exit 1
