#!/bin/sh
# Builds omonob's altscreen-most-bridge (v1.x behaviour + diasdio) and harman-f's
# direct_ts_parity for the host. Everything is built under /tmp/bridge-stage0/build.
set -eu
S=$(cd "$(dirname "$0")" && pwd)
B="$S/build"
rm -rf "$B"
mkdir -p "$B/src"

# 1. pristine sources must match SOURCE.txt
( cd "$S/third_party/omonob" && tail -n 4 SOURCE.txt | shasum -a 256 -c - )

# 2. copy the bridge source and apply the flag-guarded v1.x/diasdio patch
cp "$S/third_party/omonob/altscreen_most_bridge.c" "$S/third_party/omonob/altscreen_frame_protocol.h" "$B/src/"
( cd "$B/src" && patch -s -p1 < "$S/patches/omonob-v1x-diasdio.patch" )

CFLAGS="-std=gnu99 -O2 -g -Wall -Wno-unused-function -pthread"

# host_mlb.c is compiled on its own: it must see the real write()/close()
clang $CFLAGS -c -o "$B/host_mlb.o" "$S/host/host_mlb.c"

# 3. the bridge as deployed (v1.x + diasdio)
#    -I host comes after the source directory, so host/cpmap_*.h replace the v2 headers
clang $CFLAGS -DALTSCREEN_V1X -DALTSCREEN_DIASDIO -I "$S/host" -include "$S/host/host_shim.h" \
    -o "$B/altscreen-most-bridge-host" "$B/src/altscreen_most_bridge.c" "$B/host_mlb.o"
# 4. the same without diasdio (stock omonob v1.x c846e505), for comparison
clang $CFLAGS -DALTSCREEN_V1X -I "$S/host" -include "$S/host/host_shim.h" \
    -o "$B/altscreen-most-bridge-host-stock" "$B/src/altscreen_most_bridge.c" "$B/host_mlb.o"

# 5. harman-f direct_ts_parity, host build: no devctl (__QNXNTO__ unset), regular-file output
#    paced by its own 12.288 Mbit/s clock. Its hard-coded /tmp/mibr-* marker/status paths are
#    rewritten into build/harman-run/ (sed on the build copy only) so nothing is written outside
#    /tmp/bridge-stage0.
H="$B/harman/modules/carplay/source"
mkdir -p "$B/harman-run/root" "$B/harman"
cp -R "$S/third_party/harman-f/modules" "$B/harman/"
sed -i '' "s#\"/tmp/mibr-#\"$B/harman-run/mibr-#g" "$H/direct-ts-parity/direct_ts_parity.c" "$H/altscreen111-gen2/include/alt111_recovery.h"
if clang $CFLAGS -DMIBR_ROOT_DIR="\"$B/harman-run/root\"" -o "$B/direct-ts-parity-host" \
        "$H/direct-ts-parity/direct_ts_parity.c" 2> "$B/harman-build.log"; then
    echo "harman-f: built"
else
    echo "harman-f: build failed, see $B/harman-build.log"
fi
echo "built: $B/altscreen-most-bridge-host $B/altscreen-most-bridge-host-stock"
