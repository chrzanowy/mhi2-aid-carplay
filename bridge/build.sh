#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds pmcp-most stage 1 (altscreen-most-bridge, CarPlay mode) for QNX 6.5 armv7 (MU1161, AID 791)
# in the qnx65-armv7-toolchain:8.5 image, the same recipe as aa/feeder/build.sh. Builds twice and
# requires the same sha256 (reproducible), strips, prints size, sha256, NEEDED and the imported symbols.
# Usage: bridge/build.sh OUTDIR        (PMCP_MOST_AA=1 also builds the -DALTSCREEN_AA_SINGLE_IDR variant)
# The binary keeps the name altscreen-most-bridge: the mathsls supervisor execs exactly that path.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
[ $# -eq 1 ] || { echo "usage: $0 OUTDIR"; exit 2; }
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
AA=${PMCP_MOST_AA:-0}
docker run --rm --network=none --platform=linux/amd64 -e AA="$AA" -v "$HERE/src":/src:ro -v "$OUT":/out -w /src \
    qnx65-armv7-toolchain:8.5 bash -c '
set -e
export PATH=/opt/qnx650/host/linux/x86/usr/bin:$PATH QNX_HOST=/opt/qnx650/host/linux/x86 QNX_TARGET=/opt/qnx650/target/qnx6
P=arm-unknown-nto-qnx6.5.0eabi
CFLAGS="-O2 -Wall -Wextra -Werror -Wno-unused-function -std=gnu99 -march=armv7-a -mfloat-abi=softfp -mfpu=vfpv3-d16 -ffile-prefix-map=/src=."
build() { # output, extra flags
    o=$1; shift
    $P-gcc $CFLAGS "$@" altscreen_most_bridge.c -lsocket -o "$o"
    $P-strip "$o"
}
build /out/altscreen-most-bridge
build /tmp/second
cmp /out/altscreen-most-bridge /tmp/second || { echo "NOT REPRODUCIBLE"; exit 1; }
echo "reproducible: two builds identical"
$P-gcc --version | head -1
if [ "$AA" = 1 ]; then build /out/altscreen-most-bridge-aa -DALTSCREEN_AA_SINGLE_IDR; fi
for f in /out/altscreen-most-bridge*; do
    case $f in *.txt) continue;; esac
    echo "== $f"
    $P-readelf -d "$f" | grep NEEDED
    $P-readelf -W -D -s "$f" | awk "\$8 == \"UND\" && \$9 != \"\" {print \$9}" | sed "s/@.*//" | sort -u > "$f.imports.txt"
    echo "imports: $(wc -l < "$f.imports.txt")"
done
'
for f in "$OUT"/altscreen-most-bridge*; do
    case $f in *.txt) continue;; esac
    echo "$(basename "$f"): $(wc -c < "$f" | tr -d ' ') bytes, sha256 $(shasum -a 256 "$f" | cut -d' ' -f1)"
done
