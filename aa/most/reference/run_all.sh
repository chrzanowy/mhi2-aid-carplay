#!/bin/sh
# Regenerates every golden directory. Takes about 1.5 minutes.
set -u
S=$(cd "$(dirname "$0")" && pwd)
cd "$S"
PY="python3 -I"
for s in steady burst gap large-idr large-run; do
    echo "=== $s"
    $PY tools/run_scenario.py "$s" --harman
done
echo "=== burst-no-idr (the AA feeder v10 default: request file removed, no IDR sent)"
$PY tools/run_scenario.py burst --out golden/burst-no-idr --idr-on-request -1
echo "=== burst-stock (omonob v1.x without the diasdio patch)"
$PY tools/run_scenario.py burst --out golden/burst-stock --bridge build/altscreen-most-bridge-host-stock
echo "=== steady-block (driver blocks in write() instead of EAGAIN)"
$PY tools/run_scenario.py steady --out golden/steady-block --env HOST_MLB_MODE=block
echo "=== steady-stall (MOST stops draining for 200 ms after block 300)"
$PY tools/run_scenario.py steady --out golden/steady-stall --env HOST_MLB_STALL_AT_BLOCK=300 --env HOST_MLB_STALL_MS=200
echo "=== repeatability: steady again, compared with golden/steady"
$PY tools/run_scenario.py steady --out golden/steady-rerun
$PY tools/ts_compare.py golden/steady golden/steady-rerun
