#!/bin/sh
# Builds aa-most-feeder for QNX 6.5 armv7 in the qnx65-armv7-toolchain:8.5 image (docs/06-audyt.md A66).
# Usage: aa/feeder/build.sh OUTDIR
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
docker run --rm --platform=linux/amd64 -v "$HERE":/src:ro -v "$OUT":/out -w /src qnx65-armv7-toolchain:8.5 bash -c '
set -e
export PATH=/opt/qnx650/host/linux/x86/usr/bin:$PATH QNX_HOST=/opt/qnx650/host/linux/x86 QNX_TARGET=/opt/qnx650/target/qnx6
P=arm-unknown-nto-qnx6.5.0eabi
$P-gcc -O2 -Wall -Wextra -Werror -std=gnu99 -march=armv7-a -mfloat-abi=softfp -mfpu=vfpv3-d16 \
    -ffile-prefix-map=/src=. aa_most_feeder.c -lsocket -o /out/aa-most-feeder
$P-strip /out/aa-most-feeder
$P-readelf -d /out/aa-most-feeder | grep NEEDED'
shasum -a 256 "$OUT/aa-most-feeder"
