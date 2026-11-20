#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# pmcp-most stage 1 host tests (macOS/Linux, cc). Builds the bridge for the host in its
# ALTSCREEN_BRIDGE_FILE_OUTPUT mode (regular file instead of /dev/mlb/isoTX2), plus the unmodified
# upstream bridge, an ENOMEM-injection build and the synthetic producer, then runs test/harness.py.
# Prints "BRIDGE TESTS: N ok, M failed"; exit status non-zero on any failure.
# Optional: PMCP_TEST_H264=<Annex-B capture> (default: the AA car capture if present, else skipped).
#           ./run_tests.sh [test ...]   with test = steady real-h264 parity force-idr enomem session gate log events
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
KIT="$ROOT/src/pmcp_gate.c"   # stage 1b: consumer gate, verbatim functions of the contract kit

build() { # name, then compiler arguments
    name=$1; shift
    if "$CC" "$@" 2> "$B/$name.build.log"; then
        echo "ok build $name" >> "$B/build-results.txt"
    else
        echo "FAILED build $name" >> "$B/build-results.txt"; cat "$B/$name.build.log"
    fi
}
build bridge-host $HOST -I "$ROOT/src" -I "$ROOT/contract" -o "$B/bridge-host" "$ROOT/src/altscreen_most_bridge.c" \
    "$KIT" "$HERE/shim/host_shim.c"
build bridge-host-upstream $HOST -I "$ROOT/upstream" -o "$B/bridge-host-upstream" \
    "$ROOT/upstream/altscreen_most_bridge.c" "$HERE/shim/host_shim.c"
# upstream's own test hook: ENOMEM after block 100 and every 60 blocks after it
build bridge-host-enomem $HOST -DALTSCREEN_BRIDGE_TEST_ENOMEM_AT_BLOCKS=100 -DALTSCREEN_BRIDGE_TEST_ENOMEM_REPEAT=60 \
    -I "$ROOT/src" -I "$ROOT/contract" -o "$B/bridge-host-enomem" "$ROOT/src/altscreen_most_bridge.c" "$KIT" \
    "$HERE/shim/host_shim.c"
# slow-write congestion (every 4th MOST write 35 ms): the fixed recovery rule and, as a control, the old one
SLOW="-DPMCP_TEST_SLOW_WRITE_EVERY=4U -DPMCP_TEST_SLOW_WRITE_US=35000"
build bridge-host-slow $HOST $SLOW -I "$ROOT/src" -I "$ROOT/contract" -o "$B/bridge-host-slow" \
    "$ROOT/src/altscreen_most_bridge.c" "$KIT" "$HERE/shim/host_shim.c"
build bridge-host-slow-old $HOST $SLOW -DPMCP_RECOVERY_FAST_STREAK_REQUIRED=8U -I "$ROOT/src" -I "$ROOT/contract" \
    -o "$B/bridge-host-slow-old" "$ROOT/src/altscreen_most_bridge.c" "$KIT" "$HERE/shim/host_shim.c"
# stage 1c: event file limit 1024 B and a 10-digit status pid (QNX pid_t), for the events test
build bridge-host-events $HOST -DPMCP_MOST_EVENTS_LIMIT=1024U -DPMCP_STATUS_PID=2147483647L -I "$ROOT/src" \
    -I "$ROOT/contract" -o "$B/bridge-host-events" "$ROOT/src/altscreen_most_bridge.c" "$KIT" "$HERE/shim/host_shim.c"
# the Android Auto variant must keep compiling (not run here; CP is the default)
build bridge-host-aa-flag $HOST -DALTSCREEN_AA_SINGLE_IDR -I "$ROOT/src" -I "$ROOT/contract" -o "$B/bridge-host-aa" \
    "$ROOT/src/altscreen_most_bridge.c" "$KIT" "$HERE/shim/host_shim.c"
# stage 2: the same ring/contract consumer on the AA MOST output library (aa/most ts_mux + most_writer, compiled,
# never edited), with the simulated isoTX2 of aa/most/test/host_mlb.c
AAM="$ROOT/../aa/most"
build bridge-host-lib $CF -DMOST_HOST_SIM -include $HERE/shim/host_shim.h -I "$ROOT/src" -I "$ROOT/contract" -I "$AAM" \
    -o "$B/bridge-host-lib" "$ROOT/src/pmcp_most_lib.c" "$KIT" "$HERE/shim/host_shim.c" "$AAM/ts_mux.c" \
    "$AAM/most_writer.c" "$AAM/test/host_mlb.c"
build producer -std=gnu99 -O2 -Wall -Wextra -Werror -o "$B/producer" "$HERE/producer.c"
# stage 5: the MOST supervisor v1 (src/pmcp_most_sup.c) with the contract library
build supervisor-host $CF -I "$ROOT/contract" -o "$B/pmcp-most-sup" "$ROOT/src/pmcp_most_sup.c" "$ROOT/contract/pmcp_most_producer.c"
chmod +x "$HERE/fake_dmdt.sh"

H264=${PMCP_TEST_H264:-$ROOT/../../../passat-mhi2-carplay/build/car-logs-20261110b/aa-stream.h264}
[ -f "$H264" ] || H264=-
if grep -q FAILED "$B/build-results.txt"; then
    n_ok=$(grep -c '^ok' "$B/build-results.txt"); n_bad=$(grep -c '^FAILED' "$B/build-results.txt")
    echo "BRIDGE TESTS: $n_ok ok, $n_bad failed"
    exit 1
fi
# AA's condition for stage 2 (2026-11-16): the bridge uses aa/most as it is and never changes aa/. The output library
# must match origin/release-candidate; the rest of aa/ moves only with AA's own commits (feeder v16, 2026-11-18), so
# only uncommitted changes there fail.
AA_DIFF=$(cd "$ROOT/.." && git diff --stat origin/release-candidate -- aa/most 2>/dev/null; git status --porcelain -- aa 2>/dev/null)
python3 -I "$HERE/harness.py" "$B" "$TOOLS" "$H264" "$@"; rc1=$?
echo "== stage 2 (bridge-host-lib, AA MOST output library)"
PMCP_TEST_BRIDGE=bridge-host-lib python3 -I "$HERE/harness.py" "$B" "$TOOLS" "$H264" "$@"; rc2=$?
if [ -z "$AA_DIFF" ]; then echo "ok     aa/most unchanged against origin/release-candidate, aa/ clean"; rc3=0
else echo "FAILED aa/most differs from origin/release-candidate or aa/ has local changes:"; echo "$AA_DIFF"; rc3=1; fi
echo "== stage 5 (MOST supervisor v1)"
python3 -I "$HERE/sup_test.py" "$B/pmcp-most-sup"; rc4=$?
[ $rc1 = 0 ] && [ $rc2 = 0 ] && [ $rc3 = 0 ] && [ $rc4 = 0 ]
