#!/bin/bash
# Build and run the tests of the GPU driver's arithmetic and of the two SoCs' rows
# (bsd/sys/redwood_gpu_layout.h, struct adreno_soc in bsd/dev/redwood_adreno.c) on this machine,
# under the address and undefined-behaviour sanitizers. Nothing here needs the phone.
set -e
HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
K=$ROOT/xnu-src/xnu-8796.121.2                 # the kernel tree being worked in, or else the copies that are in git
[ -f "$K/bsd/sys/redwood_gpu_layout.h" ] || K=$ROOT/xnu/files
B=$ROOT/xnu-deps/build/gpu-test
rm -rf "$B"
mkdir -p "$B/inc/sys"
ln -s "$K/bsd/sys/redwood_gpu_layout.h" "$B/inc/sys/"
FLAGS="-std=gnu11 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all"
${CC:-cc} $FLAGS -I"$B/inc" -o "$B/test" "$HERE/test_gpu.c"
"$B/test"
python3 "$HERE/test_tables.py" "$K/bsd/dev/redwood_adreno.c"
