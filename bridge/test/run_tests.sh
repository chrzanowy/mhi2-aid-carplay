#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# pmcp-most stage 1 host tests (macOS/Linux, cc). Builds the bridge for the host in its
# ALTSCREEN_BRIDGE_FILE_OUTPUT mode (regular file instead of /dev/mlb/isoTX2), plus the unmodified
# upstream bridge, an ENOMEM-injection build and the synthetic producer, then runs test/harness.py.
# Prints "BRIDGE TESTS: N ok, M failed"; exit status non-zero on any failure.
# Optional: PMCP_TEST_H264=<Annex-B capture> (default: the AA car capture if present, else skipped).
#           ./run_tests.sh [test ...]   with test = steady real-h264 parity force-idr enomem session log
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
B="$HERE/build"
TOOLS=$(cd "$ROOT/../aa/most/test" 2>/dev/null && pwd) || { echo "missing aa/most/test (ts_analyse.py)"; exit 2; }
CC=${CC:-cc}
mkdir -p "$B"
: > "$B/build-results.txt"
CF="-std=gnu99 -O2 -Wall -Wextra -Werror -Wno-unused-function -pthread"
HOST="$CF -DALTSCREEN_BRIDGE_FILE_OUTPUT -include $HERE/shim/host_shim.h"

build() { # name, then compiler arguments
    name=$1; shift
    if "$CC" "$@" 2> "$B/$name.build.log"; then
        echo "ok build $name" >> "$B/build-results.txt"
    else
        echo "FAILED build $name" >> "$B/build-results.txt"; cat "$B/$name.build.log"
    fi
}
build bridge-host $HOST -I "$ROOT/src" -o "$B/bridge-host" "$ROOT/src/altscreen_most_bridge.c" "$HERE/shim/host_shim.c"
build bridge-host-upstream $HOST -I "$ROOT/upstream" -o "$B/bridge-host-upstream" \
    "$ROOT/upstream/altscreen_most_bridge.c" "$HERE/shim/host_shim.c"
# upstream's own test hook: ENOMEM after block 100 and every 60 blocks after it
build bridge-host-enomem $HOST -DALTSCREEN_BRIDGE_TEST_ENOMEM_AT_BLOCKS=100 -DALTSCREEN_BRIDGE_TEST_ENOMEM_REPEAT=60 \
    -I "$ROOT/src" -o "$B/bridge-host-enomem" "$ROOT/src/altscreen_most_bridge.c" "$HERE/shim/host_shim.c"
# the Android Auto variant must keep compiling (not run here; CP is the default)
build bridge-host-aa-flag $HOST -DALTSCREEN_AA_SINGLE_IDR -I "$ROOT/src" -o "$B/bridge-host-aa" \
    "$ROOT/src/altscreen_most_bridge.c" "$HERE/shim/host_shim.c"
build producer -std=gnu99 -O2 -Wall -Wextra -Werror -o "$B/producer" "$HERE/producer.c"
chmod +x "$HERE/fake_dmdt.sh"

H264=${PMCP_TEST_H264:-$ROOT/../../../passat-mhi2-carplay/build/car-logs-20261110b/aa-stream.h264}
[ -f "$H264" ] || H264=-
if grep -q FAILED "$B/build-results.txt"; then
    n_ok=$(grep -c '^ok' "$B/build-results.txt"); n_bad=$(grep -c '^FAILED' "$B/build-results.txt")
    echo "BRIDGE TESTS: $n_ok ok, $n_bad failed"
    exit 1
fi
exec python3 -I "$HERE/harness.py" "$B" "$TOOLS" "$H264" "$@"
