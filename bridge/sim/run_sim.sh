#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# fake-car (docs/28): builds the real supervisor and the pmcp-most stage 2 bridge for the host, with the channel in
# the car process (sim_mlb.c instead of aa/most/test/host_mlb.c; aa/ unchanged), then runs fakecar.py.
# ./run_sim.sh [scenario ...]   prints "FAKECAR TESTS: N ok, M failed"
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
AAM="$ROOT/../aa/most"
B="$HERE/build"
CC=${CC:-cc}
mkdir -p "$B"
CF="-std=gnu99 -O2 -Wall -Wextra -Werror -Wno-unused-function -pthread"
fail=0
"$CC" $CF -DMOST_HOST_SIM -include "$ROOT/test/shim/host_shim.h" -I "$ROOT/src" -I "$ROOT/contract" -I "$AAM" \
    -o "$B/bridge-sim" "$ROOT/src/pmcp_most_lib.c" "$ROOT/src/pmcp_gate.c" "$ROOT/test/shim/host_shim.c" \
    "$AAM/ts_mux.c" "$AAM/most_writer.c" "$HERE/sim_mlb.c" || fail=1
"$CC" $CF -I "$ROOT/contract" -o "$B/pmcp-most-sup" "$ROOT/src/pmcp_most_sup.c" \
    "$ROOT/contract/pmcp_most_producer.c" || fail=1
"$CC" -std=gnu99 -O2 -Wall -Wextra -Werror -o "$B/producer" "$ROOT/test/producer.c" || fail=1
# stage 2: the real AA feeder (aa/ compiled, never edited) on the same simulated channel
AAF="$ROOT/../aa/feeder"
"$CC" -O2 -Wall -Wextra -Werror -std=gnu99 -pthread -DMOST_HOST_SIM -o "$B/feeder-sim" "$AAF/aa_most_feeder.c" \
    "$AAF/h264_ka.c" "$AAM/ts_mux.c" "$AAM/most_writer.c" "$HERE/sim_mlb.c" || fail=1
[ $fail = 0 ] || { echo "FAKECAR TESTS: 0 ok, 1 failed (build)"; exit 1; }
exec python3 -I "$HERE/fakecar.py" "$B" "$@"
